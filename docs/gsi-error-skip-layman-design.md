# GSI Error Skip Design - Simple Explanation

**Purpose:** Explain the dynamic error-skip design in simple terms  
**Audience:** Anyone trying to understand the Jira/design before coding  
**Related files:**  
- `docs/gsi-error-skip-design-proposal.md`
- `docs/gsi-error-skip-master-design.md`
- `docs/gsi-error-skip-practical-scenarios.md`

---

## 1. What This Project Does Today

This project creates a **Quarter GSI text file**.

Think of the GSI file as a final report that gets sent downstream.

The file contains:

1. employee/worker information
2. tax information
3. federal tax lines
4. state tax lines
5. local tax lines
6. header and trailer records

Example simplified output:

```text
<FILE HEADER>
      STGE5910000NN             Y
******      CSCUNEAL      CUJACKSON      DD123-45-6789
******F     EJ+00000012345EK+00000045678
******CA    MV+000000234567NT+000000070000
9999999999990000005
```

In simple words:

| Line | Meaning |
|------|---------|
| file header | says this is a quarter GSI file |
| company header | branch/company information |
| employee line | employee name, SSN, dates, flags |
| federal tax line | federal tax data |
| state tax line | state tax data |
| trailer | final record count |

---

## 2. Where The Data Comes From

The GSI file is **not mainly generated from the JSON file**.

The JSON/event is only a trigger or reference input in some flows.

The actual GSI data comes mostly from database tables.

### Current Data Sources

| Data Needed | Comes From |
|------------|------------|
| queued files to process | `outbound_file` table |
| branch/company/site | `organization_unit` table |
| worker details | `worker` table |
| worker addresses | `worker_address` table |
| tax amounts | `worker_tax_qtr_snapshot` table |
| tax profile data | `worker_tax_profile` table |
| GSI field definitions | GI1/GI2 metadata and mapping API |

So practically:

```text
database rows -> PySpark transformations -> formatted GSI text file
```

---

## 3. What Problem The New Design Solves

Today, the job creates the GSI file even if there are validation errors.

Example:

| Error | Current Behavior |
|-------|------------------|
| SSN invalid | employee may still be written |
| CA wage plan missing | CA tax line may still be written |
| FEIN missing | company tax output may still be written |

The Jira story says:

> If certain errors impact Mainframe or Agency, do not send the affected GSI data.

In simple words:

```text
Before writing data to the GSI file, check whether any known errors say that data should be skipped.
```

---

## 4. The Main Design Idea

Do **not** hardcode rules directly inside the GSI formatting code.

Bad design:

```text
if error_code == FEIN_IS_MISSING:
    skip something

if error_code == CA_WAGE_PLAN_MISSING:
    skip something else
```

That becomes hard to maintain.

Better design:

```text
error -> category -> rule -> skip decision -> output filtering
```

That means the code follows a general process:

1. read errors from the database
2. categorize the errors
3. look up what each category means
4. decide what should be skipped
5. apply the skip while building the GSI output

---

## 5. Simple Picture Of The New Flow

```text
1. Find queued file
        |
        v
2. Find company/site data
        |
        v
3. Read validation errors
        |
        v
4. Convert errors into skip decisions
        |
        v
5. Read worker and tax data
        |
        v
6. Apply skip decisions
        |
        v
7. Build final GSI file
        |
        v
8. Update status and logs
```

The new part is steps 3, 4, and 6.

---

## 6. What Is A Skip Decision?

A skip decision is the final answer to this question:

> Should this worker, tax line, or GSI code be included in the file?

Examples:

| Error Situation | Possible Skip Decision |
|-----------------|------------------------|
| error has no MF/Agency impact | skip nothing |
| one tax value is invalid | skip one GSI code |
| CA wage plan is missing | skip CA tax jurisdiction |
| employee profile is invalid | skip the whole employee |
| FEIN is missing | skip company tax output or whole company output |

The design supports many skip levels.

---

## 7. Skip Levels In Plain English

| Skip Scope | Meaning |
|-----------|---------|
| `NO_SKIP` | keep everything |
| `SKIP_GSI_CODE` | remove one code/value pair from a line |
| `SKIP_TAX_JURISDICTION` | remove one state/local tax line |
| `SKIP_ALL_TAX_FOR_EMPLOYEE` | keep employee line, remove all tax lines for that employee |
| `SKIP_ENTIRE_EMPLOYEE` | remove employee and all tax lines |
| `SKIP_COMPANY_TAX_OUTPUT` | keep employees, remove all tax lines for company |
| `SKIP_COMPANY_OUTPUT` | remove the whole company from output |

---

## 8. Practical Example 1: No Error

### Input

Worker:

| worker_sk | name | state tax |
|-----------|------|-----------|
| 361 | Cuneal Jackson | CA and IL |

Errors:

| error_code | result |
|------------|--------|
| none | no skip |

### Output

Everything is included.

```text
******      CSCUNEAL      CUJACKSON      DD123-45-6789
******F     EJ+00000012345EK+00000045678
******CA    MV+000000234567NT+000000070000
******IL    MV+000000145786NT+000000093045
```

### Status

| Item | Status |
|------|--------|
| file | written |
| `outbound_file.status` | `GENERATED` |

---

## 9. Practical Example 2: Error Exists But No Skip

### Input

Error:

| error_code | impacts_deposit | impacts_filing |
|------------|-----------------|----------------|
| FEIN_NOT_CORRECT | false | false |

If business says this error does not impact output, then the decision is:

```text
NO_SKIP
```

### Output

Same as normal output.

### Status

| Item | Status |
|------|--------|
| file | written |
| job | success |
| log | "error observed, no skip applied" |

Key point:

```text
Having an error does not automatically mean the job fails.
```

---

## 10. Practical Example 3: Skip One GSI Code

### Input

Business rule:

| Error Category | Decision |
|----------------|----------|
| FIT amount invalid | skip GSI code `EJ` |

Before skip:

```text
******F     EJ+00000012345EK+00000045678
```

After skip:

```text
******F     EK+00000045678
```

Only `EJ` is removed.

The rest of the worker and tax data stays.

### Status

| Item | Status |
|------|--------|
| file | written |
| job | success |
| error write status | `SKIPPED` |

---

## 11. Practical Example 4: Skip CA Tax Jurisdiction

### Input

Error:

| error_code | state_code | tax_type |
|------------|------------|----------|
| CA_WAGE_PLAN_MISSING | CA | SIT |

Rule:

```text
WAGE_PLAN_ERROR -> SKIP_TAX_JURISDICTION
```

Before skip:

```text
******F     EJ+00000012345EK+00000045678
******CA    MV+000000234567NT+000000070000
******IL    MV+000000145786NT+000000093045
```

After skip:

```text
******F     EJ+00000012345EK+00000045678
******IL    MV+000000145786NT+000000093045
```

CA line is removed.

Federal and IL stay.

### Status

| Item | Status |
|------|--------|
| file | written |
| job | success |
| line count | reduced |
| error write status | `SKIPPED` |

---

## 12. Practical Example 5: Skip Entire Employee

### Input

Error:

| worker_sk | error_code |
|-----------|------------|
| 362 | SSN_INVALID |

Rule:

```text
EMPLOYEE_PROFILE_ERROR -> SKIP_ENTIRE_EMPLOYEE
```

Before skip:

```text
******      CSCUNEAL      CUJACKSON
******F     EJ+00000012345EK+00000045678
******      CSMAYA        CULEE
******F     EJ+00000021000EK+00000090000
```

After skip:

```text
******      CSCUNEAL      CUJACKSON
******F     EJ+00000012345EK+00000045678
```

Maya Lee is removed completely.

### Status

| Item | Status |
|------|--------|
| file | written |
| job | success |
| error write status | `SKIPPED` |

Key point:

```text
Skipping an employee because of business rules is not a technical failure.
```

---

## 13. Practical Example 6: Skip All Company Tax

### Input

Error:

| error_code | category |
|------------|----------|
| FEIN_IS_MISSING | Registration |

Possible rule:

```text
COMPANY_TAX_ID_ERROR -> SKIP_COMPANY_TAX_OUTPUT
```

Before skip:

```text
******      CSCUNEAL      CUJACKSON
******F     EJ+00000012345EK+00000045678
******CA    MV+000000234567NT+000000070000
******      CSMAYA        CULEE
******F     EJ+00000021000EK+00000090000
```

After skip:

```text
******      CSCUNEAL      CUJACKSON
******      CSMAYA        CULEE
```

Employee lines remain.

Tax lines are removed.

### Status

| Item | Status |
|------|--------|
| file | written |
| job | success |
| error write status | `SKIPPED` |

Important:

Business must confirm whether FEIN errors mean:

1. skip only tax output
2. skip the whole company
3. skip nothing

The design supports all three.

---

## 14. Practical Example 7: Skip Whole Company

### Input

Rule:

```text
COMPANY_TAX_ID_ERROR -> SKIP_COMPANY_OUTPUT
```

This means no employee lines and no tax lines for that company.

### Possible Output Option 1: Minimal File

```text
<FILE HEADER>
9999999999990000002
```

### Possible Output Option 2: No File

The job marks the outbound file as:

```text
SKIPPED
```

This is a business decision.

The current code may treat "no worker lines" as failure. Final implementation should separate:

| Situation | Meaning |
|----------|---------|
| no workers because query failed | technical failure |
| no workers because rule skipped them | business skip |

---

## 15. What Happens If Multiple Errors Exist?

Example:

| Error | Scope |
|-------|-------|
| SSN invalid | skip entire employee |
| CA wage plan missing | skip CA tax only |
| FIT amount invalid | skip `EJ` code |

If all apply to the same employee, the biggest skip wins.

So:

```text
SKIP_ENTIRE_EMPLOYEE
```

wins over:

```text
SKIP_TAX_JURISDICTION
SKIP_GSI_CODE
```

Reason:

If the whole employee is removed, there is no need to separately remove CA or `EJ`.

---

## 16. What Is Success?

Success means the job produced the correct result based on data and rules.

Success can include skipped data.

| Scenario | Success? | Why |
|----------|----------|-----|
| no errors, full file written | yes | normal processing |
| CA tax skipped by rule | yes | business rule applied |
| employee skipped by rule | yes | business rule applied |
| unknown error logged, no skip | yes with warning | fail-open behavior |
| all company output intentionally skipped | yes or skipped | business rule applied |

---

## 17. What Is Failure?

Failure means the job could not safely produce the expected output.

| Scenario | Failure? |
|----------|----------|
| Redshift connection fails | yes |
| secrets cannot load | yes |
| no organization found for site | yes |
| all worker queries fail | yes |
| file write fails | yes |
| status update fails after file write | needs reconciliation |
| error table cannot be read | initially warning, not failure |
| rule catalog missing | initially warning, not failure |

Recommended rollout:

```text
Start fail-open for error/rule lookup.
Generate file and log warning.
After rules are trusted, decide if some errors should fail-closed.
```

---

## 18. Where The New Logic Should Live

Do not put all logic inside `main.py`.

Do not put business rules inside `gsi_formatter.py`.

Recommended structure:

| File | Responsibility |
|------|----------------|
| `error_handler.py` | read errors, categorize, create skip decisions |
| `db_connection.py` | query `company_errors` and `error_catalog` |
| `skip_rules.yaml` | configurable category-to-skip-scope rules |
| `main.py` | call error handler and pass decisions forward |
| `gsi_formatter.py` | apply final skip decisions while formatting |
| `logger.py` | log what was skipped and why |

---

## 19. Final Simple Design

The simplest correct design is:

```text
Read errors
    |
Group errors into categories
    |
Look up category in rules
    |
Create skip decisions
    |
Apply decisions while data is still structured
    |
Build GSI file
    |
Log exactly what was skipped
```

This keeps the design dynamic.

When business later says:

```text
WAGE_PLAN_ERROR should skip CA/SIT
```

we update rules.

When business later says:

```text
EMPLOYEE_PROFILE_ERROR should skip whole employee
```

we update rules.

We should not need to rewrite the whole GSI generation flow.

---

## 20. One-Line Summary

The new design adds a decision layer that checks validation errors before writing GSI output, then dynamically decides whether to keep or skip workers, tax lines, jurisdictions, or individual GSI codes based on configurable business rules.

