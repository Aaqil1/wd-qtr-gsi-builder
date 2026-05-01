from wd.qtr.gsi_builder.error_classification import (
    PresentationScope,
    ProcessingArea,
    classify_error_category,
    normalize_error_category,
    normalize_impact_flag,
)


def test_company_category_is_periodic():
    result = classify_error_category("Company")

    assert result.normalized_category == "COMPANY"
    assert result.processing_area == ProcessingArea.PERIODIC
    assert result.presentation_scope == PresentationScope.COMPANY


def test_worker_profile_category_is_quarter():
    result = classify_error_category("WORKER_PROFILE")

    assert result.normalized_category == "WORKER_PROFILE"
    assert result.processing_area == ProcessingArea.QUARTER
    assert result.presentation_scope == PresentationScope.WORKER


def test_payroll_and_tax_category_is_quarter():
    result = classify_error_category("Payroll & Tax")

    assert result.normalized_category == "PAYROLL_AND_TAX"
    assert result.processing_area == ProcessingArea.QUARTER
    assert result.presentation_scope == PresentationScope.WORKER


def test_payroll_catalog_category_is_quarter_alias():
    result = classify_error_category("PAYROLL")

    assert result.normalized_category == "PAYROLL"
    assert result.processing_area == ProcessingArea.QUARTER
    assert result.presentation_scope == PresentationScope.WORKER


def test_unknown_category_stays_unknown():
    result = classify_error_category("WagePlan")

    assert result.normalized_category == "WAGEPLAN"
    assert result.processing_area == ProcessingArea.UNKNOWN
    assert result.presentation_scope == PresentationScope.UNKNOWN
    assert not result.is_classified


def test_category_normalization_handles_spacing_and_symbols():
    assert normalize_error_category(" payroll  &   tax ") == "PAYROLL_AND_TAX"
    assert normalize_error_category(None) == "UNKNOWN"
    assert normalize_error_category("") == "UNKNOWN"


def test_impact_flag_normalization():
    assert normalize_impact_flag(True)
    assert normalize_impact_flag("Y")
    assert normalize_impact_flag("true")
    assert normalize_impact_flag("1")
    assert not normalize_impact_flag(False)
    assert not normalize_impact_flag("N")
    assert not normalize_impact_flag(None)
