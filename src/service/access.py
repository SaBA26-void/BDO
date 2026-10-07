from dataclasses import dataclass
from typing import Optional
from sqlalchemy.orm import Session
from src.database import Employee
from src.service.session import with_session

EMPLOYEE_ROLE = "employee"
HR_ROLE = "hr"
HR_DEPARTMENT_CODE = "HRS"

# Channel recorded in leave_requests.created_via for each caller role.
ROLE_CHANNELS = {EMPLOYEE_ROLE: "assistant", HR_ROLE: "hr"}


class AccessDeniedError(PermissionError):
    """The caller's role does not allow the action (Article 12.3 for the employee assistant)."""

    def __init__(self, message: str, article: Optional[str] = None):
        super().__init__(message)
        self.article = article


@dataclass(frozen=True)
class Caller:
    employee_id: str
    role: str

    @property
    def is_hr(self) -> bool:
        return self.role == HR_ROLE

    @property
    def channel(self) -> str:
        return ROLE_CHANNELS[self.role]


@with_session
def resolve_caller(caller_id: str, caller_role: str, session: Optional[Session] = None) -> Caller:
    """Validate the caller against the employee table. The HR role is limited to the HR department."""
    role = (caller_role or "").strip().lower()
    if role not in ROLE_CHANNELS:
        raise AccessDeniedError(f"Unknown caller_role '{caller_role}'. Use 'employee' or 'hr'.")

    emp = session.get(Employee, (caller_id or "").strip().upper())
    if not emp or (emp.status or "active").lower() != "active":
        raise AccessDeniedError(f"Caller '{caller_id}' is not an active employee.")
    if role == HR_ROLE and emp.department_code != HR_DEPARTMENT_CODE:
        raise AccessDeniedError(f"Caller '{emp.employee_id}' is not a member of the HR department.")
    return Caller(employee_id=emp.employee_id, role=role)


def require_self_or_hr(caller: Caller, employee_id: str) -> None:
    if not caller.is_hr and employee_id.strip().upper() != caller.employee_id:
        raise AccessDeniedError(
            "თანამშრომლის ასისტენტს შეუძლია მხოლოდ საკუთარი მონაცემების ნახვა და საკუთარ სახელზე "
            "მოთხოვნის შექმნა.",
            "12.3",
        )


def require_hr(caller: Caller, action: str) -> None:
    if not caller.is_hr:
        raise AccessDeniedError(
            f"თანამშრომლის ასისტენტს არ შეუძლია მოთხოვნის {action}. მიმართეთ უშუალო ხელმძღვანელს, "
            "HR პორტალს ან ადამიანური რესურსების სამსახურს.",
            "12.3",
        )
