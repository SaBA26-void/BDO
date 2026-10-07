import pytest

from src.service.leave_balance_service import get_leave_balance
from src.service.leave_service import (
    ASSISTANT_CHANNEL,
    LeavePolicyError,
    cancel_leave_request,
    create_leave_request,
    list_leave_requests,
)


def assistant_request(employee_id, leave_type, start, end, **kwargs):
    return create_leave_request(
        employee_id=employee_id, leave_type_id=leave_type, start_date=start, end_date=end,
        created_via=ASSISTANT_CHANNEL, **kwargs,
    )


def remaining(employee_id, leave_type):
    return get_leave_balance(employee_id=employee_id, year=2026, leave_type_id=leave_type)[0]["remaining_days"]


@pytest.mark.parametrize("employee_id, leave_type, start, end, article", [
    # Article 12.3: next year's dates go through the HR portal.
    ("E1007", "ANNUAL", "2027-01-04", "2027-01-05", "12.3"),
    # Article 4.5: 16 working days (2026-11-23 is a public holiday).
    ("E1007", "ANNUAL", "2026-11-02", "2026-11-24", "4.5"),
    # Article 4.4: one working day of notice instead of five.
    ("E1007", "ANNUAL", "2026-10-13", "2026-10-13", "4.4"),
    # Article 4.3: E1004 is on probation until 2026-11-30.
    ("E1004", "ANNUAL", "2026-11-02", "2026-11-03", "4.3"),
    # Article 4.6: E1001 works in audit, 1-20 December is restricted.
    ("E1001", "ANNUAL", "2026-12-01", "2026-12-02", "4.6"),
    # Article 12.3: overlaps E1001's pending 2026-11-09..11 request.
    ("E1001", "ANNUAL", "2026-11-10", "2026-11-10", "12.3"),
    # Article 7.2: two working days of notice instead of ten (2026-10-14 is a holiday).
    ("E1007", "UNPAID", "2026-10-15", "2026-10-16", "7.2"),
    # Article 5.1: E1002 has 4 annual days left.
    ("E1002", "ANNUAL", "2026-11-02", "2026-11-06", "5.1"),
    # Articles 8-10: HR-only leave types.
    ("E1001", "STUDY", "2026-11-02", "2026-11-02", "9"),
    ("E1001", "PARENTAL", "2026-12-01", "2026-12-31", "10"),
])
def test_assistant_refuses_requests_that_break_policy(employee_id, leave_type, start, end, article):
    with pytest.raises(LeavePolicyError) as err:
        assistant_request(employee_id, leave_type, start, end)
    assert err.value.article == article


def test_weekend_only_request_is_refused():
    with pytest.raises(LeavePolicyError) as err:
        assistant_request("E1007", "ANNUAL", "2026-11-07", "2026-11-08")
    assert err.value.article == "2.2"


def test_dry_run_checks_without_creating():
    before = len(list_leave_requests(employee_id="E1007"))
    preview = assistant_request("E1007", "ANNUAL", "2026-11-02", "2026-11-04", dry_run=True)

    assert preview["dry_run"] and preview["requested_days"] == 3
    assert preview["remaining_days_after"] == 12
    assert len(list_leave_requests(employee_id="E1007")) == before
    assert remaining("E1007", "ANNUAL") == 15


def test_created_request_is_pending_and_reserves_balance():
    data = assistant_request("E1007", "ANNUAL", "2026-11-02", "2026-11-04")

    assert data["status"] == "PENDING"
    assert data["remaining_days"] == 12
    stored = list_leave_requests(employee_id="E1007", status="PENDING")
    assert stored[0]["created_at"].startswith("2026-10-09")
    assert stored[0]["created_via"] == "assistant"


def test_unpaid_counts_calendar_days():
    data = assistant_request("E1007", "UNPAID", "2026-11-06", "2026-11-09")
    assert data["requested_days"] == 4


def test_cancel_restores_balance():
    data = assistant_request("E1007", "ANNUAL", "2026-11-02", "2026-11-04")
    cancel_leave_request(request_id=str(data["request_id"]))
    assert remaining("E1007", "ANNUAL") == 15


def test_cancelling_twice_fails():
    cancel_leave_request(request_id="5")
    with pytest.raises(ValueError):
        cancel_leave_request(request_id="5")
