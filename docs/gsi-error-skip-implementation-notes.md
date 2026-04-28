# GSI Error Skip Implementation Notes

**Status:** Initial implementation  
**Purpose:** Explain the code changes for filing-impact company and worker skips  

---

## 1. What Was Implemented

This change implements the first simple version of error-based skip behavior.

It does two things:

1. If a company has an active company error whose `error_catalog.impacts_filing` is true/Y, the job skips the entire company.
2. If a worker has an active worker tax/profile/transaction error whose `error_catalog.impacts_filing` is true/Y, the job skips the entire worker.

This is intentionally smaller than the full dynamic design. It uses only `impacts_filing` as the trigger.

---

## 2. New Behavior In Plain English

### Company Error

If this exists:

```text
company_errors.error_code = error_catalog.error_code
error_catalog.impacts_filing = true
company_errors.resolution_status = Open
company_errors.write_status = PENDING
```

then:

```text
drop the entire company from the GSI file
```

### Worker Error

If a worker-level error table has:

```text
worker_sk
error_code
```

and the error joins to:

```text
error_catalog.impacts_filing = true
```

then:

```text
drop that whole worker from the GSI file
```

That means the worker employee line and all worker tax lines are removed.

---

## 3. Files Changed

| File | Change |
|------|--------|
| `src/wd/qtr/gsi_builder/error_handler.py` | New module that resolves skip decisions. |
| `src/wd/qtr/gsi_builder/db_connection.py` | Adds queries for company filing-impact errors and worker filing-impact errors. |
| `src/wd/qtr/gsi_builder/main.py` | Applies skip decisions during company/worker processing. |
| `tests/test_error_handler.py` | Adds lightweight tests for skip decision behavior. |

---

## 4. New Module: `error_handler.py`

This module creates an `ErrorSkipDecision`.

The decision contains:

| Field | Meaning |
|-------|---------|
| `skip_company` | True means skip the whole company. |
| `worker_sks_to_skip` | Worker IDs to remove from the file. |
| `company_error_count` | Number of company filing-impact errors found. |
| `worker_error_count` | Number of workers being skipped. |

The main function is:

```text
resolve_error_skip_decision(...)
```

It calls the database layer and returns one decision for one company.

---

## 5. Company Skip Query

The new database method is:

```text
query_company_filing_error_count(...)
```

It checks:

```text
company_errors
join error_catalog
join organization_unit
```

It only counts errors where:

```text
resolution_status = Open
write_status = PENDING
impacts_filing = true / Y
```

If the count is greater than zero, the company is skipped.

---

## 6. Worker Skip Query

The new database method is:

```text
query_worker_filing_error_worker_sks(...)
```

The exact worker error table name is not confirmed in the repo, so the code checks likely table names:

```text
worker_tax_errors
worker_tax_error
worker_transaction_errors
worker_transactions_errors
worker_transaction_error
worker_profile_errors
worker_profile_error
worker_errors
worker_error
```

For a worker error table to be usable, it must have at least:

```text
worker_sk
error_code
```

Optional columns supported:

```text
resolution_status
write_status
year
quarter
payroll_run_sk
organization_unit_sk
```

If no worker error table exists, the job logs and continues. Current behavior does not break.

---

## 7. Main Flow Change

Before processing each company, `main.py` now does:

```text
resolve skip decision
```

Then:

| Decision | Action |
|----------|--------|
| `skip_company = true` | do not query/build worker or tax output for that company |
| `worker_sks_to_skip` not empty | remove those workers from worker DataFrame |
| `worker_sks_to_skip` not empty | remove those workers from tax DataFrame |

If all companies/workers are removed only because of filing-impact skip decisions, the outbound file is marked:

```text
SKIPPED
```

instead of:

```text
FAILED
```

---

## 8. Example

### Input

Company error:

| organization_unit_sk | error_code | impacts_filing |
|----------------------|------------|----------------|
| 227 | FEIN_IS_MISSING | true |

### Result

```text
Company is skipped.
No employee or tax lines are written for that company.
```

### Another Input

Worker error:

| worker_sk | error_code | impacts_filing |
|-----------|------------|----------------|
| 361 | SSN_INVALID | true |

### Result

```text
Worker 361 is skipped.
Worker 361 employee line is removed.
Worker 361 tax lines are removed.
Other workers remain.
```

---

## 9. What Is Still Required

For company-level skip, required tables are already documented:

```text
company_errors
error_catalog
organization_unit
worker_tax_qtr_snapshot
```

For worker-level skip, we still need the real production worker error table name and schema.

At minimum, the worker error table must provide:

```text
worker_sk
error_code
```

Without `worker_sk`, the job cannot safely know which worker to remove.

---

## 10. Validation

Validation done:

```text
python3 -m compileall ...
```

Result:

```text
passed
```

`pytest` could not run locally because the local Python environment does not have `pytest` installed.

Manual lightweight tests for `error_handler.py` were run with:

```text
PYTHONPATH=src python3 ...
```

Result:

```text
passed
```

---

## 11. Important Note

This is not the full future rule-catalog design.

This is the immediate requested behavior:

```text
impacts_filing = true on company error -> skip company
impacts_filing = true on worker error -> skip worker
```

The bigger dynamic design can still be added later when the full category-to-skip mapping is known.

