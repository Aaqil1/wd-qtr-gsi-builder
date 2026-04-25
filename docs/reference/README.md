# Reference Documents

These files are source/reference material for the GSI builder and error-based exclusion analysis. They are not read by the Databricks job at runtime.

| File | Purpose |
|------|---------|
| `ASCII_EBCDIC_Rules.xlsx` | ASCII/EBCDIC character mapping and allowed-character reference for Mainframe-facing validation. |
| `GPTAnalysisWorkerDetails.xlsx` | Worker validation rules for name, address, SSN, tax class, and generalized validations. |
| `GSI_GE59_Q1_2026_20260425_110358.txt` | COBOL-style tax validation notes with GSI code references such as `EJ`, `IC`, `ZE`, `ZF`, `FP/6B`, and `IA/7A`. |
| `sample-periodic-tax-deposit-event.redacted.json` | Sanitized upstream `PeriodicTaxDeposit` event sample. The raw source was not committed because it contained sensitive-looking identifiers. |
| `sample-event-and-gsi-output-notes.md` | Notes connecting the redacted JSON sample and the GSI output screenshot to the project flow. |

Use these documents when designing or validating future error-based GSI exclusion logic.
