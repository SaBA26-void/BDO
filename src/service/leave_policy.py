"""
Leave policy rules (Leave_and_Absence_Policy_v4.0, Article 12.3).
One check function per article. Each raises LeavePolicyError with the article number
so the caller can explain the refusal to the employee.
"""

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.database import Employee, LeaveRequest, LeaveType
from src.service.calendar_service import count_working_days_between

ASSISTANT_CHANNEL = "assistant"
ASSISTANT_LEAVE_TYPES = {"ANNUAL", "SICK", "UNPAID"}
ACTIVE_STATUSES = ("PENDING", "APPROVED")
# No yearly entitlement: HR sets the duration case by case (Articles 8 and 10).
UNTRACKED_LEAVE_TYPES = {"BEREAVEMENT", "PARENTAL"}

ANNUAL_MAX_DAYS = 15
ANNUAL_NOTICE_SHORT = 5    # up to 5 requested days
ANNUAL_NOTICE_LONG = 15    # 6-15 requested days
UNPAID_YEARLY_CAP = 30
UNPAID_NOTICE_DAYS = 10
# (start month, start day, end month, end day), inclusive.
AUDIT_RESTRICTED_PERIODS = [(12, 1, 12, 20), (1, 15, 3, 15)]
AUDIT_DEPARTMENT_CODE = "AUD"

HR_ONLY_LEAVE_TYPES = {
    "BEREAVEMENT": (
        "8",
        "გლოვის შვებულების მოთხოვნას HR ასისტენტი არ ქმნის (მუხლი 8.3). "
        "მოთხოვნა წარადგინეთ HR პორტალით ან ადამიანური რესურსების სამსახურის მეშვეობით, "
        "შვებულების პირველი დღიდან არაუგვიანეს 2 სამუშაო დღისა.",
    ),
    "STUDY": (
        "9",
        "სასწავლო და საგამოცდო შვებულების მოთხოვნას HR ასისტენტი არ ქმნის (მუხლი 9.3). "
        "მოთხოვნა წარადგინეთ HR პორტალით ან HR-ის მეშვეობით, დაწყებამდე სულ მცირე 10 სამუშაო დღით ადრე.",
    ),
    "PARENTAL": (
        "10",
        "მშობლის შვებულება თვითმომსახურების არხებით, მათ შორის HR ასისტენტით, არ წარდგება (მუხლი 10.2). "
        "მიმართეთ პირდაპირ ადამიანური რესურსების სამსახურს.",
    ),
}


class LeavePolicyError(ValueError):
    """A request the assistant may not create, with the policy article that forbids it."""

    def __init__(self, message: str, article: str):
        super().__init__(message)
        self.article = article


def active_requests(session: Session, employee_id: str):
    """Query for the employee's PENDING and APPROVED requests."""
    return select(LeaveRequest).where(
        LeaveRequest.employee_id == employee_id,
        func.upper(LeaveRequest.status).in_(ACTIVE_STATUSES),
    )


# --------------------------------------------------------------------------- #
# Individual rules
# --------------------------------------------------------------------------- #
def check_leave_type_allowed(lt: LeaveType) -> None:
    """Articles 8, 9, 10: the assistant only files ANNUAL, SICK and UNPAID."""
    if lt.code in ASSISTANT_LEAVE_TYPES:
        return
    article, message = HR_ONLY_LEAVE_TYPES.get(
        lt.code, ("12.3", "ამ სახის შვებულების მოთხოვნას HR ასისტენტი არ ქმნის. მიმართეთ HR-ს.")
    )
    raise LeavePolicyError(message, article)


def check_current_year(start: date, end: date, today: date) -> None:
    """Article 12.3: the assistant only files requests for the current year."""
    if start.year != today.year or end.year != today.year:
        raise LeavePolicyError(
            f"HR ასისტენტი ქმნის მოთხოვნებს მხოლოდ მიმდინარე, {today.year} წლის თარიღებზე. "
            "მომდევნო წლის მოთხოვნა HR პორტალით შეიძლება მიმდინარე წლის 1 დეკემბრიდან; "
            "წლებს შორის გადამავალი შვებულებისთვის თითოეულ წელზე ცალკე მოთხოვნაა საჭირო (მუხლი 2.1).",
            "12.3",
        )


def check_no_overlap(session: Session, employee_id: str, start: date, end: date) -> None:
    """Article 12.3: dates may not overlap another pending or approved request."""
    overlap = session.scalar(active_requests(session, employee_id).where(
        LeaveRequest.start_date <= end.isoformat(),
        LeaveRequest.end_date >= start.isoformat(),
    ))
    if overlap:
        raise LeavePolicyError(
            f"მოთხოვნილი თარიღები ემთხვევა თქვენს სხვა მოთხოვნას (ID {overlap.request_id}, "
            f"{overlap.start_date} – {overlap.end_date}, სტატუსი: {overlap.status.upper()}). "
            "აირჩიეთ სხვა თარიღები.",
            "12.3",
        )


def check_probation(emp: Employee, today: date) -> None:
    """Article 4.3: no annual leave during the probation period."""
    if emp.probation_end_date and today.isoformat() <= emp.probation_end_date:
        raise LeavePolicyError(
            f"გამოსაცდელი ვადა ({emp.probation_end_date}-ის ჩათვლით) ჯერ არ დასრულებულა, ამიტომ "
            "ყოველწლიური შვებულების გამოყენება ჯერ არ შეიძლება. ავადმყოფობისა და უხელფასო შვებულება "
            "ხელმისაწვდომია. გამონაკლისი (არაუმეტეს 2 სამუშაო დღე) მხოლოდ ადამიანური რესურსების "
            "სამსახურთან პირდაპირ შეთანხმდება.",
            "4.3",
        )


def check_max_duration(days: int) -> None:
    """Article 4.5: at most 15 working days of annual leave per request."""
    if days > ANNUAL_MAX_DAYS:
        raise LeavePolicyError(
            f"ერთი მოთხოვნით შეიძლება არაუმეტეს {ANNUAL_MAX_DAYS} სამუშაო დღის ყოველწლიური შვებულება "
            f"(მოთხოვნილია {days}). უფრო ხანგრძლივ შვებულებას სჭირდება პარტნიორის ან დირექტორის "
            "წერილობითი თანხმობა და წარდგება უშუალო ხელმძღვანელის მეშვეობით.",
            "4.5",
        )


def check_annual_notice(session: Session, today: date, start: date, days: int) -> None:
    """Article 4.4: 5 working days of notice for up to 5 days, 15 for longer leave."""
    required = ANNUAL_NOTICE_SHORT if days <= 5 else ANNUAL_NOTICE_LONG
    notice = count_working_days_between(today, start, session)
    if notice < required:
        raise LeavePolicyError(
            f"{days} სამუშაო დღის ყოველწლიურ შვებულებას სჭირდება სულ მცირე {required} სამუშაო დღით "
            f"ადრე შეტყობინება, დღეს წარდგენისას კი მხოლოდ {max(notice, 0)} სამუშაო დღეა. "
            "აირჩიეთ უფრო გვიანი თარიღი, ან გადაუდებელ შემთხვევაში მიმართეთ უშუალო ხელმძღვანელს.",
            "4.4",
        )


def _in_audit_restricted_period(start: date, end: date) -> bool:
    curr = start
    while curr <= end:
        md = (curr.month, curr.day)
        if any((m1, d1) <= md <= (m2, d2) for m1, d1, m2, d2 in AUDIT_RESTRICTED_PERIODS):
            return True
        curr += timedelta(days=1)
    return False


def check_restricted_period(emp: Employee, start: date, end: date) -> None:
    """Article 4.6: audit staff cannot take annual leave in the busy audit periods."""
    if emp.department_code == AUDIT_DEPARTMENT_CODE and _in_audit_restricted_period(start, end):
        raise LeavePolicyError(
            "აუდიტისა და მარწმუნებელი მომსახურების დეპარტამენტისთვის 1–20 დეკემბერი და "
            "15 იანვარი – 15 მარტი შეზღუდული პერიოდებია. ამ დღეებზე ყოველწლიური შვებულება "
            "ასისტენტით არ იგზავნება; მიმართეთ უშუალო ხელმძღვანელს, რომელიც საკითხს პროექტის "
            "პარტნიორთან შეათანხმებს.",
            "4.6",
        )


def check_unpaid_notice(session: Session, today: date, start: date) -> None:
    """Article 7.2: unpaid leave needs 10 working days of notice."""
    notice = count_working_days_between(today, start, session)
    if notice < UNPAID_NOTICE_DAYS:
        raise LeavePolicyError(
            f"უხელფასო შვებულების მოთხოვნა დაწყებამდე სულ მცირე {UNPAID_NOTICE_DAYS} სამუშაო დღით "
            f"ადრე უნდა წარდგეს, დღეს წარდგენისას კი მხოლოდ {max(notice, 0)} სამუშაო დღეა. "
            "აირჩიეთ უფრო გვიანი თარიღი.",
            "7.2",
        )


def check_unpaid_cap(session: Session, employee_id: str, start: date, days: int) -> None:
    """Article 7.1: at most 30 calendar days of unpaid leave per year."""
    booked = session.scalars(active_requests(session, employee_id).where(
        LeaveRequest.leave_type == "UNPAID",
        LeaveRequest.start_date.like(f"{start.year}-%"),
    )).all()
    booked_days = sum(r.days for r in booked)
    if booked_days + days > UNPAID_YEARLY_CAP:
        raise LeavePolicyError(
            f"წელიწადში ჯამურად არაუმეტეს {UNPAID_YEARLY_CAP} კალენდარული დღის უხელფასო შვებულებაა "
            f"შესაძლებელი. უკვე მოთხოვნილი/დამტკიცებულია {booked_days} დღე, ახალი მოთხოვნა {days} დღეა. "
            "მეტი დღისთვის საჭიროა მმართველი პარტნიორის თანხმობა ადამიანური რესურსების სამსახურის მეშვეობით.",
            "7.1",
        )


def check_balance(lt: LeaveType, available: Optional[int], requested: int) -> None:
    """Articles 5.1 and 6.4: the request must fit the remaining balance. None = untracked type."""
    if available is None or available >= requested:
        return
    if lt.code == "SICK":
        raise LeavePolicyError(
            f"ანაზღაურებადი ავადმყოფობის დღეებიდან დარჩენილია {available}, მოთხოვნილია {requested}. "
            "ასეთ მოთხოვნას ასისტენტი არ ქმნის: მიმართეთ ადამიანური რესურსების სამსახურს, რომელიც "
            "აღრიცხვასა და ანაზღაურების პირობებს ინდივიდუალურად განსაზღვრავს.",
            "6.4",
        )
    raise LeavePolicyError(
        f"ბალანსი არ არის საკმარისი: ხელმისაწვდომია {available} დღე, მოთხოვნილია {requested}. "
        "შეგიძლიათ აირჩიოთ უფრო მოკლე პერიოდი ან სხვა სახის შვებულება.",
        "5.1",
    )


# --------------------------------------------------------------------------- #
# Everything the assistant must check before filing a request (Article 12.3)
# --------------------------------------------------------------------------- #
def check_assistant_request(
    session: Session,
    emp: Employee,
    lt: LeaveType,
    start: date,
    end: date,
    days: int,
    today: date,
) -> None:
    check_current_year(start, end, today)
    check_no_overlap(session, emp.employee_id, start, end)

    if lt.code == "ANNUAL":
        check_probation(emp, today)
        check_max_duration(days)
        check_annual_notice(session, today, start, days)
        check_restricted_period(emp, start, end)

    if lt.code == "UNPAID":
        check_unpaid_notice(session, today, start)
        check_unpaid_cap(session, emp.employee_id, start, days)
