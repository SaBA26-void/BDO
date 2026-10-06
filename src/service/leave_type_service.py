from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select
from src.database import engine, LeaveType
from src.service.session import with_session


@with_session
def get_leave_types(session: Optional[Session] = None) -> List[Dict[str, Any]]:
    """List all available leave types in the company."""
    types = session.scalars(select(LeaveType)).all()
    return [
        {
            "code": lt.code,
            "name": lt.name,
            "day_unit": lt.day_unit,
            "annual_limit_days": lt.annual_limit_days,
            "self_service": lt.self_service
        }
        for lt in types
    ]
