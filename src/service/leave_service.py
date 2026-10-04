from datetime import datetime
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import select
from src.database import engine, Employee, LeaveType, LeaveEntitlement, LeaveRequest
from src.service.calendar_service import calculate_working_days
from src.service.session import with_session


@with_session
def create_leave_request(
    employee_id: str,
    leave_type_id: str,
    start_date: str,
    end_date: str,
    reason: str = "",
    session: Optional[Session] = None
) -> Dict[str, Any]:
    """Create a new leave request and update employee entitlement balances using SQLAlchemy ORM."""
    emp = session.get(Employee, employee_id)
    if not emp:
        raise ValueError(f"Employee ID '{employee_id}' not found.")

    lt = session.scalar(
        select(LeaveType).where(
            (LeaveType.code == leave_type_id) |
            (LeaveType.name.like(f"%{leave_type_id}%"))
        )
    )
    if not lt:
        raise ValueError(f"Leave type '{leave_type_id}' not found.")

    requested_days = calculate_working_days(start_date, end_date, session)
    if requested_days <= 0:
        raise ValueError("Requested period contains 0 working days.")

    year = datetime.strptime(start_date, "%Y-%m-%d").year

    ent = session.scalar(
        select(LeaveEntitlement).where(
            LeaveEntitlement.employee_id == employee_id,
            LeaveEntitlement.leave_type == lt.code,
            LeaveEntitlement.year == year
        )
    )

    if not ent:
        raise ValueError(f"No leave entitlement found for {employee_id} in {year}.")

    if ent.remaining_days < requested_days:
        raise ValueError(
            f"Insufficient leave balance! Available: {ent.remaining_days} days, Requested: {requested_days} days."
        )

    last_req = session.scalar(
        select(LeaveRequest).order_by(LeaveRequest.request_id.desc()).limit(1)
    )
    req_id = (last_req.request_id + 1) if last_req else 1
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    new_request = LeaveRequest(
        request_id=req_id,
        employee_id=employee_id,
        leave_type=lt.code,
        start_date=start_date,
        end_date=end_date,
        days=requested_days,
        requested_days=requested_days,
        status="PENDING",
        comment=reason,
        reason=reason,
        created_at=now_str
    )
    session.add(new_request)

    ent.pending_days += requested_days
    ent.remaining_days -= requested_days

    session.commit()

    return {
        "success": True,
        "request_id": req_id,
        "requested_days": requested_days,
        "status": "PENDING",
        "remaining_days": ent.remaining_days
    }


@with_session
def list_leave_requests(
    employee_id: Optional[str] = None,
    status: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    session: Optional[Session] = None
) -> List[Dict[str, Any]]:
    """List leave requests filtered by employee, status, or date range."""
    query = select(LeaveRequest)
    if employee_id:
        query = query.where(LeaveRequest.employee_id == employee_id)
    if status:
        query = query.where(LeaveRequest.status == status.upper())
    if start_date:
        query = query.where(LeaveRequest.start_date >= start_date)
    if end_date:
        query = query.where(LeaveRequest.end_date <= end_date)

    requests = session.scalars(query).all()
    return [
        {
            "request_id": str(req.request_id),
            "employee_id": req.employee_id,
            "leave_type": req.leave_type,
            "start_date": req.start_date,
            "end_date": req.end_date,
            "days": req.days,
            "status": req.status,
            "reason": req.reason or req.comment
        }
        for req in requests
    ]


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

    try:
        req_num = int(str(request_id).replace("REQ", ""))
    except ValueError:
        req_num = request_id

    req = session.scalar(select(LeaveRequest).where(LeaveRequest.request_id == req_num))
    if not req:
        raise ValueError(f"Leave request ID '{request_id}' not found.")

    if req.status != "PENDING":
        raise ValueError(f"Request '{request_id}' is already {req.status}.")

    ent = session.scalar(select(LeaveEntitlement).where(
        LeaveEntitlement.employee_id == req.employee_id,
        LeaveEntitlement.leave_type == req.leave_type
    ))

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
    try:
        req_num = int(str(request_id).replace("REQ", ""))
    except ValueError:
        req_num = request_id

    query = select(LeaveRequest).where(LeaveRequest.request_id == req_num)
    if employee_id:
        query = query.where(LeaveRequest.employee_id == employee_id)

    req = session.scalar(query)
    if not req:
        raise ValueError(f"Leave request ID '{request_id}' not found.")

    if req.status == "CANCELLED":
        raise ValueError(f"Request '{request_id}' is already CANCELLED.")

    ent = session.scalar(select(LeaveEntitlement).where(
        LeaveEntitlement.employee_id == req.employee_id,
        LeaveEntitlement.leave_type == req.leave_type
    ))

    if ent:
        if req.status == "PENDING":
            ent.pending_days -= req.days
            ent.remaining_days += req.days
        elif req.status == "APPROVED":
            ent.used_days -= req.days
            ent.remaining_days += req.days

    req.status = "CANCELLED"
    session.commit()

    return {
        "success": True,
        "request_id": str(req.request_id),
        "status": "CANCELLED"
    }
