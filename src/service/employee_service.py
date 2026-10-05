from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from src.database import Employee
from src.service.session import with_session


@with_session
def get_employee(employee_id: str, session: Optional[Session] = None) -> Optional[Dict[str, Any]]:
    """Fetch employee details by exact ID."""
    emp = session.get(Employee, employee_id)
    if not emp:
        return None

    parts = emp.full_name.split(" ", 1)
    return {
        "employee_id": emp.employee_id,
        "full_name": emp.full_name,
        "first_name": parts[0],
        "last_name": parts[1] if len(parts) > 1 else "",
        "email": emp.email,
        "department": emp.department_name,
        "position": emp.job_title,
        "status": emp.status
    }
