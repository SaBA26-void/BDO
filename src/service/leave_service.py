from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select
from src.database import engine, Employee, LeaveType, LeaveEntitlement, LeaveRequest
from src.service.calendar_service import calculate_working_days

def create_leave_request(
    employee_id: str,
    leave_type_id: str,
    start_date: str,
    end_date: str,
    reason: str = "",
    session: Optional[Session] = None
) -> Dict[str, Any]:
    """Create a new leave request and update employee entitlement balances using SQLAlchemy ORM."""
    
    # Manage database session lifecycle if not provided by caller
    close_session = False
    if session is None:
        session = Session(engine)
        close_session = True

    try:
        # Validate target employee exists
        emp = session.get(Employee, employee_id)
        if not emp:
            raise ValueError(f"Employee ID '{employee_id}' not found.")

        # Resolve leave type by ID, code, or Georgian name
        lt = session.scalar(
            select(LeaveType).where(
                (LeaveType.leave_type_id == leave_type_id) |
                (LeaveType.code == leave_type_id) |
                (LeaveType.name_ka.like(f"%{leave_type_id}%"))
            )
        )
        if not lt:
            raise ValueError(f"Leave type '{leave_type_id}' not found.")

        # Calculate deductible working days (excluding weekends & public holidays)
        requested_days = calculate_working_days(start_date, end_date, session)
        if requested_days <= 0:
            raise ValueError("Requested period contains 0 working days.")

        year = datetime.strptime(start_date, "%Y-%m-%d").year

        # Fetch entitlement balance for the request year
        ent = session.scalar(
            select(LeaveEntitlement).where(
                LeaveEntitlement.employee_id == employee_id,
                LeaveEntitlement.leave_type_id == lt.leave_type_id,
                LeaveEntitlement.year == year
            )
        )

        if not ent:
            raise ValueError(f"No leave entitlement found for {employee_id} in {year}.")

        if ent.remaining_days < requested_days:
            raise ValueError(
                f"Insufficient leave balance! Available: {ent.remaining_days} days, Requested: {requested_days} days."
            )

        # Generate sequential request ID (e.g., REQ001, REQ002)
        last_req = session.scalar(
            select(LeaveRequest).order_by(LeaveRequest.request_id.desc()).limit(1)
        )
        req_num = int(last_req.request_id.replace('REQ', '')) + 1 if last_req else 1
        req_id = f"REQ{req_num:03d}"

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Create new leave request record
        new_request = LeaveRequest(
            request_id=req_id,
            employee_id=employee_id,
            leave_type_id=lt.leave_type_id,
            start_date=start_date,
            end_date=end_date,
            requested_days=requested_days,
            status="PENDING",
            reason=reason,
            created_at=now_str
        )
        session.add(new_request)

        # Update entitlement pending and remaining balances
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

    except Exception as e:
        session.rollback()
        raise e
    finally:
        if close_session:
            session.close()