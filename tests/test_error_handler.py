from wd.qtr.gsi_builder.error_handler import resolve_error_skip_decision


class FakeDbConnection:
    def __init__(self, company_error_count=0, worker_sks=None, fail_company=False, fail_worker=False):
        self.company_error_count = company_error_count
        self.worker_sks = worker_sks or set()
        self.fail_company = fail_company
        self.fail_worker = fail_worker

    def query_company_filing_error_count(self, site_id, branch_code, company_code, year, quarter):
        if self.fail_company:
            raise RuntimeError("company lookup failed")
        return self.company_error_count

    def query_worker_filing_error_worker_sks(self, site_id, branch_code, company_code, year, quarter):
        if self.fail_worker:
            raise RuntimeError("worker lookup failed")
        return self.worker_sks


def test_company_filing_error_skips_company():
    decision = resolve_error_skip_decision(
        FakeDbConnection(company_error_count=2),
        "GE59",
        "ST",
        "GE59",
        2026,
        1,
    )

    assert decision.skip_company is True
    assert decision.company_error_count == 2
    assert decision.worker_sks_to_skip == set()
    assert decision.has_skips is True


def test_worker_filing_errors_skip_workers():
    decision = resolve_error_skip_decision(
        FakeDbConnection(worker_sks={361, "362"}),
        "GE59",
        "ST",
        "GE59",
        2026,
        1,
    )

    assert decision.skip_company is False
    assert decision.worker_sks_to_skip == {"361", "362"}
    assert decision.worker_error_count == 2
    assert decision.has_skips is True


def test_error_lookup_failures_are_fail_open():
    decision = resolve_error_skip_decision(
        FakeDbConnection(fail_company=True, fail_worker=True),
        "GE59",
        "ST",
        "GE59",
        2026,
        1,
    )

    assert decision.skip_company is False
    assert decision.worker_sks_to_skip == set()
    assert decision.company_error_count == 0
    assert decision.worker_error_count == 0
    assert decision.has_skips is False

