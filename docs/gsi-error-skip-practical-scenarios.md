# GSI Error Skip Practical Scenarios

**Status:** Design support document  
**Purpose:** Explain practical success and failure behavior for error-based GSI skip handling  
**Related design:** `docs/gsi-error-skip-design-proposal.md`  
**Scope:** Quarter GSI generation only  

This document uses simple sample data to show how the proposed skip design should behave in real cases.

The output lines below are **illustrative GSI fragments**, not byte-perfect 160-character production records. They are written this way so the skip behavior is easy to see.

---

## 1. Baseline Data Used In All Examples

### 1.1 Queued Outbound File

| batch_id | site_id | year | quarter | status | file_type |
|----------|---------|------|---------|--------|-----------|
| BATCH-001 | GE59 | 2026 | 1 | QUEUED | QUARTER |

The current job starts from `outbound_file` records where:

```sql
status = 'QUEUED'
AND file_type = 'QUARTER'
```

### 1.2 Organization

| organization_unit_sk | branch_code | company_code | site_id |
|----------------------|-------------|--------------|---------|
| 227 | ST | GE59 | GE59 |

Current code uses `query_site_organizations()` to get branch/company for the site.

Important design note: for error handling, the job also needs `organization_unit_sk`. If it is not returned by `query_site_organizations()`, the error reader must join it internally through `organization_unit`.

### 1.3 Workers

| worker_sk | branch_code | company_code | given_name | family_name | ssn | birth_date | hire_date |
|-----------|-------------|--------------|------------|-------------|-----|------------|-----------|
| 361 | ST | GE59 | CUNEAL | JACKSON | 123456789 | 1986-01-31 | 2023-12-31 |
| 362 | ST | GE59 | MAYA | LEE | 987654321 | 1990-05-12 | 2024-01-01 |

### 1.4 Tax Rows Before Formatting

| worker_sk | jurisdiction | state_code | local_code | tax_type | qtd_amount | ytd_amount | qtd_gross_wages | ytd_gross_wages |
|-----------|--------------|------------|------------|----------|------------|------------|-----------------|-----------------|
| 361 | F | NULL | NULL | FIT | 123.45 | 456.78 | 3456.67 | 4567.89 |
| 361 | CA | CA | NULL | SIT | 0.00 | 0.00 | 2345.67 | 7000.00 |
| 361 | IL | IL | NULL | SIT | 0.00 | 0.00 | 1457.86 | 9304.56 |
| 362 | F | NULL | NULL | FIT | 210.00 | 900.00 | 5000.00 | 9000.00 |
| 362 | CA | CA | NULL | SIT | 0.00 | 0.00 | 3000.00 | 8000.00 |

### 1.5 Common GSI Mappings Used In Examples

| Data | Example GSI Code |
|------|------------------|
| `given_name` | `CS` |
| `family_name` | `CU` |
| `ssn` | `DD` |
| `birth_date` | `SY` |
| `hire_date` | `NZ` |
| FIT QTD tax amount | `EJ` |
| FIT YTD tax amount | `EK` |
| SIT QTD gross wages | `MV` |
| SIT YTD gross wages | `NT` |
| filing status | `DF`, `DH`, `DK` |
| number of allowances | `DG`, `DI`, `DL` |

### 1.6 Example Rule Catalog

This is a design-level example, not final code.

| normalized_category | Trigger Example | Scope | Target |
|---------------------|-----------------|-------|--------|
| `NO_IMPACT_ERROR` | impact flags false | `NO_SKIP` | none |
| `SPECIFIC_TAX_CODE_ERROR` | tax value invalid | `SKIP_GSI_CODE` | listed GSI code(s) |
| `WAGE_PLAN_ERROR` | CA wage plan missing | `SKIP_TAX_JURISDICTION` | state/local/tax type |
| `EMPLOYEE_PROFILE_ERROR` | SSN/profile invalid | `SKIP_ENTIRE_EMPLOYEE` | worker |
| `COMPANY_TAX_ID_ERROR` | FEIN missing | `SKIP_COMPANY_TAX_OUTPUT` or `SKIP_COMPANY_OUTPUT` | company |

Final category-to-scope mapping must come from business/product rules. The architecture should allow changing this table without editing formatter logic.

---

## 2. Baseline Success: No Active Errors

### Input Error Data

`company_errors` has no active rows for `organization_unit_sk = 227`.

| company_error_sk | error_code | resolution_status | write_status |
|------------------|------------|-------------------|--------------|
| none | none | none | none |

### Resolved Decision

| Entity | Decision |
|--------|----------|
| company GE59 | `NO_SKIP` |
| worker 361 | include |
| worker 362 | include |
| all tax jurisdictions | include |
| all GSI codes | include |

### Final Output Fragment

```text
<FILE HEADER>
      STGE5910000NN             Y
******      CSCUNEAL      CUJACKSON      DD123-45-6789SY19860131NZ12312023
******F     EJ+00000012345EK+00000045678DFSDG00
******CA    MV+000000234567NT+000000070000DHSDI01
******IL    MV+000000145786NT+000000093045DHSDI01
******      CSMAYA        CULEE          DD987-65-4321SY19900512NZ01012024
******F     EJ+00000021000EK+00000090000DFSDG00
******CA    MV+000000300000NT+000000080000DHSDI01
9999999999990000010
```

### Final Status

| Object | Result |
|--------|--------|
| Output file | written |
| `outbound_file.status` | `GENERATED` |
| `outbound_file.record_count` | 10 |
| Email | success |
| Error write-back | none |

---

## 3. Success: Error Exists But Does Not Impact MF Or Agency

### Input Error Data

| company_error_sk | error_code | category | impacts_deposit | impacts_filing | resolution_status | write_status |
|------------------|------------|----------|-----------------|----------------|-------------------|--------------|
| 501 | FEIN_NOT_CORRECT | Registration | false | false | Open | PENDING |

### Rule Interpretation

| Input | Result |
|-------|--------|
| both impact flags are false | `NO_IMPACT_ERROR` |
| mapped scope | `NO_SKIP` |

### Final Output Fragment

Same as baseline. Nothing is removed.

```text
<FILE HEADER>
      STGE5910000NN             Y
******      CSCUNEAL      CUJACKSON      DD123-45-6789SY19860131NZ12312023
******F     EJ+00000012345EK+00000045678DFSDG00
******CA    MV+000000234567NT+000000070000DHSDI01
******IL    MV+000000145786NT+000000093045DHSDI01
******      CSMAYA        CULEE          DD987-65-4321SY19900512NZ01012024
******F     EJ+00000021000EK+00000090000DFSDG00
******CA    MV+000000300000NT+000000080000DHSDI01
9999999999990000010
```

### Final Status

| Object | Result |
|--------|--------|
| Output file | written |
| `outbound_file.status` | `GENERATED` |
| `company_errors.write_status` | recommended `WRITTEN` or left unchanged until write-back policy is confirmed |
| Audit log | "error observed, no skip applied" |

Practical meaning: the job does not fail just because an error exists. The error must map to an active skip rule.

---

## 4. Success: Skip One Specific GSI Code

### Business Example

A validation rule says FIT QTD withholding should not be sent for worker 361, but other federal data is still valid.

### Input Error Fact

This may come from `company_errors` plus a richer validation detail source. The current `company_errors` table alone does not carry `worker_sk`, so worker-specific targeting needs either another source or an added field.

| worker_sk | error_code | normalized_category | target_gsi_code | resolution_status | write_status |
|-----------|------------|---------------------|-----------------|-------------------|--------------|
| 361 | FIT_QTD_INVALID | SPECIFIC_TAX_CODE_ERROR | EJ | Open | PENDING |

### Resolved Decision

| Entity | Decision |
|--------|----------|
| worker 361 federal tax | skip GSI code `EJ` |
| worker 361 federal tax | keep `EK`, `DF`, `DG` |
| worker 361 employee line | include |
| worker 361 CA/IL tax | include |
| worker 362 | include everything |

### Final Output Fragment

Only `EJ+00000012345` is removed from worker 361 federal line.

```text
<FILE HEADER>
      STGE5910000NN             Y
******      CSCUNEAL      CUJACKSON      DD123-45-6789SY19860131NZ12312023
******F     EK+00000045678DFSDG00
******CA    MV+000000234567NT+000000070000DHSDI01
******IL    MV+000000145786NT+000000093045DHSDI01
******      CSMAYA        CULEE          DD987-65-4321SY19900512NZ01012024
******F     EJ+00000021000EK+00000090000DFSDG00
******CA    MV+000000300000NT+000000080000DHSDI01
9999999999990000010
```

### Final Status

| Object | Result |
|--------|--------|
| Output file | written |
| `outbound_file.status` | `GENERATED` |
| `company_errors.write_status` | recommended `SKIPPED` for the error that caused suppression |
| Audit log | includes `worker_sk=361`, `scope=SKIP_GSI_CODE`, `gsi_code=EJ` |

Practical meaning: line count usually stays the same because only a code/value pair is removed from a line.

---

## 5. Success: Skip A Tax Jurisdiction

### Business Example

California wage plan is missing. The rule says do not send California SIT tax output for that company/period.

### Input Error Data

| company_error_sk | organization_unit_sk | error_code | category | state_code | local_code | tax_type | impacts_filing | resolution_status | write_status |
|------------------|----------------------|------------|----------|------------|------------|----------|----------------|-------------------|--------------|
| 601 | 227 | CA_WAGE_PLAN_MISSING | WagePlan | CA | NULL | SIT | true | Open | PENDING |

### Resolved Decision

| Entity | Decision |
|--------|----------|
| company GE59, CA, SIT | `SKIP_TAX_JURISDICTION` |
| worker 361 CA tax line | remove |
| worker 362 CA tax line | remove |
| federal tax lines | keep |
| IL tax lines | keep |
| employee lines | keep |

Because `company_errors` is company/org scoped, this example removes CA SIT tax output for all workers in the affected company. If the business wants only selected workers skipped, the error data must include a reliable worker key.

### Final Output Fragment

Both CA tax lines are removed.

```text
<FILE HEADER>
      STGE5910000NN             Y
******      CSCUNEAL      CUJACKSON      DD123-45-6789SY19860131NZ12312023
******F     EJ+00000012345EK+00000045678DFSDG00
******IL    MV+000000145786NT+000000093045DHSDI01
******      CSMAYA        CULEE          DD987-65-4321SY19900512NZ01012024
******F     EJ+00000021000EK+00000090000DFSDG00
9999999999990000008
```

### Final Status

| Object | Result |
|--------|--------|
| Output file | written |
| `outbound_file.status` | `GENERATED` |
| `outbound_file.record_count` | 8 |
| `company_errors.write_status` | recommended `SKIPPED` |
| Audit log | includes `scope=SKIP_TAX_JURISDICTION`, `state_code=CA`, `tax_type=SIT`, removed line count = 2 |

Practical meaning: line count changes because whole tax lines are removed.

---

## 6. Success: Skip Entire Employee

### Business Example

An employee profile error means the employee should not be sent at all.

### Input Error Fact

The existing `company_errors` schema does not show `worker_sk`. This scenario assumes the validation layer provides a worker-level error fact.

| worker_sk | error_code | normalized_category | impacts_filing | resolution_status | write_status |
|-----------|------------|---------------------|----------------|-------------------|--------------|
| 362 | SSN_INVALID | EMPLOYEE_PROFILE_ERROR | true | Open | PENDING |

### Resolved Decision

| Entity | Decision |
|--------|----------|
| worker 362 employee line | remove |
| worker 362 all tax lines | remove |
| worker 361 | keep |

### Final Output Fragment

Worker 362 and all worker 362 tax output are removed.

```text
<FILE HEADER>
      STGE5910000NN             Y
******      CSCUNEAL      CUJACKSON      DD123-45-6789SY19860131NZ12312023
******F     EJ+00000012345EK+00000045678DFSDG00
******CA    MV+000000234567NT+000000070000DHSDI01
******IL    MV+000000145786NT+000000093045DHSDI01
9999999999990000007
```

### Final Status

| Object | Result |
|--------|--------|
| Output file | written |
| `outbound_file.status` | `GENERATED` |
| `company_errors.write_status` | recommended `SKIPPED` |
| Audit log | includes `worker_sk=362`, `scope=SKIP_ENTIRE_EMPLOYEE` |

Practical meaning: this is not a job failure. It is a successful file with intentionally skipped employee output.

---

## 7. Success: Multiple Errors For Same Worker Or Jurisdiction

### Input Error Facts

| entity | error_code | normalized_category | mapped_scope |
|--------|------------|---------------------|--------------|
| worker 362 | SSN_INVALID | EMPLOYEE_PROFILE_ERROR | `SKIP_ENTIRE_EMPLOYEE` |
| worker 362, CA | CA_WAGE_PLAN_MISSING | WAGE_PLAN_ERROR | `SKIP_TAX_JURISDICTION` |
| worker 362, FIT | FIT_QTD_INVALID | SPECIFIC_TAX_CODE_ERROR | `SKIP_GSI_CODE(EJ)` |

### Precedence Result

`SKIP_ENTIRE_EMPLOYEE` wins because it is broader than jurisdiction or specific-code skipping.

### Final Output Fragment

Same as Scenario 6. Worker 362 is removed completely.

```text
<FILE HEADER>
      STGE5910000NN             Y
******      CSCUNEAL      CUJACKSON      DD123-45-6789SY19860131NZ12312023
******F     EJ+00000012345EK+00000045678DFSDG00
******CA    MV+000000234567NT+000000070000DHSDI01
******IL    MV+000000145786NT+000000093045DHSDI01
9999999999990000007
```

### Final Status

| Object | Result |
|--------|--------|
| Output file | written |
| `outbound_file.status` | `GENERATED` |
| error write-back | all three error facts can be marked `SKIPPED` because all were covered by the broader skip |
| Audit log | records the winning scope and suppressed narrower scopes |

Practical meaning: do not apply conflicting rules independently after a broader skip has already removed the entity.

---

## 8. Success: Company-Level Tax Output Skip

### Business Example

FEIN is missing. Business chooses a rule that says employee identity lines may be included, but tax lines should not be sent.

### Input Error Data

| company_error_sk | organization_unit_sk | error_code | category | error_type | impacts_filing | resolution_status | write_status |
|------------------|----------------------|------------|----------|------------|----------------|-------------------|--------------|
| 701 | 227 | FEIN_IS_MISSING | Registration | TAX_ID | true | Open | PENDING |

### Resolved Decision

| Entity | Decision |
|--------|----------|
| company GE59 tax output | `SKIP_COMPANY_TAX_OUTPUT` |
| all employee lines | keep |
| all tax lines | remove |

### Final Output Fragment

```text
<FILE HEADER>
      STGE5910000NN             Y
******      CSCUNEAL      CUJACKSON      DD123-45-6789SY19860131NZ12312023
******      CSMAYA        CULEE          DD987-65-4321SY19900512NZ01012024
9999999999990000005
```

### Final Status

| Object | Result |
|--------|--------|
| Output file | written |
| `outbound_file.status` | `GENERATED` |
| `company_errors.write_status` | recommended `SKIPPED` |
| Audit log | includes `scope=SKIP_COMPANY_TAX_OUTPUT`, removed tax line count = 5 |

Important: if business instead says FEIN missing should suppress the whole company, then the scope changes to `SKIP_COMPANY_OUTPUT`.

---

## 9. Success Or Skipped: Entire Company Output Suppressed

### Business Example

Business chooses a strict rule: FEIN missing means do not send any employee or tax output for that company.

### Resolved Decision

| Entity | Decision |
|--------|----------|
| company GE59 | `SKIP_COMPANY_OUTPUT` |

### Recommended Outcome

This should not be treated as a technical failure. There are two acceptable business outcomes:

| Option | Meaning |
|--------|---------|
| Write header/trailer-only file | `outbound_file.status = GENERATED`, record count reflects minimal file |
| Write no file | `outbound_file.status = SKIPPED` |

The current code will fail if all worker lines are removed, because it raises when `all_worker_lines` is empty. Final implementation should distinguish "no data because of a valid skip decision" from "no data because something broke."

### Example Header/Trailer-Only Output

```text
<FILE HEADER>
9999999999990000002
```

### Preferred Status

If product accepts the existing enum value, use:

| Object | Result |
|--------|--------|
| Output file | not written, or header/trailer only |
| `outbound_file.status` | `SKIPPED` if no file, `GENERATED` if minimal file is written |
| `company_errors.write_status` | `SKIPPED` |

---

## 10. Success With Warning: Unknown Error Category

### Input Error Data

| company_error_sk | error_code | category | impacts_filing | resolution_status | write_status |
|------------------|------------|----------|----------------|-------------------|--------------|
| 801 | NEW_UNKNOWN_ERROR | UnknownCategory | true | Open | PENDING |

### Resolved Decision

| Entity | Decision |
|--------|----------|
| company GE59 | `NO_SKIP` by default |

### Final Output

Same as baseline.

### Final Status

| Object | Result |
|--------|--------|
| Output file | written |
| `outbound_file.status` | `GENERATED` |
| `company_errors.write_status` | leave `PENDING` or mark `WRITTEN_WITH_NO_RULE`, depending final policy |
| Audit log | high-visibility warning: "unknown category, no skip applied" |

Practical meaning: initial rollout should fail open for unknown rules so a missing rule does not silently block quarter output.

---

## 11. Failure And Warning Scenarios

The table below separates true technical failures from successful files with warnings.

| Scenario | Example Input | Current Behavior | Recommended Final Behavior |
|----------|---------------|------------------|----------------------------|
| No queued records | no `outbound_file` rows with `QUEUED` | logs "No queued files to process", returns | same |
| Config/secrets fail at startup | Redshift secret missing | job fails before processing | fail job, no file |
| No organizations for site | `query_site_organizations()` returns empty | outer exception, `outbound_file.status = FAILED` | same |
| Worker query fails for one company | DB timeout for company A, company B works | logs company error and continues | generated with warning if at least one company succeeds |
| All worker queries fail or no workers | every company skipped by technical error, not business rule | raises "No worker data found", `FAILED` | same |
| All workers intentionally skipped by rule | `SKIP_COMPANY_OUTPUT` | current code would look like no worker data and fail | should be `SKIPPED` or valid minimal `GENERATED`, not `FAILED` |
| Tax query fails | Redshift tax query timeout | logs error and can still generate worker-only file | decide with feature flag: strict mode fails, soft mode generates with warning |
| Mandatory field validator fails | TAX_MAPPINGS lazy load issue | current code logs warning and formats original tax data | same, unless strict validation mode is enabled |
| Error table unavailable | `company_errors` query fails | not implemented today | initial rollout: fail open, generate file, warning log |
| Rule catalog unavailable | config missing or invalid | not implemented today | initial rollout: fail open, generate file, warning log |
| S3/Volume write fails | `write_gsi_dataframe()` cannot write | current writer returns `None`; current caller may still update success | final design should treat `None` as failure and set `outbound_file.status = FAILED` |
| Success DB update fails after file write | file exists but `update_outbound_file_complete()` fails | outer exception tries to set `FAILED` | keep audit/reconciliation log because file may already exist |
| Error write-back fails | `company_errors.write_status` update fails | not implemented today | do not corrupt output; log and retry or leave PENDING for reprocessing |

---

## 12. Practical Status Rules

### 12.1 `outbound_file.status`

| Final Status | Use When |
|--------------|----------|
| `GENERATED` | file was successfully written with included and/or intentionally skipped data |
| `FAILED` | technical failure prevented valid output |
| `SKIPPED` | business rules intentionally suppress the whole output and product agrees no file should be written |
| `GENERATING` | in progress only |
| `QUEUED` | waiting to be processed |

### 12.2 `company_errors.write_status`

Recommended interpretation:

| Final Status | Use When |
|--------------|----------|
| `SKIPPED` | the error caused at least one worker/tax/GSI output item to be excluded |
| `WRITTEN` | the error was observed, but no skip was applied and the output was written |
| `PENDING` | not processed yet, or processing failed before a final decision could be safely recorded |

This policy should be confirmed with the owning team before implementation.

---

## 13. Where Each Decision Applies In The Current Pipeline

| Decision Type | Best Application Point | Why |
|---------------|------------------------|-----|
| Skip whole company | before worker query or immediately after error decisions | avoids unnecessary worker/tax work |
| Skip whole employee | after worker DataFrame is available, before employee lines and tax joins | needs `worker_sk` |
| Skip tax jurisdiction | before `format_tax_data_df()` groups tax rows | tax rows still have `jurisdiction` |
| Skip one tax GSI code | inside `format_tax_data_df()` before the final `gsi_fields` array is built | GSI code is known at field formatting time |
| Skip one employee GSI code | inside `apply_gsi_mappings()` or before `gsi_fields_array` is built | GSI columns still exist separately |
| Skip reporting/non-reporting group | after mapping metadata has `reporting_group` | current code does not have this classification yet |
| Audit/log decision | in `error_handler.py`, plus before/after counts in `main.py` | gives traceability |

---

## 14. End-To-End Example With Skip Layer

### Step 1: Read queued file

Input:

| batch_id | site_id | year | quarter |
|----------|---------|------|---------|
| BATCH-001 | GE59 | 2026 | 1 |

### Step 2: Read organizations

Input:

| organization_unit_sk | branch_code | company_code |
|----------------------|-------------|--------------|
| 227 | ST | GE59 |

### Step 3: Read active errors

Input:

| company_error_sk | error_code | category | state_code | tax_type | impacts_filing |
|------------------|------------|----------|------------|----------|----------------|
| 601 | CA_WAGE_PLAN_MISSING | WagePlan | CA | SIT | true |

### Step 4: Resolve decision

Output from `error_handler.py`:

| scope | company_code | state_code | tax_type |
|-------|--------------|------------|----------|
| `SKIP_TAX_JURISDICTION` | GE59 | CA | SIT |

### Step 5: Read worker and tax data

Workers are included. Tax rows are filtered before formatting.

Removed tax rows:

| worker_sk | jurisdiction | tax_type |
|-----------|--------------|----------|
| 361 | CA | SIT |
| 362 | CA | SIT |

### Step 6: Build final output

```text
<FILE HEADER>
      STGE5910000NN             Y
******      CSCUNEAL      CUJACKSON      DD123-45-6789SY19860131NZ12312023
******F     EJ+00000012345EK+00000045678DFSDG00
******IL    MV+000000145786NT+000000093045DHSDI01
******      CSMAYA        CULEE          DD987-65-4321SY19900512NZ01012024
******F     EJ+00000021000EK+00000090000DFSDG00
9999999999990000008
```

### Step 7: Write statuses

| Table | Update |
|-------|--------|
| `outbound_file` | `status = GENERATED`, `record_count = 8` |
| `company_errors` | `write_status = SKIPPED` for `company_error_sk = 601` |

---

## 15. Key Practical Takeaways

1. A technical failure and a business skip are different things.
2. If data is skipped because a rule said to skip it, the job should usually succeed.
3. If data is missing because a query, formatter, or writer failed, the job should fail or warn based on strictness.
4. `company_errors` is company/org scoped in the available schema. Employee-level skip requires a worker-level error key from another source or schema extension.
5. Specific GSI-code skip changes line contents but usually not line count.
6. Jurisdiction, employee, company-tax, and company-output skips usually change line count.
7. Unknown categories should initially fail open with loud logs.
8. S3 writer returning `None` must be treated as a failure in the final implementation.
9. Mandatory-field backfill must not recreate rows that a skip decision intentionally removed.
10. Every skip must be auditable by site, company, worker/jurisdiction/code, error, rule, and before/after counts.

