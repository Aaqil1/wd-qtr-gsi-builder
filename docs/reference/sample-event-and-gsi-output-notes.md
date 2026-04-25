# Sample Event and GSI Output Notes

## Source Event

`sample-periodic-tax-deposit-event.redacted.json` is a sanitized example of the upstream JSON payload received for a `PeriodicTaxDeposit` event.

Important sections:

| JSON Path | Meaning | Project Relevance |
|-----------|---------|-------------------|
| `applicationArea.event` | Event type, for example `PeriodicTaxDeposit` | Identifies the business process that eventually drives GSI generation. |
| `applicationArea.targetProducts` | Target product list | Helps determine whether this is Employment Tax periodic processing. |
| `organization.organizationUnit[]` | Company/site level data | Contains branch/company/site identifiers, tax period, addresses, FEIN, payroll runs, workers, and summaries. |
| `organization.organizationUnit[].payrollRun[]` | Payroll run context | Source context for worker/tax snapshots that the Databricks job later reads from Redshift. |
| `organization.organizationUnit[].worker[]` | Worker data | Source-domain equivalent of worker fields formatted into employee-level GSI codes. |
| `workerTaxSummary[]` | Tax/jurisdiction summaries | Source-domain equivalent of tax data formatted into federal/state/local GSI lines. |

The raw source file was not committed because it contained sensitive-looking identifiers such as SSN-like, FEIN-like, phone, UUID, and organization/worker values.

## GSI Output Screenshot

The screenshot shows the final text-file shape produced by the GSI builder:

1. File header line
   - Contains timestamp, hardcoded `WDQTRRECON`, year/quarter, and file type `Q`.

2. Company header line
   - Contains branch/company identifiers and a fixed organization header segment.

3. Employee lines
   - Start with `******      `.
   - Contain employee-level GSI codes such as name, SSN, dates, flags, and address values.

4. Tax lines
   - Start with `******` followed by a jurisdiction code such as `F`, `AL`, `CA`, `DE`, `IL`, etc.
   - Contain tax-level GSI codes and formatted signed/unsigned values.

5. Trailer line
   - Starts with `999999999999`.
   - Ends with the total output line count.

This is the output format produced by `S3Writer.generate_gsi_header()`, `process_site_event()`, `format_tax_data_df()`, and `S3Writer.generate_trailer_record()`.

## Relationship to Error-Based Exclusion

For the upcoming design task, the sample JSON helps explain the upstream source domain, while the screenshot shows the downstream file surface where codes may need to be excluded.

The design question is not simply "can we generate a GSI file?" The project already does that. The new design needs to decide where error records should alter this pipeline:

- before worker GSI fields are formatted
- before tax GSI fields are formatted
- before employee/tax lines are combined
- before the final output is written
- when `company_errors.write_status` should be updated

