import json
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mcp_server.app import mcp, run_tool
from src.service.employee_service import get_employee as db_get_employee
from src.service.leave_type_service import get_leave_types as db_get_leave_types
from src.service.leave_balance_service import get_leave_balance as db_get_leave_balance
from src.service.leave_service import (
    create_leave_request as db_create_leave_request,
    list_leave_requests as db_list_leave_requests,
    approve_or_reject_leave_request as db_approve_or_reject_leave_request,
    cancel_leave_request as db_cancel_leave_request,
)


@mcp.tool()
def create_leave_request(
    employee_id: str,
    leave_type: str,
    start_date: str,
    end_date: str,
    reason: str = ""
) -> str:
    """Create a new leave request for an employee."""
    try:
        result = db_create_leave_request(
            employee_id=employee_id,
            leave_type_id=leave_type,
            start_date=start_date,
            end_date=end_date,
            reason=reason
        )
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False, indent=2)


@mcp.tool()
def list_leave_requests(
    employee_id: Optional[str] = None,
    status: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> str:
    """View list of leave requests with optional filters."""
    try:
        requests = db_list_leave_requests(
            employee_id=employee_id,
            status=status,
            start_date=start_date,
            end_date=end_date
        )
        return json.dumps({"success": True, "count": len(requests), "requests": requests}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False, indent=2)


@mcp.tool()
def get_leave_balance(
    employee_id: str,
    year: int = 2026,
    leave_type: Optional[str] = None
) -> str:
    """View remaining leave balance for an employee."""
    try:
        emp = db_get_employee(employee_id)
        if not emp:
            return json.dumps({"success": False, "error": f"Employee '{employee_id}' not found."}, ensure_ascii=False, indent=2)

        balances = db_get_leave_balance(employee_id=employee_id, year=year, leave_type_id=leave_type)
        emp_name = f"{emp.get('first_name', '')} {emp.get('last_name', '')}".strip() or emp.get('full_name', '')
        return json.dumps({
            "success": True,
            "employee_id": employee_id,
            "employee_name": emp_name,
            "year": year,
            "balances": balances
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False, indent=2)


@mcp.tool()
def approve_or_reject_leave_request(
    request_id: str,
    status: str,
    reviewer_id: Optional[str] = "HR_MANAGER"
) -> str:
    """Approve or reject a leave request ('APPROVED' or 'REJECTED')."""
    try:
        result = db_approve_or_reject_leave_request(
            request_id=request_id,
            status=status,
            reviewer_id=reviewer_id
        )
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False, indent=2)


@mcp.tool()
def cancel_leave_request(
    request_id: str,
    employee_id: Optional[str] = None
) -> str:
    """Cancel a leave request and restore balance."""
    try:
        result = db_cancel_leave_request(
            request_id=request_id,
            employee_id=employee_id
        )
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False, indent=2)


@mcp.tool()
def list_leave_types() -> str:
    """List all available leave types in the system."""
    try:
        types = db_get_leave_types()
        return json.dumps({"success": True, "count": len(types), "leave_types": types}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False, indent=2)
