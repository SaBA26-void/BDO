from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select
from src.database import LeaveEntitlement
from src.service.session import with_session


@with_session
def get_leave_balance(
    employee_id: str,
    year: int = 2026,
    leave_type_id: Optional[str] = None,
    session: Optional[Session] = None
) -> List[Dict[str, Any]]:
    """View remaining leave balances for an employee, looked up by exact ID."""
    query = select(LeaveEntitlement).where(
        LeaveEntitlement.employee_id == employee_id,
        LeaveEntitlement.year == year
    )
    if leave_type_id:
        query = query.where(LeaveEntitlement.leave_type == leave_type_id.strip().upper())

    entitlements = session.scalars(query).all()
    return [
        {
            "leave_type": ent.leave_type,
            "entitled_days": ent.entitled_days,
            "carried_over_days": ent.carried_over_days,
            "total_days": ent.total_days,
            "used_days": ent.used_days,
            "pending_days": ent.pending_days,
            "remaining_days": ent.remaining_days
        }
        for ent in entitlements
    ]
