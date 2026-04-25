# GSI Error-Based Exclusion - Comprehensive Analysis Document

**Document Version:** 1.0  
**Date:** April 23, 2026  
**Status:** Analysis / Requirements Gathering  
**Jira Ticket:** FY26Q4-S2 OneTax Smart League  

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current Application Overview](#2-current-application-overview)
3. [Problem Statement](#3-problem-statement)
4. [Current End-to-End Flow](#4-current-end-to-end-flow)
5. [Database Schema Analysis](#5-database-schema-analysis)
6. [Current Data Analysis](#6-current-data-analysis)
7. [Open Questions for Team Discussion](#7-open-questions-for-team-discussion)
8. [Dependencies and Unknowns](#8-dependencies-and-unknowns)
9. [Derived Requirements](#9-derived-requirements)
10. [Next Steps](#10-next-steps)

---

## 1. Executive Summary

### Jira Ticket Summary

**Story:** Update the Databricks job logic to skip worker or tax GSI codes in the GSI file when there are errors that have impact at MF (Mainframe) side or Agency side.

**Acceptance Criteria:**
- Create a generic design to add or remove worker, tax, reporting, and non-reporting GSI codes based on errors

### Current Status

- The codebase currently generates GSI files without any error-based exclusion logic
- Two database tables exist for error management: `onetax.error_catalog` (configuration) and `onetax.company_errors` (runtime)
- There are currently **5 open errors** in `company_errors` with `write_status = 'PENDING'`
- The exact mapping between errors and GSI codes to skip is **NOT DEFINED** in any available documentation

---

## 2. Current Application Overview

### 2.1 Application Purpose

The `wd-qtr-gsi-builder` is a PySpark application that:
- Runs as a Databricks `python_wheel_task`
- Processes quarterly worker and tax data from Redshift
- Generates GSI (General System Interface) files for tax reporting
- Writes output files to Databricks Volumes
- Updates status in `outbound_file` table

### 2.2 Key Source Files

| File | Purpose |
|------|---------|
| `main.py` | Main entry point, orchestrates processing |
| `gsi_formatter.py` | Formats worker and tax data into GSI line format |
| `gsi_mappings.py` | Contains GSI code definitions and field mappings |
| `db_connection.py` | Database connectivity (Redshift, PostgreSQL) |
| `s3_writer.py` | Writes output files to Databricks Volumes |

### 2.3 How GSI Codes Are Currently Generated

#### Worker Section (Employee-Level GSI Codes)

1. **Source:** `gsi_mappings.py` defines `GSI_MAPPINGS` dictionary
2. **Mapping:** Database field -> GSI code (2-character)
3. **Examples:**
   - `given_name` -> `CS`
   - `family_name` -> `CU`
   - `ssn` -> `DD`
   - `birth_date` -> `SY`

4. **Process:** `apply_gsi_mappings()` in `gsi_formatter.py`:
   - Takes worker DataFrame
   - Applies formatting based on field type (text/number/date/decimal)
   - Prepends GSI code to each formatted value
   - Builds lines with 160-character limit

#### Tax Section (Tax-Level GSI Codes)

1. **Source:** `gsi_mappings.py` defines `TAX_MAPPINGS` dictionary
2. **Organization:** Mapped by tax type (FIT, SIT, SDI, SUI, CIT, etc.)
3. **Examples:**
   - FIT qtd_amount -> `EJ`
   - FIT ytd_amount -> `EK`
   - SIT qtd_gross_wages -> `MV`
   - SDI exempt flag -> `EB`

4. **Process:** `format_tax_data_df()` in `gsi_formatter.py`:
   - Takes tax DataFrame
   - Looks up GSI code based on tax_type
   - Formats amounts with sign indicator
   - Builds tax lines per jurisdiction

#### GSI Level Classification

The code classifies GSI codes into levels:
- **EE (Employee):** Worker header section
- **F (Federal):** Federal tax jurisdiction
- **S (State):** State tax jurisdiction
- **L (Local):** Local tax jurisdiction

---

## 3. Problem Statement

### 3.1 The Issue

Currently, the GSI file generation process does **NOT** check for errors before generating GSI codes. When errors exist that would impact the Mainframe (MF) or Agency systems, the GSI codes are still generated and included in the output file.

### 3.2 Why This Is a Problem

1. **Data Quality:** Incorrect or incomplete data may be transmitted
2. **Downstream Impact:** MF and Agency systems may receive invalid data
3. **Compliance Risk:** Tax filings may be incorrect

### 3.3 What the Ticket Requests

> "Update the Databricks job logic to skip the worker or tax GSI codes to add in the GSI file, when there are errors that has impact at MF side or at Agency side."

### 3.4 What Is Missing

The ticket does **NOT** specify:
1. Which specific errors should trigger skipping
2. What exactly should be skipped (entire worker, specific GSI codes, entire jurisdiction, etc.)
3. The mapping between error types and GSI codes
4. Whether to skip only when `impacts_deposit = true`, `impacts_filing = true`, or both

---

## 4. Current End-to-End Flow

### 4.1 High-Level Flow Diagram

```text
+---------------------------------------------------------------------+
|                         CURRENT FLOW                                |
|                    (No Error Checking)                              |
+---------------------------------------------------------------------+

1. STARTUP
   |
   +-- Load configuration (config/loader.py)
   +-- Initialize Spark session
   +-- Connect to Redshift (db_connection.py)
   +-- Connect to PostgreSQL for GI1 mappings (optional)
   +-- Initialize S3Writer, EmailNotifier

2. PROCESS QUEUED FILES (main.py: process_queued_files)
   |
   +-- Query outbound_file WHERE status = 'QUEUED'
   +-- Load GSI_MAPPINGS and ADDRESS_MAPPINGS (from PostgreSQL GI1 table)
   +-- Process in chunks of 10 (parallel threads)

3. FOR EACH SITE (main.py: process_site_event)
   |
   +-- Update status to 'GENERATING'
   +-- Get all companies for site
   |
   +-- FOR EACH COMPANY:
       |
       +-- Query worker data (db_connection.py: query_workers)
       |   +-- Returns: worker_sk, name, SSN, dates, addresses, flags
       |
       +-- Apply GSI mappings (gsi_formatter.py: apply_gsi_mappings)
       |   +-- Format each field based on type
       |   +-- Prepend GSI code to value
       |   +-- Build employee lines (160-char limit)
       |
       +-- Query tax data (db_connection.py: query_all_worker_tax)
       |   +-- Returns: jurisdiction, amounts, rates, profiles
       |
       +-- Format tax data (gsi_formatter.py: format_tax_data_df)
       |   +-- Map tax_type to GSI code
       |   +-- Format amounts with sign
       |   +-- Build tax lines per jurisdiction
       |
       +-- Combine worker + tax lines

4. WRITE OUTPUT
   |
   +-- Add file header
   +-- Add branch/company headers
   +-- Write combined lines
   +-- Add trailer record with line count
   +-- Write to Databricks Volumes

5. UPDATE STATUS
   |
   +-- Update outbound_file to 'GENERATED' or 'FAILED'
   +-- Send email notification
```

### 4.2 What's Missing in Current Flow

```text
+---------------------------------------------------------------------+
|                         MISSING STEPS                               |
|              (Need to be added for error handling)                  |
+---------------------------------------------------------------------+

? Query company_errors for organization_unit_sk
? Check if any errors have impacts_deposit = true or impacts_filing = true
? Determine which GSI codes should be excluded
? Filter GSI codes before writing to output
? Update write_status in company_errors after processing
```

---

## 5. Database Schema Analysis

### 5.1 onetax.error_catalog (Configuration Table)

**Purpose:** Defines all possible error types and their characteristics

| Column | Type | Description | Sample Values |
|--------|------|-------------|---------------|
| `error_code` | varchar | Primary key | FEIN_IS_MISSING, CA_WAGE_PLAN_MISSING |
| `legacy_error_code` | varchar | Legacy code | E02, 57, E01 |
| `name` | varchar | Human-readable name | "FEIN is missing" |
| `error_type` | varchar | Category | TAX_ID, CA_WAGE_PLAN, SSN |
| `category` | varchar | Classification | Registration, WagePlan, Validation |
| `impacts_deposit` | boolean | **MF impact flag** | true/false |
| `impacts_filing` | boolean | **Agency impact flag** | true/false |
| `created_date_time` | timestamp | Creation time | - |
| `updated_date_time` | timestamp | Last update | - |
| `effective_from` | date | When rule became effective | 2026-01-01 |

**Record Count:** 91 records

### 5.2 onetax.company_errors (Runtime Table)

**Purpose:** Tracks actual errors detected for each company/payroll

| Column | Type | Description | Sample Values |
|--------|------|-------------|---------------|
| `company_error_sk` | bigint | Primary key | 1, 2, 3, 4, 5 |
| `organization_unit_sk` | bigint | FK to organization_unit | 227, 229, 273 |
| `payroll_run_sk` | bigint | FK to payroll run | 95, 97, 99, 101 |
| `error_code` | varchar | FK to error_catalog | FEIN_IS_MISSING, FEIN_NOT_CORRECT |
| `impacted_count` | integer | Workers affected | 1, 25, 35 |
| `resolution_status` | varchar | Current status | Open, Resolved |
| `write_status` | varchar | GSI write status | PENDING, WRITTEN, SKIPPED |
| `state_code` | varchar | State (if applicable) | NULL, CA, NY |
| `local_code` | varchar | Local (if applicable) | NULL |
| `tax_type` | varchar | Tax type (if applicable) | NULL |
| `created_date_time` | timestamp | When error detected | 2026-03-13 |
| `resolved_date_time` | timestamp | When resolved | NULL |

**Current Record Count:** 5 records (all Open, all PENDING)

---

## 6. Current Data Analysis

### 6.1 Error Catalog Sample (with Impact Flags)

Based on query results provided:

| error_code | legacy_error_code | name | error_type | category | impacts_deposit | impacts_filing |
|------------|-------------------|------|------------|----------|-----------------|----------------|
| CA_WAGE_PLAN_MISSING | E01 | California wage plan code is missing | CA_WAGE_PLAN | WagePlan | **false** | **true** |
| E001 | 01 | CA wage plan missing | CAWagePlan | WagePlan | **true** | **true** |
| E002 | 02 | SSN invalid | SSN | Validation | **false** | **true** |
| FEIN_IS_MISSING | E02 | FEIN is missing | TAX_ID | Registration | **false** | **true** |

### 6.2 Current company_errors (Open Errors)

| error_code | legacy_error_code | name | impacts_deposit | impacts_filing | resolution_status | write_status |
|------------|-------------------|------|-----------------|----------------|-------------------|--------------|
| FEIN_IS_MISSING | E02 | FEIN is missing | **false** | **true** | Open | PENDING |
| FEIN_IS_MISSING | E02 | FEIN is missing | **false** | **true** | Open | PENDING |
| FEIN_NOT_CORRECT | 57 | FEIN is incorrect | **false** | **false** | Open | PENDING |
| FEIN_NOT_CORRECT | 57 | FEIN is incorrect | **false** | **false** | Open | PENDING |
| FEIN_IS_MISSING | E02 | FEIN is missing | **false** | **true** | Open | PENDING |

### 6.3 Key Observations

1. **FEIN_IS_MISSING** (3 records):
   - `impacts_deposit = false`
   - `impacts_filing = true` <- **This should trigger some action based on ticket**

2. **FEIN_NOT_CORRECT** (2 records):
   - `impacts_deposit = false`
   - `impacts_filing = false` <- **No impact flags, should this be skipped?**

3. **Unknown:** What GSI codes relate to FEIN errors? The data does not specify.

---

## 7. Open Questions for Team Discussion

### 7.1 Business Logic Questions

| # | Question | Why It Matters | Possible Answers |
|---|----------|----------------|------------------|
| 1 | When `impacts_filing = true`, what exactly should be skipped? | Core logic requirement | Skip worker section? Skip tax section? Skip specific codes? Skip entire company? |
| 2 | When `impacts_deposit = true`, what exactly should be skipped? | Core logic requirement | Same options as above |
| 3 | If both flags are false (like FEIN_NOT_CORRECT), should any GSI codes be skipped? | Determines scope | Yes/No |
| 4 | Is there a mapping document that defines error_type -> GSI codes? | Without this, we cannot implement | Need document or database table |
| 5 | Should errors at organization_unit level affect all workers or specific workers? | Determines granularity | All workers / Affected workers only |

### 7.2 Technical Questions

| # | Question | Why It Matters | Possible Answers |
|---|----------|----------------|------------------|
| 6 | Where should the error check happen in the flow? | Architecture decision | Before worker query? Before GSI mapping? Before write? |
| 7 | Should we update `write_status` in company_errors after processing? | Data consistency | Yes - to 'WRITTEN' or 'SKIPPED' |
| 8 | Should the error catalog be queried from Redshift or PostgreSQL? | The tables exist in onetax schema | Verify which database |
| 9 | How do we join company_errors to the current processing context? | Need FK relationship | organization_unit_sk, payroll_run_sk |
| 10 | What should happen to the GSI file if errors exist but no exclusion rules are defined? | Edge case handling | Generate anyway? Fail? Log warning? |

### 7.3 PDF Document Questions

The "Quarter and Periodic Errors" PDF shows error definitions but does NOT specify:

| # | Question | Reference |
|---|----------|-----------|
| 11 | Do the legacy_error_codes (56, 59, 922-929, etc.) in PDF match the error_catalog? | PDF shows codes like 056, 059, 922-929 but error_catalog shows E01, E02, 57 |
| 12 | Does the PDF's "Profile Error" vs "Non Profile" category determine what to skip? | PDF shows Category column |
| 13 | Is the "Business Unit" (Majors, Nationals, Employment Tax) relevant for exclusion logic? | PDF shows this column |

---

## 8. Dependencies and Unknowns

### 8.1 Missing Information

| Item | Status | Needed From |
|------|--------|-------------|
| Error-to-GSI code mapping | ? NOT AVAILABLE | Business/Product team |
| Complete error_catalog dump | ? PARTIAL (4 records seen) | Database query |
| Definition of "reporting" vs "non-reporting" GSI codes | ? NOT DEFINED | Business/Product team |
| Test data with various error scenarios | ? NOT AVAILABLE | QA/Test team |

### 8.2 Assumptions That MUST Be Validated

**Note:** These are NOT assumptions being made, but items that NEED clarification:

| Item | Current Understanding | Needs Validation |
|------|----------------------|------------------|
| Error tables are in Redshift (not PostgreSQL) | Tables shown as `onetax.*` | Confirm database |
| `impacts_filing` = Agency impact | Based on ticket description | Confirm with business |
| `impacts_deposit` = MF impact | Based on ticket description | Confirm with business |
| Only `resolution_status = 'Open'` errors should trigger exclusion | Logical assumption | Confirm with business |
| Only `write_status = 'PENDING'` errors should be processed | Logical assumption | Confirm with business |

### 8.3 External Dependencies

| Dependency | Description | Impact |
|------------|-------------|--------|
| PDF document accuracy | "Quarter and Periodic Errors" PDF may be outdated | Mapping might be incorrect |
| Database schema stability | error_catalog/company_errors schema | Code changes if schema changes |
| Downstream systems (MF, Agency) | Must match expected format | Validation required |

---

## 9. Derived Requirements

### 9.1 Confirmed Requirements (from Jira Ticket)

| ID | Requirement | Source |
|----|-------------|--------|
| REQ-01 | System must be able to skip worker GSI codes based on errors | Jira AC |
| REQ-02 | System must be able to skip tax GSI codes based on errors | Jira AC |
| REQ-03 | Skip logic should apply when errors impact MF side | Jira AC |
| REQ-04 | Skip logic should apply when errors impact Agency side | Jira AC |
| REQ-05 | Design should be generic (not hardcoded for specific errors) | Jira AC |

### 9.2 Inferred Requirements (Need Validation)

| ID | Requirement | Inference Source | Status |
|----|-------------|------------------|--------|
| REQ-06 | Query company_errors before generating GSI file | Logical | ? Validate |
| REQ-07 | Use `impacts_deposit` flag for MF impact | Database schema | ? Validate |
| REQ-08 | Use `impacts_filing` flag for Agency impact | Database schema | ? Validate |
| REQ-09 | Update `write_status` after processing | Database has this field | ? Validate |
| REQ-10 | Only process errors with `resolution_status = 'Open'` | Logical | ? Validate |

### 9.3 Requirements Gaps

| Gap | Description | Action Needed |
|-----|-------------|---------------|
| GAP-01 | No mapping between error_type and GSI codes | Need business input |
| GAP-02 | No definition of what "skip" means per error type | Need business input |
| GAP-03 | No clarity on granularity (company vs worker level) | Need business input |
| GAP-04 | No test scenarios defined | Need QA input |

---

## 10. Next Steps

### 10.1 Immediate Actions

| # | Action | Owner | Priority |
|---|--------|-------|----------|
| 1 | Schedule meeting with business team to answer questions in Section 7 | Developer | High |
| 2 | Run query to get complete error_catalog dump with all 91 records | Developer | High |
| 3 | Validate PDF document against actual database data | Developer | Medium |
| 4 | Confirm database location (Redshift vs PostgreSQL) for error tables | Developer | High |

### 10.2 After Requirements Clarification

| # | Action | Owner | Priority |
|---|--------|-------|----------|
| 5 | Create error_handler.py module with exclusion logic | Developer | High |
| 6 | Modify main.py to integrate error checking | Developer | High |
| 7 | Modify gsi_formatter.py to accept exclusion parameters | Developer | High |
| 8 | Create unit tests for error handling | Developer | Medium |
| 9 | Create integration tests with sample error data | Developer | Medium |

### 10.3 SQL Queries to Run

**Query 1: Get complete error_catalog**

```sql
SELECT * FROM onetax.error_catalog ORDER BY error_code;
```

**Query 2: Get all errors with impact flags = true**

```sql
SELECT error_code, legacy_error_code, name, error_type, category,
       impacts_deposit, impacts_filing
FROM onetax.error_catalog
WHERE impacts_deposit = true OR impacts_filing = true
ORDER BY error_code;
```

**Query 3: Get current open errors with join**

```sql
SELECT ce.*, ec.impacts_deposit, ec.impacts_filing, ec.error_type, ec.category
FROM onetax.company_errors ce
JOIN onetax.error_catalog ec ON ce.error_code = ec.error_code
WHERE ce.resolution_status = 'Open'
ORDER BY ce.created_date_time;
```

---

## Appendix A: File References

| File | Path | Purpose |
|------|------|---------|
| Main entry | `src/wd/qtr/gsi_builder/main.py` | Orchestration |
| GSI Formatter | `src/wd/qtr/gsi_builder/gsi_formatter.py` | Format GSI lines |
| GSI Mappings | `src/wd/qtr/gsi_builder/gsi_mappings.py` | Code definitions |
| DB Connection | `src/wd/qtr/gsi_builder/db_connection.py` | Database access |
| PDF Document | `docs/Quarter and Periodic Errors_*.pdf` | Error definitions |

## Appendix B: GSI Code Examples

### Worker-Level Codes (EE)

| GSI Code | Field | Description |
|----------|-------|-------------|
| CS | given_name | First name |
| CU | family_name | Last name |
| DD | ssn | Social Security Number |
| SY | birth_date | Date of birth |
| NZ | hire_date | Hire date |

### Tax-Level Codes

| GSI Code | Tax Type | Field | Description |
|----------|----------|-------|-------------|
| EJ | FIT | qtd_amount | Federal income tax QTD |
| EK | FIT | ytd_amount | Federal income tax YTD |
| MV | SIT | qtd_gross_wages | State income tax QTD gross |
| NT | SIT | ytd_gross_wages | State income tax YTD gross |

---

**Document End**

*This document is based solely on the data and files provided. No assumptions have been made. Items requiring clarification are explicitly marked.*
