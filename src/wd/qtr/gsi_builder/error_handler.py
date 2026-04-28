"""Error-driven skip decisions for quarter GSI generation."""

from dataclasses import dataclass, field
from typing import Set

try:
    from wd.qtr.gsi_builder.logger import Logger

    logger = Logger.get_logger(__name__)
except Exception:  # pragma: no cover - only used in lightweight local test envs
    import logging

    logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ErrorSkipDecision:
    """Resolved skip decision for one branch/company in a quarter run."""

    skip_company: bool = False
    worker_sks_to_skip: Set[str] = field(default_factory=set)
    company_error_count: int = 0
    worker_error_count: int = 0

    @property
    def has_skips(self) -> bool:
        return self.skip_company or bool(self.worker_sks_to_skip)


def resolve_error_skip_decision(db_conn, site_id, branch_code, company_code, year, quarter):
    """Resolve current filing-impact errors into company/worker skip decisions.

    This is intentionally fail-open: if error lookup fails, the current GSI
    generation path continues and logs the lookup failure.
    """
    company_error_count = 0
    worker_sks_to_skip = set()

    try:
        company_error_count = db_conn.query_company_filing_error_count(
            site_id, branch_code, company_code, year, quarter
        )
    except Exception as e:
        logger.warning(
            f"Company filing-error lookup failed for {site_id}/{branch_code}/{company_code}: {e}"
        )

    try:
        worker_sks_to_skip = {
            str(worker_sk)
            for worker_sk in db_conn.query_worker_filing_error_worker_sks(
                site_id, branch_code, company_code, year, quarter
            )
        }
    except Exception as e:
        logger.warning(
            f"Worker filing-error lookup failed for {site_id}/{branch_code}/{company_code}: {e}"
        )

    decision = ErrorSkipDecision(
        skip_company=company_error_count > 0,
        worker_sks_to_skip=worker_sks_to_skip,
        company_error_count=company_error_count,
        worker_error_count=len(worker_sks_to_skip),
    )

    if decision.skip_company:
        logger.info(
            f"Resolved filing-error skip: company {site_id}/{branch_code}/{company_code} "
            f"will be skipped because {company_error_count} company error(s) have impacts_filing=true"
        )
    elif decision.worker_sks_to_skip:
        logger.info(
            f"Resolved filing-error skip: {len(worker_sks_to_skip)} worker(s) will be skipped "
            f"for {site_id}/{branch_code}/{company_code}: {sorted(worker_sks_to_skip)}"
        )
    else:
        logger.info(
            f"No filing-impact company/worker errors found for {site_id}/{branch_code}/{company_code}"
        )

    return decision
