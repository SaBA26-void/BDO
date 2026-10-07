import os
import sys
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mcp_server.app import mcp, run_tool
from src.service.access import resolve_caller, require_hr, require_self_or_hr
from src.service.employee_service import get_employee as db_get_employee
from src.service.leave_type_service import get_leave_types as db_get_leave_types
from src.service.leave_balance_service import get_leave_balance as db_get_leave_balance
from src.service.leave_service import (
    create_leave_request as db_create_leave_request,
    list_leave_requests as db_list_leave_requests,
    approve_or_reject_leave_request as db_approve_or_reject_leave_request,
    cancel_leave_request as db_cancel_leave_request,
)

CALLER_DOC = (
    " caller_id is the acting employee's ID; caller_role is 'employee' (the employee assistant, "
    "limited to the caller's own data by Article 12 of the leave policy) or 'hr' (HR department staff)."
)


@mcp.tool(description=(
    "Create a PENDING leave request. Dates are YYYY-MM-DD. Employees may only file their own ANNUAL, "
    "SICK or UNPAID requests, checked against Article 12.3; HR may file any type for any employee. "
    "With dry_run=true, run every check and return the day count without creating the request."
    + CALLER_DOC
))
def create_leave_request(
    caller_id: str,
    caller_role: str,
    employee_id: str,
    leave_type: str,
    start_date: str,
    end_date: str,
    reason: str = "",
    dry_run: bool = False
) -> str:
    def body():
        caller = resolve_caller(caller_id, caller_role)
        require_self_or_hr(caller, employee_id)
        return db_create_leave_request(
            employee_id=employee_id.strip().upper(),
            leave_type_id=leave_type,
            start_date=start_date,
            end_date=end_date,
            reason=reason,
            created_via=caller.channel,
            dry_run=dry_run
        )
    return run_tool(body)


@mcp.tool(description=(
    "List leave requests, filtered by employee, status (PENDING, APPROVED, REJECTED, CANCELLED) and a "
    "YYYY-MM-DD date range that the leave overlaps. Employees only see their own requests."
    + CALLER_DOC
))
def list_leave_requests(
    caller_id: str,
    caller_role: str,
    employee_id: Optional[str] = None,
    status: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> str:
    def body():
        caller = resolve_caller(caller_id, caller_role)
        target = employee_id
        if not caller.is_hr:
            target = employee_id or caller.employee_id
            require_self_or_hr(caller, target)
        requests = db_list_leave_requests(
            employee_id=target, status=status, start_date=start_date, end_date=end_date
        )
        return {"success": True, "count": len(requests), "requests": requests}
    return run_tool(body)


@mcp.tool(description=(
    "Show an employee's leave balance for a year (default: current year), optionally for one leave "
    "type. Employees only see their own balance." + CALLER_DOC
))
def get_leave_balance(
    caller_id: str,
    caller_role: str,
    employee_id: str,
    year: Optional[int] = None,
    leave_type: Optional[str] = None
) -> str:
    def body():
        caller = resolve_caller(caller_id, caller_role)
        require_self_or_hr(caller, employee_id)
        target = employee_id.strip().upper()
        emp = db_get_employee(target)
        if not emp:
            raise ValueError(f"Employee '{employee_id}' not found.")

        balance_year = year or datetime.now().year
        return {
            "success": True,
            "employee_id": target,
            "employee_name": emp["full_name"],
            "year": balance_year,
            "balances": db_get_leave_balance(employee_id=target, year=balance_year, leave_type_id=leave_type),
        }
    return run_tool(body)


@mcp.tool(description=(
    "Approve or reject a PENDING leave request (status 'APPROVED' or 'REJECTED'). HR only; reviewers "
    "cannot decide their own requests." + CALLER_DOC
))
def approve_or_reject_leave_request(
    caller_id: str,
    caller_role: str,
    request_id: str,
    status: str
) -> str:
    def body():
        caller = resolve_caller(caller_id, caller_role)
        require_hr(caller, "დამტკიცება ან უარყოფა")
        return db_approve_or_reject_leave_request(
            request_id=request_id, status=status, reviewer_id=caller.employee_id
        )
    return run_tool(body)


@mcp.tool(description=(
    "Cancel a PENDING or APPROVED leave request and restore the balance. HR only." + CALLER_DOC
))
def cancel_leave_request(
    caller_id: str,
    caller_role: str,
    request_id: str
) -> str:
    def body():
        caller = resolve_caller(caller_id, caller_role)
        require_hr(caller, "გაუქმება")
        return db_cancel_leave_request(request_id=request_id)
    return run_tool(body)


@mcp.tool(description="List all leave types with their day unit and yearly limit. Public reference data.")
def list_leave_types() -> str:
    def body():
        types = db_get_leave_types()
        return {"success": True, "count": len(types), "leave_types": types}
    return run_tool(body)
