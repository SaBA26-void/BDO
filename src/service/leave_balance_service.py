from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select
from src.database import engine, LeaveEntitlement, Employee
from src.service.session import with_session


@with_session
def get_leave_balance(
    employee_id: str,
    year: int = 2026,
    leave_type_id: Optional[str] = None,
    session: Optional[Session] = None
) -> List[Dict[str, Any]]:
    """View remaining leave balances for an employee."""
    target_id = employee_id
    emp = session.get(Employee, employee_id)
    if not emp and employee_id.startswith("EMP"):
        num_part = employee_id[3:]
        if num_part.isdigit():
            alt_id = f"E1{num_part.zfill(3)}"
            emp = session.get(Employee, alt_id)
            if emp:
                target_id = emp.employee_id
    elif not emp:
        emp = session.scalar(select(Employee).where(Employee.employee_id.ilike(f"%{employee_id}%")))
        if emp:
            target_id = emp.employee_id

    query = select(LeaveEntitlement).where(
        LeaveEntitlement.employee_id == target_id,
        LeaveEntitlement.year == year
    )
    if leave_type_id:
        query = query.where(LeaveEntitlement.leave_type == leave_type_id)

    entitlements = session.scalars(query).all()
    return [
        {
            "leave_type": ent.leave_type,
            "entitled_days": ent.entitled_days,
            "used_days": ent.used_days,
            "pending_days": ent.pending_days,
            "remaining_days": ent.remaining_days
        }
        for ent in entitlements
    ]
