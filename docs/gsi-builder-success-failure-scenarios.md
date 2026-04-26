# GSI Builder - Practical Success & Failure Scenarios

This document walks through the most useful success and failure paths in the
quarter GSI builder using **realistic sample data**. For each scenario you get:

- the upstream Redshift state at the start of the run,
- what the job does at each stage,
- the resulting GSI file content (or what is written instead),
- the final state of the `outbound_file` row,
- what the operator sees (logs + email).

All examples assume `ENV=dit`, `site_id = GE59`, `year = 2026`, `quarter = 1`,
program start time `2026-04-25 11:30:00 UTC` (so the timestamp prefix is
`260425113000`).

> **Note on values.** Numeric formatting examples use the static fallback in
> `gsi_mappings._static_tax_fallback()` and `_get_static_fallback_mappings()`,
> which is what runs when the tax-mapping API or PostgreSQL GI1/GI2 metadata is
> not reachable. Lines are shown trimmed to the meaningful prefix; in the real
> file every record is exactly 160 characters wide.

---

## 0. The Plumbing in One Picture

```
outbound_file (QUEUED, QUARTER)
        |
        v
process_sites_parallel  -- ThreadPoolExecutor (max 4)
        |
        v
process_site_event(site_id, year, quarter)
   |
   |-- update outbound_file -> GENERATING
   |-- query_site_organizations  -> [(branch, company), ...]
   |
   |   for each (branch, company):
   |     query_workers          -> worker DataFrame
   |     apply_gsi_mappings     -> EE lines + F/S/L worker_level_df
   |     query_all_worker_tax   -> tax DataFrame
   |     validate_mandatory_fields / ensure_mandatory_fields
   |     format_tax_data_df     -> jurisdiction tax lines
   |
   |-- union worker + tax + per-company headers
   |-- prepend file header, append trailer
   |-- S3Writer.write_gsi_dataframe -> /Volumes/.../GSI_<site>_Q<q>_<year>_<ts>.txt
   |
   |-- update outbound_file -> GENERATED + s3_key + record_count + file_name
   |-- email_notifier.send_notification SUCCESS
```

On any uncaught exception inside `process_site_event` the catch block sets
`outbound_file -> FAILED` and sends a `FAILED` email. Errors *inside* the
per-company loop are isolated: the rest of the run continues.

---

## 1. Success Scenarios

### S1. Happy Path - 1 Site, 1 Company, 1 Worker

#### S1.1 Input - Redshift state at run start

`onetax.outbound_file`:

| batch_id  | site_id | year | quarter | window_start | window_end | status | file_type |
|-----------|---------|------|---------|--------------|------------|--------|-----------|
| BATCH-001 | GE59    | 2026 | 1       | 2026-01-01   | 2026-03-31 | QUEUED | QUARTER   |

`onetax.organization_unit`:

| branch_code | company_code | site_id |
|-------------|--------------|---------|
| 01          | C001         | GE59    |

`onetax.worker`:

| worker_sk | branch_code | company_code | family_name | given_name | ssn         | birth_date | hire_date  | job_title  |
|-----------|-------------|--------------|-------------|------------|-------------|------------|------------|------------|
| 1001      | 01          | C001         | SMITH       | JOHN       | 123-45-6789 | 1985-03-15 | 2020-06-01 | ENGINEER   |

`onetax.worker_address`:

| worker_sk | type | line_one     | city_name | state_code | postal_code |
|-----------|------|--------------|-----------|------------|-------------|
| 1001      | Work | 1 ADP BLVD   | ROSELAND  | NJ         | 07068       |
| 1001      | Home | 100 MAIN ST  | NEWARK    | NJ         | 07101       |

`onetax.worker_tax_qtr_snapshot` (latest payroll per `worker_sk + jurisdiction + tax_type + is_employer_tax`):

| worker_sk | state | local | tax_type | qtd_amount | ytd_amount | qtd_gross_wages | ytd_gross_wages | is_employer_tax |
|-----------|-------|-------|----------|-----------:|-----------:|----------------:|----------------:|:---------------:|
| 1001      | NULL  | NULL  | FIT      |    1500.00 |    1500.00 |        15000.00 |        15000.00 | false           |
| 1001      | NJ    | NULL  | SIT      |     450.00 |     450.00 |        15000.00 |        15000.00 | false           |

#### S1.2 Stage-by-stage transformation

1. `query_queued_outbound_files` returns 1 row (`BATCH-001 / GE59`).
2. `update_outbound_file_status -> GENERATING`.
3. `query_site_organizations(['GE59'])` returns `[(01, C001)]`.
4. `query_workers('01', 'C001', 2026, 1)` returns 1 row, with `Work_*` and `Home_*` columns pivoted from `worker_address`.
5. `apply_gsi_mappings` produces formatted columns (static fallback codes shown):

   | Source            | GSI code | Formatted value           |
   |-------------------|----------|---------------------------|
   | `given_name`      | `CS`     | `CSJOHN        `          |
   | `family_name`     | `CU`     | `CUSMITH         `        |
   | `ssn`             | `DD`     | `DD123-45-6789`           |
   | `birth_date`      | `SY`     | `SY19850315`              |
   | `hire_date`       | `NZ`     | `NZ06012020`              |
   | `work_line_one`   | `SQ`     | `SQ1 ADP BLVD                  ` |
   | `work_state_code` | `DA`     | `DANJ`                    |
   | `home_line_one`   | `Z5`     | `Z5100 MAIN ST                              ` |
   | `job_title` (S level) | `Z3` | merged into NJ tax line   |

6. EE columns are concatenated with the prefix `******      ` (12 chars), respecting the 160-char limit, by `build_employee_lines_udf`.
7. `query_all_worker_tax` returns the two rows above. `format_tax_data_df`:
   - rewrites `tax_type=FIT -> FIT` (no remap; FIT not in `TAX_TYPE_MAPPINGS`),
   - resolves jurisdictions: `state_code IS NULL -> 'F'`, `state_code='NJ', local_code IS NULL -> 'NJ'`,
   - formats numeric fields. For FIT QTD `1500.00`: code `EJ`, signed length 12, value scaled by 100 -> `150000`, padded to numeric_length 11 -> `00000150000`, result `EJ+00000150000`.

8. Final per-jurisdiction tax lines (160-char rows truncated for display):

   ```
   ******F     EJ+00000150000EK+0000000150000
   ******NJ    MV+00001500000NT+00001500000
   ```

9. Worker `S`-level fields (e.g. `job_title -> Z3`) are merged into the NJ state line by the `worker_level_df` join.
10. File header (`generate_gsi_header(2026, 1)`):
    ```
    [12 spaces]260425113000WDQTRRECON261[11 spaces]Q[111 spaces]
    ```
11. Per-company header is built inline in `process_site_event`:
    ```
    [6 spaces]01C00110000NN[13 spaces]Y[118 spaces]
    ```
12. Trailer with line count: `999999999999` + zfill(7).
13. `S3Writer.write_gsi_dataframe` writes a single text file to the Volume:
    `/Volumes/onedata_us_east_1_shared_dit/ssot_raw_scs_n8_dit/adp-onetax-wd-quarter-outbound/GSI_GE59_Q1_2026_20260425_113000.txt`.

#### S1.3 Final output file (representative)

```
            260425113000WDQTRRECON261           Q                                                                                                               
      01C00110000NN             Y                                                                                                                                              
******      CSJOHN        CUSMITH         DD123-45-6789SY19850315NZ06012020SQ1 ADP BLVD                  DANJ Z5100 MAIN ST                              ...
******F     EJ+00000150000EK+0000000150000
******NJ    Z3ENGINEER...MV+00001500000NT+00001500000
9999999999990000005
```

#### S1.4 `outbound_file` final state

| batch_id  | site_id | year | quarter | status    | s3_key                                             | record_count | outbound_file_name                              |
|-----------|---------|------|---------|-----------|----------------------------------------------------|-------------:|--------------------------------------------------|
| BATCH-001 | GE59    | 2026 | 1       | GENERATED | worker-detail/GSI_GE59_Q1_2026_20260425_113000.txt |            5 | GSI_GE59_Q1_2026.txt                            |

#### S1.5 Operator-visible signal

- **Logs:** `Started Processing Site: GE59`, `Found 1 workers for 01/C001`, `Tax data formatting completed in 0.83s`, `Written to: /Volumes/.../GSI_GE59_Q1_2026_20260425_113000.txt`, `Completed: 1/1 sites succeeded`.
- **Email subject:** `WD QTR GSI Builder - SUCCESS`. Body includes site, year, quarter, runtime, Databricks job link.

---

### S2. Multi-Company Site - All Companies Succeed

#### S2.1 Input

`onetax.organization_unit` (same site, two companies):

| branch_code | company_code | site_id |
|-------------|--------------|---------|
| 01          | C001         | GE59    |
| 01          | C002         | GE59    |

`onetax.worker`: 1 worker (`1001`) under `C001`, 2 workers (`2001`, `2002`) under `C002`. Each has FIT + SIT(NJ) tax rows in `worker_tax_qtr_snapshot`.

#### S2.2 What happens

`process_site_event` iterates the company list **sequentially within the site** (companies are NOT parallelized; only sites are). Per company:

| Iteration | Branch / Company | Workers found | Worker lines | Tax lines |
|-----------|------------------|--------------:|-------------:|----------:|
| 1/2       | 01 / C001        | 1             | 1            | 2         |
| 2/2       | 01 / C002        | 2             | 2            | 4         |

The combined DataFrame is sorted by `branch_code, company_code, worker_sk` so all of `C001`'s lines come before all of `C002`'s lines, with a per-company header in front of each block.

#### S2.3 Final output file shape

```
[file header]
      01C00110000NN...Y...                     <- header for C001
******      ... worker 1001 ...
******F     ...
******NJ    ...
      01C00210000NN...Y...                     <- header for C002
******      ... worker 2001 ...
******F     ...
******NJ    ...
******      ... worker 2002 ...
******F     ...
******NJ    ...
9999999999990000010
```

#### S2.4 `outbound_file` final state

`status = GENERATED`, `record_count = 10` (file header + 2 company headers + 3 worker lines + 6 tax lines + trailer minus headers/trailer accounting).

---

### S3. Worker With Federal + State + Local Tax (Jurisdiction Hierarchy)

#### S3.1 Input

`worker_tax_qtr_snapshot` for `worker_sk=1001`, `branch=01`, `company=C001`:

| state | local | tax_type | qtd_amount | ytd_amount | is_employer_tax |
|-------|-------|----------|-----------:|-----------:|:---------------:|
| NULL  | NULL  | FIT      |    1500.00 |    1500.00 | false           |
| CA    | NULL  | SIT      |     400.00 |     400.00 | false           |
| CA    | 0123  | CIT      |      75.00 |      75.00 | false           |

`query_all_worker_tax` projects `jurisdiction` as:

- `state_code IS NULL` -> `F`
- `local_code IS NULL` -> `<state>` (e.g. `CA`)
- otherwise -> `<state> + RIGHT(local_code, 4)` (e.g. `CA0123`)

#### S3.2 What happens in `format_tax_data_df`

Three groups (`worker_sk=1001, jurisdiction_fmt='F     '`, `'CA    '`, `'CA0123'`). Worker level fields:

- `F` worker level (e.g. `pull_indicator -> G6`, `employee_id -> V9`) are joined onto the federal line.
- `S` worker level (e.g. `job_title -> Z3`, `pay_rate_amount -> A7`) are joined onto the **state** line (`CA`, `length(jurisdiction)=2`).
- `L` worker level (e.g. `wfh_indicator -> 9F`) are joined onto the **local** line (`CA0123`, `length>2`).

#### S3.3 Final output (jurisdiction lines only)

```
******F     V9EMP000001 G6Y G5N EJ+00000150000EK+0000000150000
******CA    Z3ENGINEER...A7+0000005000DH? DI?? ?_state_filing_status...MV+00000400000NT+00000400000
******CA01239FY ?DK? DL?? ?_local_filing_status...
```

The `S` block goes only on `CA`, not on `CA0123`. The `L` block goes only on
`CA0123`. This is enforced by the conditional join in `format_tax_data_df`:

```
((level_type = 'F') & is_federal) OR
((level_type = 'S') & is_state)   OR
((level_type = 'L') & is_local)
```

---

### S4. Mandatory Tax Field Backfill

Static fallback declares Social Security EE QTD (`7H`), Social Security EE YTD
(`5H`) and Medicare EE YTD (`5E`) as `mandatory: True`.

#### S4.1 Input

`worker_tax_qtr_snapshot` for `worker_sk=1001` only contains FIT and SIT - no
SSEE / MEDEE rows.

#### S4.2 What happens

1. `validate_mandatory_fields` logs:
   ```
   7H (SSEE-QTD): 0/1 workers
   Missing 7H: 1 workers
   5H (SSEE):    0/1 workers
   Missing 5H: 1 workers
   5E (MEDEE):   0/1 workers
   Missing 5E: 1 workers
   STATUS: SOME WORKERS MISSING MANDATORY FIELDS
   ```
2. `ensure_mandatory_fields` adds default zero rows to `tax_df`:

   | worker_sk | jurisdiction | tax_type | qtd_amount | ytd_amount | is_employer_tax |
   |-----------|--------------|----------|-----------:|-----------:|:---------------:|
   | 1001      | F            | SSEE-QTD |       0.00 |       0.00 | false           |
   | 1001      | F            | SSEE     |       0.00 |       0.00 | false           |
   | 1001      | F            | MEDEE    |       0.00 |       0.00 | false           |

3. `format_tax_data_df` then formats them into the federal jurisdiction line.

#### S4.3 Final output - federal line includes mandatory zeros

```
******F     EJ+00000150000EK+00000001500007H+000000000005H+00000000000005E+0000000000000
```

The job **does not fail** when mandatory fields are missing. It fills with
defaults so the file remains schema-complete for the downstream consumer.

---

### S5. PostgreSQL Down - Static Fallback Mappings

#### S5.1 Input

Same as S1, but the `onetax.GI1` / `onetax.GI2` reads time out, **or** the
postgres secret is missing.

#### S5.2 What happens

- `_build_gsi_mappings_from_database()` catches the exception and returns
  `_get_static_fallback_mappings()`.
- `_init_mappings()` similarly falls back to `_static_tax_fallback()` if the
  tax-code-mapping API also fails.
- Logs:
  ```
  Failed to build mappings from database after 30.12s: connection refused
  Using static fallback GSI mappings
  Generated 0 tax mappings from API   (or)   API failed: ...
  Using static mappings: ...
  ```

#### S5.3 Final output

Identical in **shape** to S1. Codes/lengths come from the hard-coded fallback
in `gsi_mappings.py` instead of GI1/GI2; values are unchanged.

`outbound_file -> GENERATED`. Email **subject** says `SUCCESS`. The fallback is
intentionally silent at the file level, but the postgres failure is captured in
Splunk for SRE follow-up.

---

### S6. Long Worker Data - Lines Split at 160 chars

#### S6.1 Input

Worker `1001` has `job_title = "SENIOR PRINCIPAL DISTRIBUTED SYSTEMS ENGINEER, PAYROLL PLATFORM, NORTH AMERICA"` (80 chars). After GSI formatting `Z3` becomes a 82-char field. Combined with name, SSN, dates, and address fields, the EE line crosses the 160-char limit.

#### S6.2 What happens

`build_employee_lines_with_limit` (the UDF behind `build_employee_lines_udf`)
emits multiple lines, each prefixed with `******      ` (12 chars):

```
******      CSJOHN        CUSMITH         DD123-45-6789SY19850315NZ06012020SQ1 ADP BLVD                  DANJ Z5100 MAIN ST                              ...
******      ...continued GSI fields that did not fit on the previous line...
```

GSI codes are never split across line boundaries; the splitter only breaks
between fields. Tax lines have the same behavior in `build_tax_lines_with_split`
with the prefix `******<jurisdiction>` re-emitted on each continuation.

#### S6.3 Final output

`outbound_file -> GENERATED`, `record_count` reflects the actual physical line
count (one extra line per worker that overflowed).

---

## 2. Failure Scenarios

For every failure the **happy path of the rest of the run** is preserved where
possible. The job is designed to isolate failures by company, by site, and by
optional component (Postgres, mandatory-fields step) so a single bad row never
halts the whole batch.

### F1. Configuration Validation Failure

#### F1.1 Trigger

`config["redshift"]["host"]` is empty (or `app.batch_size` is a string instead
of int). Could be the result of a misdeployed tfvar.

#### F1.2 What happens

`flow_validator.validate_config(config)` raises **before any Spark or DB code
runs** (this happens at module import in `main.py`):

```
Configuration validation failed: Empty value for redshift.host, Invalid type for app.batch_size: expected int, got str
```

#### F1.3 State changes

- **No** rows in `outbound_file` are touched - the job died before
  `query_queued_outbound_files`.
- No file is written.
- No email is sent (`EmailNotifier` was never instantiated).
- Databricks marks the run as `FAILED` from the Python exit code.

#### F1.4 Operator-visible signal

The Databricks run page shows the stack trace; the cluster log destination
(`s3://<bucket>/databricks/scs/scs-n8-dev`) captures the same. No Splunk events
because Splunk handler initializes after config validation.

---

### F2. AWS Secrets Manager Unreachable

#### F2.1 Trigger

`get_redshift_credentials()` returns `None` and `GSI_ALLOW_MISSING_SECRETS` is
not set.

#### F2.2 What happens

In `config/<env>.py`:

```
RuntimeError: Failed to retrieve Redshift credentials from Secrets Manager
```

`main.py` import fails with this exception. Same end-state as F1: no
`outbound_file` writes, no file written, no email.

#### F2.3 Recovery

For local import-only smoke testing set
`export GSI_ALLOW_MISSING_SECRETS=true`; the job will boot with localhost
placeholder credentials so `import wd.qtr.gsi_builder.main` succeeds, but DB
queries will then fail at runtime - this is intended for unit/import tests, not
real runs.

---

### F3. No Queued Records

#### F3.1 Trigger

`outbound_file` has no rows with `status='QUEUED' AND file_type='QUARTER'`.

#### F3.2 What happens

```
INFO  No queued files to process
```

Function returns. `db_conn.close_write_connection()` runs in `finally`.

#### F3.3 State changes

Nothing. No emails. The Databricks run is a clean SUCCESS.

This is the intended behavior - the job is idempotent and re-runs are cheap.

---

### F4. No Companies Found For Site

#### F4.1 Trigger

The queued row points to `site_id='GE59'`, but `organization_unit` has no rows
matching that `site_id` (e.g. site decommissioned or typo).

#### F4.2 What happens (inside `process_site_event`)

1. `update_outbound_file_status -> GENERATING`.
2. `query_site_organizations(['GE59'])` returns empty.
3. `raise Exception("No companies found for site_id: GE59")` triggers the catch
   block.

#### F4.3 State changes

`outbound_file` final state:

| batch_id  | site_id | status |
|-----------|---------|--------|
| BATCH-001 | GE59    | FAILED |

> **Known gap:** the `error_message` column is **not** populated even though
> the schema and `update_outbound_file_failure(error_message)` helper support it
> - the failure path uses `update_outbound_file_status(... FAILED)` instead.

#### F4.4 Operator-visible signal

- **Email:** `WD QTR GSI Builder - FAILED`, body includes
  `Error: No companies found for site_id: GE59`.
- **Logs:** `Exception processing site GE59: No companies found for site_id: GE59`.

---

### F5. One Company's Worker Query Fails (Others Succeed)

#### F5.1 Trigger

For site `GE59` there are two companies (`C001`, `C002`). The Redshift query
for `C001` raises (e.g. statement timeout, transient JDBC error). `C002`'s
query is fine.

#### F5.2 What happens

Inside `process_site_event`'s per-company loop:

```
ERROR Worker query failed for 01/C001: Driver socket timeout after 180s
INFO  [2/2] Processing branch: 01, company: C002
INFO  Found 2 workers for 01/C002
```

The `continue` statement inside the per-company `try/except` skips the failing
company. The site as a whole **still produces a file** containing only `C002`'s
data.

#### F5.3 Final output file

```
[file header]
      01C00210000NN...Y...
******      ... worker 2001 ...
...
9999999999990000007
```

There is no header for `C001` because `C001` produced no lines.

#### F5.4 `outbound_file` final state

`status = GENERATED` (not `FAILED`). The site succeeded; one company was
silently skipped. This is **important**: a partial file ships if any company
succeeded.

#### F5.5 Operator-visible signal

`WD QTR GSI Builder - SUCCESS` email is sent. The C001 failure is **only**
visible in the log line above. If the consumer expects all companies and gets a
short file, this can be subtle.

> If your business requires "all-or-nothing per site," this default is wrong
> for you and is something to escalate.

---

### F6. All Companies Fail / No Worker Data Found For Site

#### F6.1 Trigger

Either every company's `query_workers` raised, or every company returned
`isEmpty()` (e.g. no workers in scope for the quarter), so `all_worker_lines`
is `[]`.

#### F6.2 What happens

```
raise Exception("No worker data found for site: GE59")
```

Caught by the outer `except`, `outbound_file -> FAILED`, FAILED email sent.

#### F6.3 State changes

| batch_id  | site_id | status |
|-----------|---------|--------|
| BATCH-001 | GE59    | FAILED |

No file is created on the Volume.

---

### F7. Volume Write Fails

#### F7.1 Trigger

`output_df.coalesce(1).write.text(temp_path)` succeeds but `dbutils.fs.ls`
returns no non-empty part files (rare; can happen on permission revocations or
transient Volume issues).

#### F7.2 What happens

`S3Writer.write_gsi_dataframe`:

```
ERROR No non-empty part files found
ERROR Row 0: Row(value='            260425113000WDQTRRECON261...')
ERROR Row 1: Row(value='      01C00110000NN...')
...
ERROR Error writing to volume: No non-empty part files found in temporary directory
```

It returns `None`. Back in `process_site_event`:

```python
output_file = s3_writer.write_gsi_dataframe(output_df, ...)   # -> None
s3_key = f"worker-detail/{output_file.split('/')[-1]}" ...    # AttributeError
```

The `AttributeError` is caught by the outer `except` -> `outbound_file -> FAILED`,
email FAILED.

> **Known sharp edge:** when `write_gsi_dataframe` returns `None`, the success
> branch still tries to do string ops on it instead of explicitly raising. The
> end result is correct (the run is marked FAILED), but the failure reason in
> the email is `AttributeError: 'NoneType' object has no attribute 'split'`
> rather than the real `No non-empty part files found in temporary directory`.

---

### F8. Mandatory Fields Step Crashes

#### F8.1 Trigger

`validate_mandatory_fields` or `ensure_mandatory_fields` raises - typically
because `TAX_MAPPINGS` failed to load and a downstream column is missing.

#### F8.2 What happens

Inside `process_site_event` the inner `try/except` swallows it:

```
WARN  Mandatory fields processing failed: 'NoneType' object is not iterable
```

The flow continues with `tax_formatted = format_tax_data_df(tax_df, worker_level_df)`
called on the **un-augmented** `tax_df` - i.e. without the zero-defaults that
the validator would have added.

#### F8.3 Effect on output

The file is still generated. Workers that lacked mandatory tax types will have
**no** `7H` / `5H` / `5E` field on their federal jurisdiction line. This is a
business-visible difference from S4.

#### F8.4 `outbound_file` final state

`status = GENERATED`, despite the warning. This is by design (mandatory-field
back-fill is a best-effort enrichment, not a hard precondition).

---

## 3. Quick-Reference Matrix

| Scenario | `outbound_file.status` | File on Volume | Email | Notes |
|----------|------------------------|----------------|-------|-------|
| S1 Happy path | GENERATED | yes | SUCCESS | baseline |
| S2 Multi-company | GENERATED | yes | SUCCESS | one file per site |
| S3 F + S + L | GENERATED | yes | SUCCESS | level-aware tax merge |
| S4 Mandatory backfill | GENERATED | yes | SUCCESS | zero defaults added |
| S5 Postgres/API down | GENERATED | yes | SUCCESS | static fallback used |
| S6 Long worker data | GENERATED | yes | SUCCESS | extra physical lines |
| F1 Config invalid | unchanged (no row touched) | no | none | fails before main() |
| F2 Secrets unreachable | unchanged | no | none | fails at import |
| F3 No queued records | n/a | no | none | clean exit |
| F4 No companies for site | FAILED | no | FAILED | error_message NOT persisted |
| F5 One company fails | GENERATED | yes (partial) | SUCCESS | other company silently skipped |
| F6 No worker data anywhere | FAILED | no | FAILED |  |
| F7 Volume write fails | FAILED | no | FAILED | email shows AttributeError, not real cause |
| F8 Mandatory step crashes | GENERATED | yes | SUCCESS | mandatory zeros missing |

## 4. Known Gaps Worth Tracking

These show up in the failure walkthroughs and are worth raising as separate
tickets if they matter to your downstream consumers:

1. **Failure reason not persisted to `outbound_file.error_message`** (F4, F6, F7).
   `update_outbound_file_failure(error_message)` exists in `db_connection.py`
   but is never called.
2. **Per-company failures are silent at the file/email level** (F5). A site
   with one failing company still ships a partial file and a SUCCESS email.
3. **`write_gsi_dataframe` returns `None` on failure** (F7), causing a
   downstream `AttributeError` to be reported instead of the real cause.
4. **Mandatory-field crashes degrade silently** (F8). The file is shipped
   without the mandatory zero-defaults; only a `WARN` log surfaces it.

These are referenced for context only; addressing them is out of scope of the
error-based skip handling design (`docs/gsi-error-skip-design-proposal.md`),
which deals with a different class of "errors."
