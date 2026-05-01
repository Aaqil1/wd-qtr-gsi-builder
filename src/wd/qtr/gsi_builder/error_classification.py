"""Classification helpers for payroll errors.

This module intentionally classifies errors for Quarter vs Periodic handling.
It does not suppress GSI output. Output blocking/skipping should be added only
after the business confirms category-to-action rules.
"""

from dataclasses import dataclass
from enum import Enum
import re
from typing import Optional


class ProcessingArea(str, Enum):
    """High-level processing bucket used by the current meeting decision."""

    QUARTER = "QUARTER"
    PERIODIC = "PERIODIC"
    UNKNOWN = "UNKNOWN"


class PresentationScope(str, Enum):
    """Where the error should be presented to users."""

    COMPANY = "COMPANY"
    WORKER = "WORKER"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ErrorClassification:
    """Resolved category classification for one catalog error."""

    original_category: Optional[str]
    normalized_category: str
    processing_area: ProcessingArea
    presentation_scope: PresentationScope
    rationale: str

    @property
    def is_classified(self) -> bool:
        return self.processing_area != ProcessingArea.UNKNOWN


def normalize_error_category(category: Optional[str]) -> str:
    """Normalize category text from the catalog into stable comparison keys."""
    if category is None:
        return "UNKNOWN"

    value = str(category).strip().upper()
    if not value:
        return "UNKNOWN"

    value = value.replace("&", " AND ")
    value = re.sub(r"[^A-Z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "UNKNOWN"


def classify_error_category(category: Optional[str]) -> ErrorClassification:
    """Classify an error category using the current temporary meeting rule.

    Current agreed working rule:
    - Company -> Periodic/payment-related
    - Worker Profile -> Quarter/filing-related
    - Payroll & Tax -> Quarter/filing-related

    Values outside that rule are deliberately returned as UNKNOWN so they can
    be reviewed instead of silently guessed.
    """
    normalized = normalize_error_category(category)

    if normalized == "COMPANY":
        return ErrorClassification(
            original_category=category,
            normalized_category=normalized,
            processing_area=ProcessingArea.PERIODIC,
            presentation_scope=PresentationScope.COMPANY,
            rationale="Meeting rule: Company category is treated as Periodic/payment-related.",
        )

    if normalized == "WORKER_PROFILE":
        return ErrorClassification(
            original_category=category,
            normalized_category=normalized,
            processing_area=ProcessingArea.QUARTER,
            presentation_scope=PresentationScope.WORKER,
            rationale="Meeting rule: Worker Profile category is treated as Quarter/filing-related.",
        )

    if normalized in {"PAYROLL", "PAYROLL_AND_TAX", "PAYROLL_TAX"}:
        return ErrorClassification(
            original_category=category,
            normalized_category=normalized,
            processing_area=ProcessingArea.QUARTER,
            presentation_scope=PresentationScope.WORKER,
            rationale="Meeting rule: Payroll & Tax category is treated as Quarter/filing-related.",
        )

    return ErrorClassification(
        original_category=category,
        normalized_category=normalized,
        processing_area=ProcessingArea.UNKNOWN,
        presentation_scope=PresentationScope.UNKNOWN,
        rationale="No confirmed meeting rule exists for this category.",
    )


def normalize_impact_flag(value) -> bool:
    """Normalize boolean-like database values without deciding business action."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "t", "1", "y", "yes"}
