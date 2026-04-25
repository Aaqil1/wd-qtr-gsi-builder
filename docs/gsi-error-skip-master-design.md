# GSI Error-Based Skip Handling - Master Architecture Design

**Status:** Architecture-first proposal  
**Scope:** Quarter GSI generation and dynamic skip handling  
**Code generation:** Not included  
**Primary source of truth:** Current repository implementation  
**Supporting reference:** `docs/gsi-error-based-exclusion-analysis.md`  

---

## 1. Current Repository Understanding

### Main Modules Involved In Quarter GSI Generation

| Area | File / Module | Current Role |
|------|---------------|--------------|
| Job startup and site flow | `src/wd/qtr/gsi_builder/main.py` | Loads config, initializes Spark and connections, queries queued files, processes sites and companies, combines lines, writes output, updates status. |
| Parallel orchestration | `src/wd/qtr/gsi_builder/orchestrator.py` | Loads GSI mappings once and runs queued site records in parallel threads. |
| Redshift and PostgreSQL access | `src/wd/qtr/gsi_builder/db_connection.py` | Reads queued outbound files, site organizations, worker data, tax data, GI1/GI2 metadata, and writes outbound status updates. |
| Worker and tax formatting | `src/wd/qtr/gsi_builder/gsi_formatter.py` | Converts worker and tax DataFrames into GSI code/value strings and final line fragments. |
| Mapping metadata | `src/wd/qtr/gsi_builder/gsi_mappings.py` | Builds worker/address mappings from GI1/GI2 where possible, falls back to static mappings, lazily loads tax mappings from API plus GI1 metadata. |
| Mandatory tax field behavior | `src/wd/qtr/gsi_builder/mandatory_fields_validator.py` | Finds mandatory tax mappings and adds default tax records for missing mandatory fields. |
| Output writer | `src/wd/qtr/gsi_builder/s3_writer.py` | Generates file header/trailer and writes the final single text file to a Databricks Volume path. |
| Status enum | `src/wd/qtr/gsi_builder/outbound_file_status.py` | Defines outbound file statuses such as `QUEUED`, `GENERATING`, `GENERATED`, and `FAILED`. |
| Environment config | `src/wd/qtr/gsi_builder/config/*.py` | Loads Redshift/PostgreSQL/S3/Kafka/Splunk/application settings by environment. |

### Current Quarter GSI Flow

The current generation flow is centered on `main.py`.

1. `main()` calls `db_conn.query_queued_outbound_files()`.
2. `orchestrator.process_sites_parallel()` loads `gsi_mappings` and `address_mappings`.
3. `process_site_event()` updates the queued file to `GENERATING`.
4. It gets branch/company records through `query_site_organizations()`.
5. For each company, it queries workers through `query_workers()`.
6. Worker fields are formatted by `apply_gsi_mappings()`.
7. Worker-level `EE` fields become employee lines.
8. Worker fields classified as `F`, `S`, or `L` are held as `worker_level_df` and merged into matching tax jurisdiction lines later.
9. Tax records are queried through `query_all_worker_tax()`.
10. Mandatory tax fields are checked and filled through `mandatory_fields_validator.py`.
11. Tax rows are formatted by `format_tax_data_df()`.
12. Worker lines and tax lines are combined.
13. File header, company headers, data lines, and trailer are written by `S3Writer`.
14. `outbound_file` status is updated to success or failure.

### How Worker GSI Output Is Produced

Worker output begins in `query_workers()` and is formatted in `apply_gsi_mappings()`.

The worker mapping source is:

- dynamic GI1/GI2 metadata when PostgreSQL metadata is available
- static fallback mappings in `gsi_mappings.py`

The formatter creates one formatted column per GSI code. Examples from current mappings:

| Source Field | GSI Code | Current Level |
|--------------|----------|---------------|
| `given_name` | `CS` | `EE` |
| `family_name` | `CU` | `EE` |
| `ssn` | `DD` | `EE` |
| `birth_date` | `SY` | `EE` |
| `employee_id` | `V9` | `F` |
| `job_title` | `Z3` | `S` |
| `wfh_indicator` | `9F` | `L` |

The code then separates mappings by `gsi_level`:

- `EE` becomes employee/header-style worker lines.
- `F`, `S`, and `L` are later merged into matching tax jurisdiction lines.

### How Tax GSI Output Is Produced

Tax output begins in `query_all_worker_tax()` and is formatted in `format_tax_data_df()`.

Tax mappings come from lazy `TAX_MAPPINGS` in `gsi_mappings.py`. The mapping is keyed by output field and tax type. Examples:

| Tax Output Field | Example Tax Type | Example GSI Code |
|------------------|------------------|------------------|
| `qtd_amount` | `FIT` | `EJ` |
| `ytd_amount` | `FIT` | `EK` |
| `qtd_gross_wages` | `SIT` | `MV` |
| `ytd_gross_wages` | `SIT` | `NT` |
| `sdi_exempt_flag` | `SDIEE` | `EB` |

`format_tax_data_df()` groups tax data by:

- `worker_sk`
- formatted jurisdiction
- federal/state ordering

It builds tax lines with prefix:

`******` plus jurisdiction code.

### Reporting and Non-Reporting Output In Current Code

The current code does not define an explicit reporting versus non-reporting classification.

What exists today is:

- worker/address mappings
- tax mappings
- GSI levels: `EE`, `F`, `S`, `L`
- mandatory field marker on selected tax mappings

Therefore, any design that talks about reporting and non-reporting GSI codes needs an added classification source. That classification does not appear in current code.

### Where Validation Errors Are Currently Produced, Passed, Transformed, Or Consumed

Confirmed from current code:

| Validation / Error Area | Current Behavior |
|-------------------------|------------------|
| Config validation | `flow_validator.validate_config()` checks required config sections and types. |
| Mandatory tax field validation | `mandatory_fields_validator.validate_mandatory_fields()` produces in-memory validation results, logs them, and `ensure_mandatory_fields()` adds default rows. |
| Database/runtime processing failures | Exceptions update `outbound_file` to `FAILED`. |
| Business validation errors from `company_errors` | Not currently read or consumed in code. |
| `error_catalog` category/impact flags | Not currently read or consumed in code. |
| GSI skip decisions | Not currently present. |

The current mandatory field validator is not the same as the requested error-based skip design. It does not read `company_errors`, does not categorize errors, and does not remove GSI output.

---

## 2. Reference Document Assessment

### Useful Parts Of `docs/gsi-error-based-exclusion-analysis.md`

The existing analysis doc is useful because it captures:

- the business intent of skipping worker or tax GSI codes based on errors
- the proposed database entities `onetax.error_catalog` and `onetax.company_errors`
- the idea that `impacts_deposit` relates to MF impact and `impacts_filing` relates to Agency impact
- examples where employee profile errors may require broader skipping
- examples where jurisdiction errors may require tax-only jurisdiction skipping
- the important gap that error-to-GSI-code mapping is not defined in current reference material
- SQL shapes that could be used to inspect `error_catalog` and `company_errors`

### What Is Aligned With The Current Codebase

The doc aligns with the codebase in these areas:

- GSI output is generated from worker and tax data.
- Worker and tax formatting are separate enough to support separate skip behavior.
- Federal, state, and local levels exist through `gsi_level` and jurisdiction formatting.
- The best likely integration area is before or during worker/tax formatting, not after the final text lines are already built.
- The current code has no error-based exclusion layer.

### What Should Be Treated Cautiously

The doc should be treated as analysis/reference only for these reasons:

- The repository does not contain a file named `docs/GSI_Error_Exclusion_Analysis.md`; the current file is `docs/gsi-error-based-exclusion-analysis.md`.
- The code does not currently query `company_errors` or `error_catalog`.
- The code does not define reporting/non-reporting GSI classification.
- The code does not expose `organization_unit_sk` in `query_workers()` output, although `query_all_worker_tax()` uses `organization_unit_sk` internally in the SQL.
- The doc references current database row counts and sample records, but those are not verifiable from the repository alone.
- The doc lists open questions. This design document does not repeat them as open questions; it converts the known gaps into explicit design assumptions and extension points.

---

## 3. Problem Framing For The Current Issue

### Simple Technical Summary

The job already knows how to produce GSI output, but it does not currently have a decision layer that can say:

- this worker should be fully excluded
- this worker should keep employee data but lose some tax data
- this jurisdiction should be excluded for this worker or company
- this specific GSI code should not be emitted
- reporting or non-reporting GSI groups should be suppressed

The missing architecture is a category-driven skip decision layer between database reads and GSI line assembly.

### Confirmed Behavior From The Codebase

Confirmed from current repository:

- The job processes queued site/year/quarter records from `outbound_file`.
- Worker data is read from Redshift via `query_workers()`.
- Tax data is read from Redshift via `query_all_worker_tax()`.
- Worker GSI formatting occurs in `apply_gsi_mappings()`.
- Tax GSI formatting occurs in `format_tax_data_df()`.
- Worker `F`, `S`, and `L` level fields are merged into tax jurisdiction lines.
- Final text output is assembled in `process_site_event()`.
- Final writing is done by `S3Writer.write_gsi_dataframe()`.
- No current module evaluates `company_errors`.
- No current module maps validation error categories to skip scopes.

### Likely Intended Behavior From The Ticket

The likely intended behavior, based on the prompt and supporting docs, is:

- quarter validation errors should be grouped into categories
- categories should drive skip behavior
- skip behavior should not be hardcoded per individual error code
- employee profile errors can suppress an entire employee
- jurisdiction errors can suppress only affected jurisdiction tax output
- MF-impact and Agency-impact flags should influence skip behavior
- future categories and skip behavior should be changeable without rewriting formatter logic

### Explicit Design Assumptions

These assumptions are required to propose a workable design because the current code does not provide the missing metadata:

| Assumption | Why It Is Needed |
|------------|------------------|
| Error records can be queried from the same Redshift schema used by this job or through an added database connection. | Current code has no `company_errors` reader. The supporting doc places the tables under `onetax`. |
| Error category can be derived from `error_catalog.category`, `error_catalog.error_type`, or a new rule configuration. | The ticket wants category-driven behavior. The code does not currently define categories. |
| A new skip-rule configuration source will be added. | The repository has no current category-to-skip-scope mapping. |
| Reporting/non-reporting classification will be added as metadata. | Current mappings only know `EE`, `F`, `S`, `L`, not reporting/non-reporting. |
| Unknown or unmapped errors should default to no skip with high-visibility logging. | This preserves current behavior while making gaps visible. |

---

## 4. Master Design Proposal

### Recommended Architecture

Introduce a dedicated **Error Skip Decision Layer** between data retrieval and GSI formatting.

The layer should be responsible for:

1. reading current validation errors for the company/site/period being processed
2. enriching those errors with catalog metadata
3. translating error metadata into normalized categories
4. resolving category-based skip rules into concrete skip decisions
5. exposing those decisions to worker and tax formatting
6. producing audit/trace output for every skip decision

### Proposed Logical Components

| Component | Responsibility | Layer |
|-----------|----------------|-------|
| Error data access | Read `company_errors` joined to `error_catalog` for the current site/company/year/quarter context. | Database access |
| Error normalization | Convert raw DB rows into consistent error facts with category, impact flags, entity scope, state/local/tax identifiers, and write status. | Rule input |
| Skip rule catalog | Stores category-to-skip behavior. This should be configuration-driven, not embedded throughout formatters. | Configuration |
| Decision resolver | Combines normalized errors and rules into final skip decisions by worker, jurisdiction, tax type, and GSI code. | Rule evaluation |
| Formatter filters | Apply already-resolved decisions while building worker/tax GSI fields. | Transformation |
| Audit/observability | Logs and optional write-back records explaining what was skipped and why. | Observability |

### Category-Driven Design

The design should not say "if error code FEIN_IS_MISSING then skip X" inside processing code.

Instead, the flow should be:

| Stage | Example |
|-------|---------|
| Raw error | `FEIN_IS_MISSING` |
| Catalog metadata | `category = Registration`, `error_type = TAX_ID`, `impacts_filing = true` |
| Normalized category | `COMPANY_TAX_ID_ERROR` or configured equivalent |
| Skip behavior | company/jurisdiction/employee/code scope as configured |
| Final decision | include or exclude particular employee/tax/GSI output |

The code should depend on normalized categories and scopes, not individual error code names.

### How Skip Decisions Influence Output

The current pipeline has natural decision points:

| Output Type | Current Build Point | Skip Influence |
|-------------|--------------------|----------------|
| Worker employee lines | after `apply_gsi_mappings()` and before `build_employee_lines_udf()` | remove specific employee GSI fields or remove the entire worker from employee lines |
| Worker fields merged into tax lines | `worker_level_df` creation for `F`, `S`, `L` levels | remove level-specific worker fields or suppress worker-level fields for a jurisdiction |
| Tax lines | inside or just before `format_tax_data_df()` | remove specific tax GSI fields, jurisdiction rows, all tax rows for an employee, or all tax output for a company |
| Reporting/non-reporting GSI groups | currently not represented | add metadata to mappings, then filter by group during worker/tax formatting |
| Final file | after worker/tax lines are combined | only broad row-level decisions should remain here; code-level filtering is too late at this point |

### Avoiding Hardcoded Error Logic

The design avoids hardcoding by separating:

- error identity
- error category
- category behavior
- final skip decision
- formatting mechanics

Only the configuration should know that a category maps to a skip scope. The formatter should only know that a resolved decision says a field or row is excluded.

### Future Extensibility

The design supports future behavior by allowing new categories or skip scopes to be added in a rule catalog without changing the core pipeline structure.

Examples:

- add a new category for name validation
- map that category to `skip_entire_employee`
- add a new category for state registration
- map it to `skip_tax_jurisdiction`
- add reporting classification to a new GSI code
- map a rule to `skip_reporting_gsi_codes`

---

## 5. Skip-Scope Model

### Recommended Scopes

The skip model should support the following scopes.

| Scope | Meaning | Where It Applies |
|-------|---------|------------------|
| `NO_SKIP` | Error is known but does not suppress GSI output. | Any error/category. |
| `SKIP_GSI_CODE` | Suppress one or more specific GSI codes. | Worker and tax formatting. |
| `SKIP_REPORTING_GSI_CODES` | Suppress mappings marked as reporting. | Requires added mapping metadata. |
| `SKIP_NON_REPORTING_GSI_CODES` | Suppress mappings marked as non-reporting. | Requires added mapping metadata. |
| `SKIP_TAX_JURISDICTION` | Suppress tax line output for a specific jurisdiction. | Tax rows and `F`/`S`/`L` merged worker fields. |
| `SKIP_ALL_TAX_FOR_EMPLOYEE` | Suppress all tax output for one employee. | Tax DataFrame before line assembly. |
| `SKIP_ENTIRE_EMPLOYEE` | Suppress employee line and all tax lines for the worker. | Worker and tax output. |
| `SKIP_COMPANY_TAX_OUTPUT` | Suppress tax output for all employees in a branch/company. | Tax output at company context. |
| `SKIP_COMPANY_OUTPUT` | Suppress all worker and tax output for a company. | Highest-impact company-level rule. |

### Hierarchical And Composable

The model should be both hierarchical and composable.

It should be hierarchical because broad scopes must dominate narrow scopes:

| Higher Scope | Dominates |
|--------------|-----------|
| `SKIP_COMPANY_OUTPUT` | all worker, tax, code, reporting, and jurisdiction decisions |
| `SKIP_ENTIRE_EMPLOYEE` | all employee-specific code and tax decisions |
| `SKIP_ALL_TAX_FOR_EMPLOYEE` | all tax-code and jurisdiction decisions for that worker |
| `SKIP_TAX_JURISDICTION` | all tax-code decisions inside that jurisdiction |

It should be composable because multiple narrow decisions may apply at once:

- skip one worker-level code and one tax code
- skip reporting codes but keep non-reporting codes
- skip one jurisdiction while keeping another
- skip Agency-impact codes while keeping MF-only codes, if business rules define that split

This hybrid model fits the current project because worker and tax outputs are built separately, but final records are combined per worker/company.

---

## 6. Rule And Decision Model

### Error-To-Category Mapping

The model should use a two-step mapping:

1. Raw error row becomes a normalized error category.
2. Normalized category maps to one or more skip scopes.

Category resolution should prefer explicit rule metadata, then database catalog metadata:

| Priority | Source | Reason |
|----------|--------|--------|
| 1 | dedicated skip-rule configuration | Most precise and safest for production behavior. |
| 2 | `error_catalog.category` | Existing catalog categorization from reference doc. |
| 3 | `error_catalog.error_type` | Useful fallback if category is too broad or missing. |
| 4 | impact flags | Useful as decision modifiers, not enough by themselves to define exact skip scope. |

### Category-To-Scope Mapping

Each normalized category should map to:

- one or more skip scopes
- entity level: company, employee, jurisdiction, tax type, GSI code group
- output side: worker, tax, reporting, non-reporting, or all
- impact target: MF, Agency, or both
- default behavior for unmapped GSI codes

### Multiple Errors For The Same Entity

When multiple errors affect the same worker, jurisdiction, or company, decisions should be merged into a single final decision set.

Recommended merge behavior:

- broadest applicable skip scope wins for the same entity
- independent narrow skips are unioned
- skip decisions are never canceled by a weaker no-skip decision
- `NO_SKIP` only applies when no stronger skip exists for the same entity/output dimension

### Precedence

Recommended precedence from highest to lowest:

1. skip entire company
2. skip company tax output
3. skip entire employee
4. skip all tax for employee
5. skip tax jurisdiction
6. skip reporting or non-reporting GSI group
7. skip specific GSI code
8. no skip

### Final Inclusion / Exclusion Decision

Conceptually, every output unit should be evaluated against the resolved decision set:

| Output Unit | Decision Dimensions |
|-------------|---------------------|
| Employee line | company, worker, GSI codes, reporting group |
| Worker field merged into tax line | company, worker, jurisdiction level, GSI code, reporting group |
| Tax row | company, worker, jurisdiction, tax type |
| Tax GSI field | company, worker, jurisdiction, tax type, GSI code, reporting group |
| Company header | company-level rule only |
| File header/trailer | not affected by worker/tax skip rules except line count changes |

The formatter should not decide why something is excluded. It should only apply an already-resolved inclusion/exclusion decision.

---

## 7. Best Integration Point In The Current Repository

### Best Extension Point

The best extension point is inside `process_site_event()` after branch/company context is known and before worker/tax formatting creates final line strings.

The reason: this is the first point where the job has enough context to evaluate company-level errors and still has structured DataFrames that can be filtered without parsing text lines.

### Likely Impacted Modules

| Module | Conceptual Change |
|--------|-------------------|
| `db_connection.py` | Add read access for error records and possibly write-back for `company_errors.write_status`. |
| new `error_handler.py` or `skip_decision.py` | Own normalization, category resolution, rule evaluation, and decision merging. |
| `main.py` | Load decisions for each company/site context and pass them into worker/tax stages. |
| `gsi_formatter.py` | Apply resolved decisions while selecting/forming worker and tax GSI fields. |
| `gsi_mappings.py` | Enrich mapping metadata with reporting/non-reporting classification if needed. |
| `mandatory_fields_validator.py` | Clarify ordering with skip handling so mandatory defaults are not added for output that will be fully skipped. |
| `logger.py` / logging call sites | Add decision trace logging. |

### Layer Placement

The design should live across three layers, with clear ownership:

| Layer | Responsibility |
|-------|----------------|
| Database access | Fetch raw errors and write status updates. |
| Rule evaluation | Categorize errors and resolve skip decisions. |
| Transformation/filtering | Apply decisions while building structured worker/tax output. |

It should not live entirely inside `gsi_formatter.py`, because that would mix business rule evaluation with formatting. It should not live entirely in `main.py`, because `main.py` is already orchestration-heavy.

### Extend, Wrap, Or Refactor

Recommended approach:

- extend the flow with a new decision layer
- wrap existing formatter calls with decision-aware inputs
- minimally refactor formatter selection logic so it can apply resolved exclusions
- do not rewrite query, mapping, line-splitting, writer, or orchestration logic initially

This keeps the current system stable while introducing the new behavior.

### Minimal Disruption Path

The least disruptive path is:

1. add error retrieval and decision resolution
2. keep current worker/tax queries intact
3. apply decisions before employee/tax arrays are built
4. preserve existing output assembly and writer behavior
5. add detailed logging for decisions and final counts

---

## 8. Design Principles And Future Extensibility

### Separation Of Concerns

Each layer should have one job:

- database layer reads and writes data
- rule layer decides skip behavior
- formatter layer formats included fields
- writer layer writes final text

This keeps the design testable and prevents future categories from spreading conditional logic across the pipeline.

### Configuration-Driven Behavior

Skip behavior should be driven by a configuration source or database rule table.

The rule catalog should support:

- category name
- error type
- impact flags
- output side
- skip scope
- optional GSI code list
- optional reporting group
- optional jurisdiction/tax-type sensitivity
- active/inactive flag or effective dates

### Backward Compatibility

Default behavior should preserve current output when no matching skip rules exist.

That means:

- no errors means current behavior
- unknown category means current behavior plus warning/audit log
- rule catalog unavailable means current behavior plus warning/audit log, unless business later requires fail-closed behavior

### Maintainability

The design should avoid scattering conditionals across:

- `process_site_event()`
- `apply_gsi_mappings()`
- `format_tax_data_df()`
- `mandatory_fields_validator.py`

Instead, those functions should consume a unified decision model.

### Observability And Traceability

Every skip decision should be traceable.

At minimum, logs should show:

- site, branch, company, year, quarter
- error code and normalized category
- impact flags
- resolved skip scope
- affected worker/jurisdiction/tax type/GSI code where available
- counts of worker lines and tax lines before and after filtering

If `company_errors.write_status` is updated, that update should be tied to completed decision application, not merely to reading the error.

### Future Unknown Error Categories

Unknown categories should be first-class in observability:

- they should not break generation by default
- they should be logged as unmapped
- they should be visible enough for rule catalog updates
- they should not require code changes if a new config entry can handle them

---

## 9. Edge-Case Handling At Design Level

### Multiple Errors With Different Scopes

The resolver should merge them into one final decision set and apply precedence.

Example design behavior:

- one error says skip GSI code `DD`
- another says skip entire employee
- final result is skip entire employee

### Employee-Level And Jurisdiction-Level Errors Together

Employee-level broad skips should dominate jurisdiction-level skips for that employee.

If an employee is fully skipped, there is no need to separately apply jurisdiction decisions for that employee.

### Reporting Versus Non-Reporting Conflicts

If one rule skips reporting codes and another skips one specific non-reporting code, both should apply.

If a broader rule skips the entire employee or jurisdiction, reporting/non-reporting classification no longer matters for that entity.

### MF-Impact And Agency-Impact Overlap

Impact flags should be treated as modifiers, not complete skip definitions.

If both MF and Agency impact are true, the resolver should union the behavior for both impacts and then apply precedence.

### Partial Or Missing Tax/Jurisdiction Data

If a rule targets a jurisdiction that does not appear in tax data, the design should not fail the job. It should log that the rule had no matching output.

If tax data is missing and mandatory-field logic would add defaults, skip decisions should be evaluated before adding defaults for fully skipped tax scopes. This prevents creating default output for data that business rules say should be suppressed.

### Future Unknown Error Types

Unknown errors should resolve to `NO_SKIP` with trace logging by default.

This preserves current behavior and makes unmapped conditions visible. If the business later wants fail-closed behavior for unknown MF/Agency-impact errors, that should be a rule-catalog policy, not hardcoded formatter behavior.

### Missing Error Catalog Join

If `company_errors` exists but the `error_catalog` join is missing for an error, the resolver should treat the error as uncategorized and observable.

Default output behavior should remain no-skip unless a configured fallback rule says otherwise.

### Company-Level Error Without Worker Identifier

Some errors may exist only at company or organization-unit level. The design should allow company-level decisions instead of forcing every error to map to a worker.

Company-level decisions can affect:

- all workers
- all tax rows
- all rows for a jurisdiction
- only specific code groups

### Jurisdiction Error Without Local Code

A state-only jurisdiction error should map to state-level jurisdiction output.

A local-code error should map to local jurisdiction output.

Federal errors should map to federal jurisdiction output.

This aligns with current `format_tax_data_df()` behavior where jurisdiction is formatted as:

- `F` for federal
- state code for state
- state plus local suffix for local

---

## 10. Final Recommended Design Direction

### Preferred Design Pattern

Use a **policy/rule evaluation layer with a resolved skip-decision model**.

The pattern is:

- raw errors are facts
- categories are normalized business concepts
- rules map categories to skip scopes
- a resolver merges rules into final decisions
- formatters apply decisions without knowing business reasons

This is the right fit because the requirement is explicitly generic and category-driven.

### Preferred Place To Integrate

Integrate at the company-processing level inside `process_site_event()`, after branch/company context is known and before worker/tax GSI line construction.

This is the practical point where the job has enough context but still has structured data.

### Preferred Extensibility Mechanism

Use a rule catalog rather than hardcoded error branches.

The catalog can start as a repository configuration file if database changes are not ready, but the cleaner long-term design is a database-managed rule table or an extension of existing error metadata.

The rule catalog should classify:

- category
- impact target
- skip scope
- output side
- optional GSI code group
- optional exact GSI codes
- effective dates or active flag

### Preferred Stability Strategy

Introduce the design in safe phases:

1. read and log error facts without changing output
2. resolve decisions and log proposed skips without changing output
3. enable skip behavior for narrow, well-understood scopes
4. expand to employee, jurisdiction, reporting, and non-reporting scopes
5. update `company_errors.write_status` only after skip behavior is reliably applied

### Final Recommendation

Build a new decision layer, not a formatter rewrite.

Keep `query_workers()`, `query_all_worker_tax()`, `load_mappings()`, line splitting, header/trailer generation, and output writing mostly intact. Add a focused error-skip subsystem that produces a clear decision object for each company/site processing unit. Then make worker and tax formatting decision-aware in small, controlled changes.

This gives the team a clean architecture for current unknowns: categories can be added, scopes can be refined, and reporting/non-reporting classification can be introduced without repeatedly touching the core GSI formatting pipeline.

