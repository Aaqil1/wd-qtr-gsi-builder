# WD QTR GSI Builder - End-to-End Project Walkthrough

## Purpose

`wd-qtr-gsi-builder` is a Databricks PySpark job that creates quarterly GSI text files for tax reporting. It reads worker and tax data, formats that data into fixed GSI code/value segments, writes the output file to a Databricks Volume, and updates processing status in the database.

## Input Side

The upstream business event is represented by the redacted sample JSON in `docs/reference/sample-periodic-tax-deposit-event.redacted.json`.

That JSON contains:

- application metadata such as event type and run type
- organization and organization-unit data
- branch/company/site identifiers
- payroll run context
- worker details
- tax and jurisdiction summaries

The Databricks job does not currently parse this JSON directly. Instead, it reads normalized data from database tables.

## Runtime Entry Point

The job entry point is:

`src/wd/qtr/gsi_builder/main.py`

At startup it:

1. Loads the environment config through `config/loader.py`.
2. Validates required config sections with `flow_validator.py`.
3. Initializes logging and Splunk logging where configured.
4. Creates a Spark session.
5. Creates a Redshift connection for worker/tax/outbound-file data.
6. Optionally creates a PostgreSQL connection for GI1/GI2 mapping metadata.
7. Creates `S3Writer` and `EmailNotifier`.

## Deployment Configuration

Terraform and deployment parameters live under `params/`.

Important files:

| File | Purpose |
|------|---------|
| `params/databricks.tf` | Defines the Databricks job, cluster, libraries, and permissions. |
| `params/variables.tf` | Terraform variables for environment, account, bucket, Databricks host, policies, etc. |
| `params/dit.tfvars`, `fit.tfvars`, `iat.tfvars`, `prod.tfvars` | Environment-specific values. |
| `params/application.yaml`, `params/common.yaml` | CI/CD metadata and product/deployment settings. |

## Processing Flow

### 1. Find Queued Work

`main()` calls:

`db_conn.query_queued_outbound_files()`

This reads records from `outbound_file` where:

- `status = 'QUEUED'`
- `file_type = 'QUARTER'`

Each queued record identifies the site/year/quarter that needs a GSI file.

### 2. Load GSI Mappings

The orchestrator calls:

`load_mappings()` from `gsi_mappings.py`

Mappings come from:

- PostgreSQL `GI1` and `GI2` tables when available
- static fallback mappings when database metadata is unavailable

These mappings define:

- source field name
- GSI code
- field length
- data type
- decimal places
- signed/unsigned formatting
- GSI level: `EE`, `F`, `S`, or `L`

### 3. Process Each Site

`orchestrator.py` runs site records in parallel using `ThreadPoolExecutor`.

Each site is processed by:

`process_site_event()`

For each site:

1. Status is changed to `GENERATING`.
2. The job queries all branch/company combinations for that site.
3. Each company is processed one at a time.

### 4. Query Worker Data

For each branch/company:

`db_conn.query_workers(branch_code, company_code, year, quarter)`

This returns worker-level fields such as:

- worker key
- branch/company
- first/last name
- SSN
- birth/hire/termination dates
- work/home addresses
- indicators and flags
- department, employee ID, job title, pay rate

### 5. Format Worker GSI Fields

`apply_gsi_mappings()` in `gsi_formatter.py` formats worker fields.

Examples:

| Source Field | GSI Code |
|--------------|----------|
| `given_name` | `CS` |
| `family_name` | `CU` |
| `ssn` | `DD` |
| `birth_date` | `SY` |
| `hire_date` | `NZ` |

The formatter:

- trims or pads text fields
- formats dates
- scales decimals
- adds signs where needed
- prepends the two-character GSI code
- builds employee lines capped at 160 characters

Employee lines start with:

`******      `

### 6. Query Tax Data

For each company:

`db_conn.query_all_worker_tax(company_code, year, quarter)`

This reads the latest quarterly tax snapshot and returns:

- worker key
- jurisdiction
- tax type
- filing status and allowances
- QTD/YTD amounts
- taxable/subject/gross wages
- tax rate and hours
- out-of-state wage values
- employer/employee tax flag

### 7. Format Tax GSI Fields

`format_tax_data_df()` formats tax fields into jurisdiction-level lines.

Tax mappings come from `TAX_MAPPINGS`.

Examples:

| Tax Type | Field | GSI Code |
|----------|-------|----------|
| FIT | `qtd_amount` | `EJ` |
| FIT | `ytd_amount` | `EK` |
| SIT | `qtd_gross_wages` | `MV` |
| SIT | `ytd_gross_wages` | `NT` |

Tax lines start with:

`******` + jurisdiction code

Examples from the screenshot:

- `******F`
- `******AL`
- `******CA`
- `******DE`
- `******IL`

### 8. Combine Lines

The job combines:

1. File header
2. Company header
3. Employee lines
4. Tax lines
5. Trailer

The trailer starts with:

`999999999999`

and includes the output line count.

### 9. Write Output

`S3Writer.write_gsi_dataframe()` writes the final Spark DataFrame as text.

Despite the class name, the configured output path is a Databricks Volume path, which maps to object storage behind the scenes.

### 10. Update Status and Notify

On success:

- `outbound_file.status` is set to `GENERATED`
- `s3_key`, record count, file name, and timestamps are updated
- success email is sent

On failure:

- `outbound_file.status` is set to `FAILED`
- failure email is sent

## Important Supporting Files

| File | Role |
|------|------|
| `db_connection.py` | Redshift/PostgreSQL reads and outbound-file writes. |
| `gsi_mappings.py` | GSI field mappings, tax mappings, GI1/GI2 metadata loading. |
| `gsi_formatter.py` | Worker and tax GSI formatting. |
| `mandatory_fields_validator.py` | Ensures mandatory tax fields exist for workers. |
| `s3_writer.py` | Header/trailer generation and text output writing. |
| `logger.py` | Console and Splunk logging. |
| `email_notifier.py` | Success/failure email notifications. |
| `orchestrator.py` | Parallel site processing. |

## Where The New Design Task Will Fit

The upcoming error-based exclusion design likely belongs between these stages:

1. After site/company context is known.
2. Before or during worker GSI mapping.
3. Before or during tax GSI mapping.
4. Before final line combination and write.

The likely new module would be:

`src/wd/qtr/gsi_builder/error_handler.py`

It would probably:

- query `company_errors`
- join to `error_catalog`
- decide impacted scope
- return excluded worker/tax/reporting/non-reporting GSI codes
- pass exclusion rules into `apply_gsi_mappings()` and `format_tax_data_df()`
- update `company_errors.write_status`

The open design decision is the mapping from errors to skipped GSI codes. That mapping is not currently present in the code or reference docs.

