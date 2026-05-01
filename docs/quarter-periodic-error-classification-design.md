# Quarter vs Periodic Error Classification Design

## Why This Replaces The Previous Skip-Only Change

The previous implementation skipped companies or workers from GSI output when `error_catalog.impacts_filing` was true.

After the meeting, that is too early and too narrow. The team discussion was not only about blocking GSI output. The confirmed near-term need is to classify payroll errors so users can understand:

- which errors affect **payments / periodic processing**
- which errors affect **filing / quarter processing**

So the design has been reset around classification first. GSI skipping should be added later only when the exact blocking behavior is confirmed.

## Confirmed Meeting Rule

For the current testing phase, use this simple category-based rule:

| Error catalog category | Treat as | User meaning |
|---|---|---|
| `Company` | `PERIODIC` | Payment-related / periodic issue |
| `Worker Profile` | `QUARTER` | Filing/reporting-related quarter issue |
| `Payroll & Tax` | `QUARTER` | Filing/reporting-related quarter issue |

This is a working rule for testing. It is not the final business taxonomy.

## Important Design Decision

Do not use only one field as the final truth.

The meeting made it clear that one label like `category` cannot fully explain an error because every error has multiple dimensions:

| Dimension | Meaning |
|---|---|
| Origin | Where the bad setup or data came from |
| Presentation scope | Where the user sees the error, such as company or worker |
| Processing impact | Whether it affects periodic payment or quarter filing |
| Blocking behavior | Whether it should eventually stop output |

The current implementation only handles the **processing impact classification**.

## Current Code Direction

The new code foundation is:

| File | Purpose |
|---|---|
| `src/wd/qtr/gsi_builder/error_classification.py` | Classifies catalog categories into `QUARTER`, `PERIODIC`, or `UNKNOWN` |
| `tests/test_error_classification.py` | Verifies the meeting category rules |

This classifier does **not** remove rows from the GSI file.

That is intentional. The meeting summary says the classification is temporary and should be validated with real test data before making stronger behavior changes.

## What Was Removed

The active skip behavior from the earlier change is removed:

- no company is skipped only because `impacts_filing = true`
- no worker is skipped only because `impacts_filing = true`
- no GSI output is filtered by the new classifier yet

This restores the GSI generation flow while keeping a clean foundation for the new meeting-based design.

## How The Classifier Works

The classifier takes the `error_catalog.category` value and normalizes it.

Examples:

| Raw category value | Normalized value | Result |
|---|---|---|
| `Company` | `COMPANY` | `PERIODIC` |
| `WORKER_PROFILE` | `WORKER_PROFILE` | `QUARTER` |
| `Payroll & Tax` | `PAYROLL_AND_TAX` | `QUARTER` |
| `PAYROLL` | `PAYROLL` | `QUARTER` |
| `WagePlan` | `WAGEPLAN` | `UNKNOWN` |
| `Registration` | `REGISTRATION` | `UNKNOWN` |
| `Validation` | `VALIDATION` | `UNKNOWN` |

Unknown categories are not guessed. They stay `UNKNOWN` so the team can review them during testing.

## How Impact Flags Should Be Used

The catalog has:

- `impacts_deposit`
- `impacts_filing`

The new classifier includes a small normalizer for these values, but it does not decide blocking behavior from them yet.

Current safe interpretation:

| Flag | Meaning |
|---|---|
| `impacts_deposit = true` | the error may matter to payment / periodic behavior |
| `impacts_filing = true` | the error may matter to filing / quarter behavior |
| both false | the error is currently not a blocker by flags alone |

The project should not permanently hardcode "both true" or "either true" until the team confirms the exact blocking policy.

## Recommended Final Architecture

Use a two-step model.

### Step 1: Classify

Read error catalog data and classify each error into:

| Output | Example |
|---|---|
| processing area | `PERIODIC`, `QUARTER`, `UNKNOWN` |
| presentation scope | `COMPANY`, `WORKER`, `UNKNOWN` |
| impact flags | filing/deposit booleans |

### Step 2: Decide Action

Only after testing confirms the behavior, map classifications to actions.

Possible future actions:

| Action | Meaning |
|---|---|
| `SHOW_ONLY` | show the error to users but do not block GSI |
| `BLOCK_PERIODIC` | block payment/periodic flow |
| `BLOCK_QUARTER` | block quarter filing/reporting flow |
| `SKIP_COMPANY` | remove entire company from GSI |
| `SKIP_WORKER` | remove one worker from GSI |
| `SKIP_JURISDICTION` | remove a tax jurisdiction only |
| `SKIP_GSI_CODE` | remove a specific GSI field only |

This keeps the project flexible because classification and blocking are not mixed together.

## Practical Examples

### Company Error

Input:

| error_code | category |
|---|---|
| `FEIN_NOT_CORRECT` | `Company` |

Classification:

| processing area | presentation scope |
|---|---|
| `PERIODIC` | `COMPANY` |

Meaning:

The error is payment/periodic-related for the current testing approach. It should be shown as a company/payment issue. It should not automatically skip GSI output until blocking policy is confirmed.

### Worker Profile Error

Input:

| error_code | category |
|---|---|
| `SSN_NON_NUM` | `WORKER_PROFILE` |

Classification:

| processing area | presentation scope |
|---|---|
| `QUARTER` | `WORKER` |

Meaning:

The error is quarter/filing-related and should be shown at worker level.

### Payroll And Tax Error

Input:

| error_code | category |
|---|---|
| `YD_FIT_TAX_MIS` | `PAYROLL` |

Classification:

| processing area | presentation scope |
|---|---|
| `QUARTER` | `WORKER` |

Meaning:

The error is treated as quarter-related for testing. The `PAYROLL` catalog value is treated as the available data equivalent of the meeting term "Payroll & Tax".

## What Still Needs Confirmation Before GSI Skipping

Before adding skip behavior again, the team must confirm:

| Question | Why it matters |
|---|---|
| Should `impacts_filing = true` block quarter output, or only classify it? | Prevents accidental file suppression |
| Should `impacts_deposit = true` block periodic output only, or also GSI output? | Deposit and GSI are not necessarily the same operation |
| Should `Company` always block the whole company? | Some company-origin errors may appear at worker level |
| Should `Payroll & Tax` always affect the worker, or sometimes only a jurisdiction? | Needed for future jurisdiction-level behavior |
| What should happen to `WagePlan`, `Registration`, and `Validation` categories? | These exist in the catalog but were not part of the confirmed temporary rule |

## Recommended Next Step

Use the classifier in read-only/logging mode first:

1. read real `error_catalog` and runtime error rows
2. classify each row as `QUARTER`, `PERIODIC`, or `UNKNOWN`
3. compare the classification with real expected user behavior
4. only then add action rules for blocking or GSI skipping

This matches the meeting direction: move quickly with a simple category rule, validate with real data, and avoid overbuilding before the edge cases are understood.
