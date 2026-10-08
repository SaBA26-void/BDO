"""
Leave request operations: create, list, approve/reject, cancel.
Policy rules live in leave_policy.py; this module only orchestrates them and updates the database.
"""

from datetime import date, datetime
from typing import Dict, Any, Optional, List, Tuple

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from src.database import Employee, LeaveType, LeaveEntitlement, LeaveRequest
from src.service.calendar_service import calculate_working_days
from src.service.session import with_session
from src.service.leave_policy import (  # noqa: F401  (ASSISTANT_CHANNEL / LeavePolicyError are re-exported)
    ASSISTANT_CHANNEL,
    UNTRACKED_LEAVE_TYPES,
    LeavePolicyError,
    check_assistant_request,
    check_balance,
    check_leave_type_allowed,
)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _parse_request_id(request_id: str) -> Any:
    try:
        return int(str(request_id).upper().replace("REQ", ""))
    except ValueError:
        return request_id


def _parse_dates(start_date: str, end_date: str) -> Tuple[date, date]:
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("თარიღები უნდა იყოს ფორმატით YYYY-MM-DD.")
    if end < start:
        raise ValueError("დასრულების თარიღი დაწყების თარიღზე ადრე ვერ იქნება.")
    return start, end


def _count_days(session: Session, lt: LeaveType, start: date, end: date) -> int:
    """Article 2.2: UNPAID counts calendar days, every other type counts working days."""
    if lt.day_unit == "calendar":
        return (end - start).days + 1
    days = calculate_working_days(start.isoformat(), end.isoformat(), session)
    if days <= 0:
        raise LeavePolicyError("მოთხოვნილ პერიოდში სამუშაო დღე არ არის (შაბათ-კვირა ან უქმე დღეებია).", "2.2")
    return days


def _find_entitlement(session: Session, employee_id: str, leave_type: str, year: int) -> Optional[LeaveEntitlement]:
    return session.scalar(select(LeaveEntitlement).where(
        LeaveEntitlement.employee_id == employee_id,
        LeaveEntitlement.leave_type == leave_type,
        LeaveEntitlement.year == year,
    ))


def _available_days(ent: Optional[LeaveEntitlement], lt: LeaveType) -> Optional[int]:
    """Remaining balance, or None for types without a yearly balance (Article 5.1)."""
    if ent is not None:
        return ent.remaining_days
    return None if lt.code in UNTRACKED_LEAVE_TYPES else 0


def _next_request_id(session: Session) -> int:
    last = session.scalar(select(LeaveRequest).order_by(LeaveRequest.request_id.desc()).limit(1))
    return (last.request_id + 1) if last else 1


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #
@with_session
def create_leave_request(
    employee_id: str,
    leave_type_id: str,
    start_date: str,
    end_date: str,
    reason: str = "",
    created_via: str = ASSISTANT_CHANNEL,
    dry_run: bool = False,
    session: Optional[Session] = None
) -> Dict[str, Any]:
    """Create a PENDING leave request. Requests from the assistant are checked against Article 12."""
    emp = session.get(Employee, employee_id)
    if not emp:
        raise ValueError(f"თანამშრომელი '{employee_id}' ვერ მოიძებნა.")

    lt = session.get(LeaveType, leave_type_id.strip().upper())
    if not lt:
        raise ValueError(f"შვებულების სახე '{leave_type_id}' ვერ მოიძებნა.")

    from_assistant = created_via == ASSISTANT_CHANNEL
    if from_assistant:
        check_leave_type_allowed(lt)

    start, end = _parse_dates(start_date, end_date)
    requested_days = _count_days(session, lt, start, end)

    if from_assistant:
        check_assistant_request(session, emp, lt, start, end, requested_days, today=date.today())

    ent = _find_entitlement(session, emp.employee_id, lt.code, start.year)
    available = _available_days(ent, lt)
    check_balance(lt, available, requested_days)

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "employee_id": emp.employee_id,
            "leave_type": lt.code,
            "start_date": start_date,
            "end_date": end_date,
            "requested_days": requested_days,
            "day_unit": lt.day_unit,
            "remaining_days_after": available - requested_days if available is not None else None,
        }

    new_request = LeaveRequest(
        request_id=_next_request_id(session),
        employee_id=emp.employee_id,
        leave_type=lt.code,
        start_date=start_date,
        end_date=end_date,
        days=requested_days,
        requested_days=requested_days,
        status="PENDING",
        created_via=created_via,
        comment=reason,
        reason=reason,
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    session.add(new_request)

    if ent:
        ent.pending_days += requested_days
        ent.remaining_days -= requested_days

    session.commit()

    return {
        "success": True,
        "request_id": new_request.request_id,
        "leave_type": lt.code,
        "start_date": start_date,
        "end_date": end_date,
        "requested_days": requested_days,
        "day_unit": lt.day_unit,
        "status": "PENDING",
        "created_via": created_via,
        "remaining_days": ent.remaining_days if ent else None
    }


# --------------------------------------------------------------------------- #
# List
# --------------------------------------------------------------------------- #
@with_session
def list_leave_requests(
    employee_id: Optional[str] = None,
    status: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    session: Optional[Session] = None
) -> List[Dict[str, Any]]:
    """List leave requests filtered by employee, status, or a date range the leave overlaps."""
    query = select(LeaveRequest).order_by(LeaveRequest.start_date, LeaveRequest.request_id)
    if employee_id:
        query = query.where(LeaveRequest.employee_id == employee_id.strip().upper())
    if status:
        query = query.where(func.upper(LeaveRequest.status) == status.upper())
    if start_date:
        query = query.where(LeaveRequest.end_date >= start_date)
    if end_date:
        query = query.where(LeaveRequest.start_date <= end_date)

    return [_request_to_dict(req) for req in session.scalars(query).all()]


def _request_to_dict(req: LeaveRequest) -> Dict[str, Any]:
    return {
        "request_id": str(req.request_id),
        "employee_id": req.employee_id,
        "leave_type": req.leave_type,
        "start_date": req.start_date,
        "end_date": req.end_date,
        "days": req.days,
        "status": req.status.upper(),
        "created_at": req.created_at,
        "created_via": req.created_via,
        "reason": req.reason or req.comment
    }


# --------------------------------------------------------------------------- #
# Approve / reject / cancel
# --------------------------------------------------------------------------- #
def _get_request(session: Session, request_id: str, employee_id: Optional[str] = None) -> LeaveRequest:
    query = select(LeaveRequest).where(LeaveRequest.request_id == _parse_request_id(request_id))
    if employee_id:
        query = query.where(LeaveRequest.employee_id == employee_id)
    req = session.scalar(query)
    if not req:
        raise ValueError(f"Leave request ID '{request_id}' not found.")
    return req


@with_session
def approve_or_reject_leave_request(
    request_id: str,
    status: str,
    reviewer_id: Optional[str] = "HR_MANAGER",
    session: Optional[Session] = None
) -> Dict[str, Any]:
    """Approve or reject a pending leave request."""
    status_upper = status.upper()
    if status_upper not in ["APPROVED", "REJECTED"]:
        raise ValueError("Status must be either 'APPROVED' or 'REJECTED'.")

    req = _get_request(session, request_id)
    if req.status.upper() != "PENDING":
        raise ValueError(f"Request '{request_id}' is already {req.status.upper()}.")
    if reviewer_id and req.employee_id == reviewer_id:
        raise PermissionError("A reviewer cannot approve or reject their own leave request.")

    ent = _find_entitlement(session, req.employee_id, req.leave_type, int(req.start_date[:4]))
    if ent:
        ent.pending_days -= req.days
        if status_upper == "APPROVED":
            ent.used_days += req.days
        else:
            ent.remaining_days += req.days

    req.status = status_upper
    req.reviewed_by = reviewer_id
    req.reviewed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    session.commit()

    return {
        "success": True,
        "request_id": str(req.request_id),
        "status": req.status,
        "reviewed_by": reviewer_id
    }


@with_session
def cancel_leave_request(
    request_id: str,
    employee_id: Optional[str] = None,
    session: Optional[Session] = None
) -> Dict[str, Any]:
    """Cancel a leave request and restore unused balance."""
    req = _get_request(session, request_id, employee_id)

    current = req.status.upper()
    if current in ("CANCELLED", "REJECTED"):
        raise ValueError(f"Request '{request_id}' is already {current}.")

    ent = _find_entitlement(session, req.employee_id, req.leave_type, int(req.start_date[:4]))
    if ent:
        if current == "PENDING":
            ent.pending_days -= req.days
        elif current == "APPROVED":
            ent.used_days -= req.days
        ent.remaining_days += req.days

    req.status = "CANCELLED"
    session.commit()

    return {
        "success": True,
        "request_id": str(req.request_id),
        "status": "CANCELLED"
    }
