from conftest import call_tool

EMPLOYEE = {"caller_id": "E1001", "caller_role": "employee"}
HR = {"caller_id": "E1007", "caller_role": "hr"}
PENDING_REQUEST_OF_E1001 = "5"


def test_employee_sees_own_balance():
    data = call_tool("get_leave_balance", **EMPLOYEE, employee_id="E1001")
    assert data["success"]
    annual = next(b for b in data["balances"] if b["leave_type"] == "ANNUAL")
    assert annual["remaining_days"] == 10


def test_employee_cannot_see_other_employees_balance():
    data = call_tool("get_leave_balance", **EMPLOYEE, employee_id="E1002")
    assert data == {**data, "success": False, "forbidden": True, "article": "12.3"}


def test_hr_sees_any_balance():
    assert call_tool("get_leave_balance", **HR, employee_id="E1002")["success"]


def test_unknown_caller_is_rejected():
    data = call_tool("get_leave_balance", caller_id="E9999", caller_role="employee", employee_id="E9999")
    assert data["forbidden"]


def test_non_hr_employee_cannot_claim_hr_role():
    data = call_tool("get_leave_balance", caller_id="E1001", caller_role="hr", employee_id="E1002")
    assert data["forbidden"]


def test_unknown_role_is_rejected():
    data = call_tool("get_leave_balance", caller_id="E1007", caller_role="admin", employee_id="E1001")
    assert data["forbidden"]


def test_employee_cannot_approve_or_cancel():
    approve = call_tool("approve_or_reject_leave_request", **EMPLOYEE,
                        request_id=PENDING_REQUEST_OF_E1001, status="APPROVED")
    cancel = call_tool("cancel_leave_request", **EMPLOYEE, request_id=PENDING_REQUEST_OF_E1001)
    assert approve["forbidden"] and approve["article"] == "12.3"
    assert cancel["forbidden"] and cancel["article"] == "12.3"


def test_employee_lists_only_own_requests():
    data = call_tool("list_leave_requests", **EMPLOYEE)
    assert data["count"] > 0
    assert {r["employee_id"] for r in data["requests"]} == {"E1001"}


def test_employee_cannot_list_other_employees_requests():
    assert call_tool("list_leave_requests", **EMPLOYEE, employee_id="E1002")["forbidden"]


def test_hr_lists_all_requests():
    data = call_tool("list_leave_requests", **HR)
    assert len({r["employee_id"] for r in data["requests"]}) > 1


def test_date_filter_matches_overlapping_requests():
    data = call_tool("list_leave_requests", **HR, employee_id="E1001",
                     start_date="2026-11-10", end_date="2026-11-30")
    assert [r["request_id"] for r in data["requests"]] == [PENDING_REQUEST_OF_E1001]


def test_status_filter():
    data = call_tool("list_leave_requests", **HR, status="pending")
    assert data["count"] > 0
    assert {r["status"] for r in data["requests"]} == {"PENDING"}


def test_hr_approves_request_and_balance_moves_to_used():
    data = call_tool("approve_or_reject_leave_request", **HR,
                     request_id=PENDING_REQUEST_OF_E1001, status="APPROVED")
    assert data["success"] and data["reviewed_by"] == "E1007"

    annual = call_tool("get_leave_balance", **EMPLOYEE, employee_id="E1001", leave_type="ANNUAL")["balances"][0]
    assert annual["pending_days"] == 0
    assert annual["used_days"] == 18
    assert annual["remaining_days"] == 10


def test_hr_rejects_request_and_balance_is_restored():
    call_tool("approve_or_reject_leave_request", **HR, request_id=PENDING_REQUEST_OF_E1001, status="REJECTED")
    annual = call_tool("get_leave_balance", **HR, employee_id="E1001", leave_type="ANNUAL")["balances"][0]
    assert annual["pending_days"] == 0
    assert annual["remaining_days"] == 13


def test_hr_cannot_decide_own_request():
    created = call_tool("create_leave_request", **HR, employee_id="E1007", leave_type="ANNUAL",
                        start_date="2026-11-02", end_date="2026-11-03")
    data = call_tool("approve_or_reject_leave_request", **HR, request_id=str(created["request_id"]), status="APPROVED")
    assert data["forbidden"]


def test_hr_cancels_request_and_balance_is_restored():
    data = call_tool("cancel_leave_request", **HR, request_id=PENDING_REQUEST_OF_E1001)
    assert data["status"] == "CANCELLED"
    annual = call_tool("get_leave_balance", **HR, employee_id="E1001", leave_type="ANNUAL")["balances"][0]
    assert annual["remaining_days"] == 13


def test_employee_request_is_recorded_as_assistant_channel():
    data = call_tool("create_leave_request", caller_id="E1007", caller_role="employee", employee_id="E1007",
                     leave_type="ANNUAL", start_date="2026-11-02", end_date="2026-11-04")
    assert data["success"] and data["created_via"] == "assistant" and data["status"] == "PENDING"


def test_employee_cannot_file_request_for_someone_else():
    data = call_tool("create_leave_request", **EMPLOYEE, employee_id="E1002",
                     leave_type="ANNUAL", start_date="2026-11-02", end_date="2026-11-03")
    assert data["forbidden"] and data["article"] == "12.3"


def test_employee_cannot_file_bereavement():
    data = call_tool("create_leave_request", **EMPLOYEE, employee_id="E1001",
                     leave_type="BEREAVEMENT", start_date="2026-10-12", end_date="2026-10-13")
    assert not data["success"] and data["article"] == "8"


def test_hr_files_bereavement_without_balance_tracking():
    data = call_tool("create_leave_request", **HR, employee_id="E1001",
                     leave_type="BEREAVEMENT", start_date="2026-10-12", end_date="2026-10-13")
    assert data["success"]
    assert data["created_via"] == "hr"
    assert data["requested_days"] == 2
    assert data["remaining_days"] is None


def test_hr_request_skips_assistant_only_rules():
    # One working day of notice breaks Article 4.4 for the assistant, but HR may record it.
    data = call_tool("create_leave_request", **HR, employee_id="E1001",
                     leave_type="ANNUAL", start_date="2026-10-13", end_date="2026-10-13")
    assert data["success"]


def test_list_leave_types_needs_no_caller():
    data = call_tool("list_leave_types")
    assert {lt["code"] for lt in data["leave_types"]} >= {"ANNUAL", "SICK", "UNPAID", "BEREAVEMENT"}
