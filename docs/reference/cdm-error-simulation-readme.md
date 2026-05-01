# CDM Error Catalog Simulation Seed

This folder contains a synthetic CDM-style test seed generated from the error catalog rows pasted in chat on 2026-05-01.

## Files

| File | Purpose |
|---|---|
| `cdm-error-catalog-simulation-seed.json` | Synthetic `PeriodicTaxDeposit` CDM payload with one organization unit / worker scenario per unique error code. |
| `error-catalog-simulation-map.csv` | Sidecar map showing which worker/company is intended to simulate each unique error. |
| `cdm-error-catalog-simulation-seed-raw103.json` | Synthetic CDM payload with 103 scenarios, including duplicate rows from the pasted catalog export. |
| `error-catalog-simulation-map-raw103.csv` | Sidecar map for the 103-row raw fixture. |

## Coverage

- Unique error scenarios represented: **81**
- Raw pasted catalog rows represented in the `raw103` fixture: **103**
- Source note: the pasted catalog had duplicate rows for several error codes. Use the 81-scenario file for unique error-code coverage and the raw103 file when you need one scenario per pasted row.

## Category Counts

- `COMPANY`: 18
- `EMPLOYEE`: 1
- `PAYROLL`: 45
- `Registration`: 1
- `Validation`: 1
- `WORKER_PROFILE`: 11
- `WagePlan`: 4

## Important Limitations

This is a **simulation seed**, not a certified validation fixture.

The error catalog tells us the error name, category, type, severity, and impact flags. It does not always tell us the exact CDM source field that triggers the validator. For that reason:

- Direct worker profile errors like SSN patterns are represented with direct bad SSN values.
- Company-level examples like missing/invalid FEIN and pay frequency are represented with direct company/profile mutations.
- Many tax, jurisdiction, PFML, service-level, and state-specific scenarios are best-effort and marked in the CSV as needing validation-rule confirmation.
- The sidecar CSV is the source of truth for which worker/company is intended to trigger which catalog error.

## Recommended Use

1. Review `error-catalog-simulation-map.csv` with the validation owner.
2. Confirm or adjust the `mutation_summary` for each scenario.
3. Run the CDM through the upstream validation pipeline.
4. Compare generated validation errors to `error_code` in the CSV.
5. Iterate until each error is reproducible.

Do not use this fixture as production input.
