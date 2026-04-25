# GSI Error-Based Skip Handling - High-Level Design Proposal

**Status:** Pre-implementation design proposal
**Audience:** Engineering + tech lead review
**Scope:** Quarter GSI generation pipeline only
**Source of truth:** Current `src/wd/qtr/gsi_builder/` implementation
**Supporting docs:** `docs/gsi-error-based-exclusion-analysis.md`, `docs/gsi-error-skip-master-design.md`, `docs/project-end-to-end.md`

This is a short, practical design intended for a technical discussion before any code changes are made. It is intentionally lighter than the existing master design document and focuses on the smallest credible architecture that satisfies the ticket.

---

## 1. Current Flow Summary

### Main Modules / Files Involved in GSI Generation

| File | Role |
|------|------|
| `src/wd/qtr/gsi_builder/main.py` | Notebook-style entrypoint. Loads config, builds Spark, opens Redshift/Postgres connections, defines `process_site_event()`, calls `main()`. |
| `src/wd/qtr/gsi_builder/orchestrator.py` | Loads mappings once, fans queued site records out across a `ThreadPoolExecutor`. |
| `src/wd/qtr/gsi_builder/db_connection.py` | All Redshift reads (workers, tax, organizations, queued outbound files) and writes (outbound_file status). PostgreSQL reads for GI1/GI2 metadata. |
| `src/wd/qtr/gsi_builder/gsi_mappings.py` | Builds worker + address mappings from GI1/GI2, lazily fetches `TAX_MAPPINGS` from a tax-code-mapping API, plus static fallbacks. |
| `src/wd/qtr/gsi_builder/gsi_formatter.py` | `apply_gsi_mappings()` formats worker fields; `format_tax_data_df()` formats tax fields and merges the worker-level F/S/L fields into the matching jurisdictions. |
| `src/wd/qtr/gsi_builder/mandatory_fields_validator.py` | Detects missing mandatory tax mappings and back-fills zero rows. |
| `src/wd/qtr/gsi_builder/s3_writer.py` | File header, organization header (helper currently unused), trailer, and Volume write. |
| `src/wd/qtr/gsi_builder/outbound_file_status.py` | Status enum (`QUEUED`, `GENERATING`, `GENERATED`, `FAILED`, plus unused values). |
| `src/wd/qtr/gsi_builder/flow_validator.py` | Static config validation. |

### End-to-End Flow (verified)

1. `main()` queries `outbound_file` for `status='QUEUED' AND file_type='QUARTER'`.
2. `orchestrator.process_sites_parallel()` loads mappings once and runs sites in parallel threads (cap = `min(records, 4)`).
3. Per site: status -> `GENERATING`; companies fetched via `query_site_organizations()`.
4. Per company: workers fetched via `query_workers()`, formatted by `apply_gsi_mappings()`. Worker-level `EE` columns become employee lines; `F`, `S`, `L` columns are stashed into `worker_level_df`.
5. Tax rows fetched via `query_all_worker_tax()`, run through `mandatory_fields_validator`, then formatted by `format_tax_data_df()` which joins `worker_level_df` per jurisdiction class.
6. Worker + tax + per-company headers + file header + trailer are unioned and written by `S3Writer.write_gsi_dataframe()` to a Databricks Volume.
7. `outbound_file` -> `GENERATED` (success) or `FAILED` (exception); SMTP email sent.

### Where Validation Errors Are Produced and Consumed Today

| Layer | Behavior in current code |
|-------|--------------------------|
| Config validation | `flow_validator.validate_config()` raises before Spark starts. |
| Mandatory tax field validation | `validate_mandatory_fields()` logs gaps; `ensure_mandatory_fields()` back-fills zero rows so the file is schema-complete. |
| Runtime/data exceptions | Bubble up, caught by `process_site_event()`, set `outbound_file` to `FAILED`, send email. |
| `onetax.company_errors` and `onetax.error_catalog` | **Not read anywhere.** No reader, no rule layer, no exclusion logic. |
| Reporting vs. non-reporting GSI classification | **Not present in code.** Mappings only carry `gsi_level ∈ {EE,F,S,L}` and an optional `mandatory` flag. |

---

## 2. Problem Summary

### In Simple Technical Terms

The job currently produces the GSI file **unconditionally** from whatever data is in Redshift. There is no point in the pipeline that asks: "should this worker / jurisdiction / GSI code actually be emitted given known data-quality errors?" The ticket wants a generic, category-driven decision layer that can suppress worker codes, tax codes, reporting codes, and non-reporting codes when validation errors flagged as MF-impact (`impacts_deposit`) or Agency-impact (`impacts_filing`) exist.

### Confirmed From Code vs. Assumed From Ticket Intent

**Confirmed from code:**
- The pipeline has clear, separable stages where filtering can be inserted (worker DataFrame, tax DataFrame, line assembly).
- `worker_sk`, `branch_code`, `company_code`, and jurisdiction (`F` / state / state+local) are available before any text line is built.
- Mappings carry `gsi_code`, `gsi_level`, and `mandatory`; nothing else.
- No table named `company_errors` or `error_catalog` is queried anywhere in `src/`.
- The job already runs per `(site, year, quarter)` with all company context known up front - the natural integration point exists.

**Assumed from ticket intent (must be validated with product/business):**
- `onetax.company_errors` and `onetax.error_catalog` exist in the same Redshift schema this job already reads from. (Ticket and analysis doc both say so; not verifiable from the repo.)
- `impacts_deposit = MF impact` and `impacts_filing = Agency impact`. (Stated in the analysis doc; needs business confirmation.)
- Errors should be evaluated only for `resolution_status = 'Open'` and `write_status = 'PENDING'`.
- "Reporting vs. non-reporting" is meaningful and will be added as a new piece of mapping metadata. The current code does not classify codes this way.
- The mapping from a specific error category to a specific skip scope is a **business decision** that must be configurable, not embedded in code.

---

## 3. Recommended High-Level Design

### Mental Model

Introduce a thin **Skip Decision Layer** between data retrieval and GSI formatting. Errors become facts, facts become categories, categories resolve to skip scopes, and formatters receive an already-resolved decision object - they never see raw error rows.

```
Errors (Redshift)
   |
   v
Error Reader  ->  Category Resolver  ->  Skip Decision Set  ->  Worker / Tax Formatter Filters
                          ^                       |
                          |                       v
                  Rule Catalog (config)     Audit Log + write_status update
```

### How Errors Should Be Categorized

A **two-step** classification:

1. **Raw error -> Normalized category.** Driven primarily by `error_catalog.category` (e.g. `Registration`, `WagePlan`, `Validation`), modified by `error_type` (e.g. `TAX_ID`, `SSN`, `CA_WAGE_PLAN`) and the impact flags (`impacts_deposit`, `impacts_filing`).
2. **Normalized category -> Skip scope(s).** Driven by a separate **rule catalog** so the business can change behavior without code changes.

Categories should be small, business-readable buckets (illustrative): `COMPANY_TAX_ID_ERROR`, `EMPLOYEE_PROFILE_ERROR`, `JURISDICTION_REGISTRATION_ERROR`, `WAGE_PLAN_ERROR`. The exact list is a product decision.

### How Categories Should Drive Skip Behavior

Use a fixed, ordered set of skip **scopes**. A category maps to one or more scopes plus an entity target.

| Scope | Effect |
|-------|--------|
| `NO_SKIP` | Error is logged but emits nothing. |
| `SKIP_GSI_CODE` | Drop one or more specific GSI codes. |
| `SKIP_REPORTING_GSI_CODES` | Drop all codes classified as reporting. |
| `SKIP_NON_REPORTING_GSI_CODES` | Drop all codes classified as non-reporting. |
| `SKIP_TAX_JURISDICTION` | Drop tax output for a specific jurisdiction (worker/company scoped). |
| `SKIP_ALL_TAX_FOR_EMPLOYEE` | Drop all tax rows for one worker. |
| `SKIP_ENTIRE_EMPLOYEE` | Drop the worker's employee + tax lines. |
| `SKIP_COMPANY_TAX_OUTPUT` | Drop tax output for the whole company. |
| `SKIP_COMPANY_OUTPUT` | Drop everything for the company. |

Precedence is highest -> lowest in the order above. When multiple errors apply to the same entity, the broadest applicable scope wins; independent narrow scopes are unioned. `NO_SKIP` is the default and only applies when nothing stronger fires.

### How Decisions Should Affect Each Output Type

| Output | Where the decision is applied |
|--------|------------------------------|
| Employee (EE) lines | Inside `apply_gsi_mappings()`, before `build_employee_lines_udf()` runs - drop columns or filter the worker row. |
| Worker fields merged into tax lines (F/S/L) | At `worker_level_df` construction in `process_site_event()` - drop level entries or filter rows. |
| Tax rows / tax GSI codes | Inside or just before `format_tax_data_df()` - filter the tax DataFrame by `(worker_sk, jurisdiction, tax_type, gsi_code)`. |
| Reporting / non-reporting groups | Filter at both worker and tax formatting after a `reporting_group` field is added to the mapping metadata. |
| File header / company header / trailer | Unaffected, except the trailer's line count naturally reflects fewer lines. |

The formatter never asks "why is this excluded?" - it only asks "is this in the resolved decision set?".

---

## 4. Integration Approach

### Best Place to Introduce This Design

Inside `process_site_event()` in `main.py`, **after** `query_site_organizations()` returns the company list and **before** the per-company worker/tax queries run. This is the first point where the job knows the full `(site, branch, company, year, quarter)` context and still has structured DataFrames - not text - to filter.

A new module `src/wd/qtr/gsi_builder/error_handler.py` (working name) would own:
- error retrieval,
- category normalization,
- rule-catalog lookup,
- decision merging,
- audit logging,
- the eventual `company_errors.write_status` write-back.

### Modules Likely Impacted

| Module | Conceptual change |
|--------|-------------------|
| `db_connection.py` | Add a reader for `company_errors` joined to `error_catalog` and a writer for `company_errors.write_status`. |
| `error_handler.py` (new) | Owns the entire decision layer. |
| `main.py` | Calls the decision layer per company; passes the resulting decision object into worker/tax stages. |
| `gsi_formatter.py` | Accepts a decision object as an optional argument; filters fields/rows accordingly. Defaults to no-op when none is supplied. |
| `gsi_mappings.py` | Add a `reporting_group` field on each mapping (sourced from GI1/GI2 metadata or a config file). |
| `mandatory_fields_validator.py` | Run **after** decision resolution so we don't back-fill defaults for tax scopes that are about to be dropped. |
| `logger.py` / call sites | Add structured "skip decision applied" logs. |

### How to Minimize Disruption

- The decision layer is **additive**: with no rules and no errors, the existing pipeline behaves exactly as it does today.
- Worker / tax queries, mapping loading, line-splitting UDFs, header/trailer generation, and the writer are not refactored.
- Roll out in phases: (1) read and log errors only; (2) resolve and log proposed skips with no effect; (3) enable narrow scopes (`SKIP_GSI_CODE`, `SKIP_TAX_JURISDICTION`); (4) enable broader scopes; (5) start writing back `company_errors.write_status` once behavior is trusted.

---

## 5. Design Principles

### Extensibility

- New error categories are a **rule-catalog edit**, not a code change.
- New skip scopes are added by extending the scope enum and the formatter filter; the rest of the pipeline is unaffected.
- Reporting / non-reporting groups are a metadata addition, not a structural change.

### Maintainability

- Three clean layers: **read errors**, **decide**, **filter**. Each has one job and one place to change.
- Formatters stay focused on formatting. Business rules never leak into `apply_gsi_mappings()` or `format_tax_data_df()`.
- One decision object per `(site, branch, company)` keeps state explicit and easy to test.

### Backward Compatibility

- Default behavior with zero rules or zero errors equals current output, byte-for-byte.
- Unknown categories resolve to `NO_SKIP` with a warning log so missing rules surface but don't break generation.
- If the rule catalog or `company_errors` table is unreachable, the job continues with current behavior plus a high-visibility warning - **fail-open** by default. (Fail-closed can later be a per-rule policy.)

### Observability of Skip Decisions

Every applied decision should produce a structured log line carrying at least:

- `site_id`, `branch_code`, `company_code`, `year`, `quarter`
- `error_code`, `legacy_error_code`, `category`, `impacts_deposit`, `impacts_filing`
- resolved `scope`
- target `worker_sk` / `jurisdiction` / `tax_type` / `gsi_code` (whichever apply)
- before/after counts of worker lines and tax lines

Optionally, write a row per applied decision back to a small audit table so analysts can answer "why was this code missing in last quarter's file?" without re-running the job.

---

## 6. Final Recommendation

**Build a thin, configurable, additive Skip Decision Layer that sits between data retrieval and GSI formatting. Do not modify the existing query, mapping, formatting, or writer code beyond adding a single optional decision parameter.**

Concretely, the recommended direction is:

1. **One new module** (`error_handler.py`) that owns reading `company_errors` + `error_catalog`, normalizing them into categories, evaluating them against a rule catalog, and emitting an immutable decision object per company.
2. **One small change to `db_connection.py`** to add the error reader and the `write_status` updater.
3. **One small change to `main.py`** to invoke the decision layer per company and pass the decision object into existing worker/tax stages.
4. **One small change to `gsi_formatter.py`** to optionally filter by the decision object.
5. **One metadata addition** in `gsi_mappings.py` for the reporting / non-reporting group, sourced ideally from GI1/GI2 to keep the static fallback honest.
6. **Rule catalog** lives initially as a versioned config file in the repo (fast to iterate); migrates to a database-managed rule table once business rules stabilize.
7. **Phased rollout** with logging-only stages before any behavior change, and `company_errors.write_status` updates only after skip behavior is reliably applied.

This direction is right for this codebase because:

- The pipeline already has clean, separable stages - we don't need a rewrite.
- The current code has zero error-driven exclusion, so any non-trivial change is greenfield; keeping the change minimal and additive is the lowest-risk path.
- A category-driven, rule-catalog approach satisfies the ticket's explicit "generic, not hardcoded per error" requirement.
- Phased rollout protects every existing tax filing while the rules are tuned.

The two highest-leverage open questions to confirm with the business **before** coding are:

1. Which database (Redshift or PostgreSQL) actually owns `company_errors` and `error_catalog`?
2. The mapping from each error category to a skip scope - this is a product decision, not an engineering one, and the design assumes it will be supplied as configuration.

Once those are answered, the engineering work is small, well-bounded, and safe to roll out incrementally.
