from datetime import date, datetime, timedelta
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from src.database import Employee, LeaveType, LeaveEntitlement, LeaveRequest
from src.service.calendar_service import calculate_working_days, count_working_days_between
from src.service.session import with_session

ASSISTANT_CHANNEL = "assistant"
ASSISTANT_LEAVE_TYPES = {"ANNUAL", "SICK", "UNPAID"}
ACTIVE_STATUSES = ("PENDING", "APPROVED")
# No yearly entitlement: HR sets the duration case by case (Articles 8 and 10).
UNTRACKED_LEAVE_TYPES = {"BEREAVEMENT", "PARENTAL"}

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

ANNUAL_MAX_DAYS = 15
UNPAID_YEARLY_CAP = 30
UNPAID_NOTICE_DAYS = 10
# (start month, start day, end month, end day), inclusive.
AUDIT_RESTRICTED_PERIODS = [(12, 1, 12, 20), (1, 15, 3, 15)]
AUDIT_DEPARTMENT_CODE = "AUD"


class LeavePolicyError(ValueError):
    """A request the assistant may not create, with the policy article that forbids it."""

    def __init__(self, message: str, article: str):
        super().__init__(message)
        self.article = article


def _parse_request_id(request_id: str) -> Any:
    try:
        return int(str(request_id).upper().replace("REQ", ""))
    except ValueError:
        return request_id


def _entitlement_for(session: Session, req: LeaveRequest) -> Optional[LeaveEntitlement]:
    return session.scalar(select(LeaveEntitlement).where(
        LeaveEntitlement.employee_id == req.employee_id,
        LeaveEntitlement.leave_type == req.leave_type,
        LeaveEntitlement.year == int(req.start_date[:4]),
    ))


def _active_requests(session: Session, employee_id: str):
    return select(LeaveRequest).where(
        LeaveRequest.employee_id == employee_id,
        func.upper(LeaveRequest.status).in_(ACTIVE_STATUSES),
    )


def _in_audit_restricted_period(start: date, end: date) -> bool:
    curr = start
    while curr <= end:
        md = (curr.month, curr.day)
        if any((m1, d1) <= md <= (m2, d2) for m1, d1, m2, d2 in AUDIT_RESTRICTED_PERIODS):
            return True
        curr += timedelta(days=1)
    return False


def _check_assistant_policy(
    session: Session,
    emp: Employee,
    lt: LeaveType,
    start: date,
    end: date,
    days: int,
    today: date,
) -> None:
    """Raise LeavePolicyError for anything Article 12.3 forbids the assistant to create."""
    code = lt.code

    if start.year != today.year or end.year != today.year:
        raise LeavePolicyError(
            f"HR ასისტენტი ქმნის მოთხოვნებს მხოლოდ მიმდინარე, {today.year} წლის თარიღებზე. "
            "მომდევნო წლის მოთხოვნა HR პორტალით შეიძლება მიმდინარე წლის 1 დეკემბრიდან; "
            "წლებს შორის გადამავალი შვებულებისთვის თითოეულ წელზე ცალკე მოთხოვნაა საჭირო (მუხლი 2.1).",
            "12.3",
        )

    overlap = session.scalar(_active_requests(session, emp.employee_id).where(
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

    if code == "ANNUAL":
        if emp.probation_end_date and today.isoformat() <= emp.probation_end_date:
            raise LeavePolicyError(
                f"გამოსაცდელი ვადა ({emp.probation_end_date}-ის ჩათვლით) ჯერ არ დასრულებულა, ამიტომ "
                "ყოველწლიური შვებულების გამოყენება ჯერ არ შეიძლება. ავადმყოფობისა და უხელფასო შვებულება "
                "ხელმისაწვდომია. გამონაკლისი (არაუმეტეს 2 სამუშაო დღე) მხოლოდ ადამიანური რესურსების "
                "სამსახურთან პირდაპირ შეთანხმდება.",
                "4.3",
            )

        if days > ANNUAL_MAX_DAYS:
            raise LeavePolicyError(
                f"ერთი მოთხოვნით შეიძლება არაუმეტეს {ANNUAL_MAX_DAYS} სამუშაო დღის ყოველწლიური შვებულება "
                f"(მოთხოვნილია {days}). უფრო ხანგრძლივ შვებულებას სჭირდება პარტნიორის ან დირექტორის "
                "წერილობითი თანხმობა და წარდგება უშუალო ხელმძღვანელის მეშვეობით.",
                "4.5",
            )

        required = 5 if days <= 5 else 15
        notice = count_working_days_between(today, start, session)
        if notice < required:
            raise LeavePolicyError(
                f"{days} სამუშაო დღის ყოველწლიურ შვებულებას სჭირდება სულ მცირე {required} სამუშაო დღით "
                f"ადრე შეტყობინება, დღეს წარდგენისას კი მხოლოდ {max(notice, 0)} სამუშაო დღეა. "
                "აირჩიეთ უფრო გვიანი თარიღი, ან გადაუდებელ შემთხვევაში მიმართეთ უშუალო ხელმძღვანელს.",
                "4.4",
            )

        if emp.department_code == AUDIT_DEPARTMENT_CODE and _in_audit_restricted_period(start, end):
            raise LeavePolicyError(
                "აუდიტისა და მარწმუნებელი მომსახურების დეპარტამენტისთვის 1–20 დეკემბერი და "
                "15 იანვარი – 15 მარტი შეზღუდული პერიოდებია. ამ დღეებზე ყოველწლიური შვებულება "
                "ასისტენტით არ იგზავნება; მიმართეთ უშუალო ხელმძღვანელს, რომელიც საკითხს პროექტის "
                "პარტნიორთან შეათანხმებს.",
                "4.6",
            )

    if code == "UNPAID":
        notice = count_working_days_between(today, start, session)
        if notice < UNPAID_NOTICE_DAYS:
            raise LeavePolicyError(
                f"უხელფასო შვებულების მოთხოვნა დაწყებამდე სულ მცირე {UNPAID_NOTICE_DAYS} სამუშაო დღით "
                f"ადრე უნდა წარდგეს, დღეს წარდგენისას კი მხოლოდ {max(notice, 0)} სამუშაო დღეა. "
                "აირჩიეთ უფრო გვიანი თარიღი.",
                "7.2",
            )

        booked = session.scalars(_active_requests(session, emp.employee_id).where(
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
    if from_assistant and lt.code not in ASSISTANT_LEAVE_TYPES:
        article, message = HR_ONLY_LEAVE_TYPES.get(
            lt.code, ("12.3", "ამ სახის შვებულების მოთხოვნას HR ასისტენტი არ ქმნის. მიმართეთ HR-ს.")
        )
        raise LeavePolicyError(message, article)

    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("თარიღები უნდა იყოს ფორმატით YYYY-MM-DD.")
    if end < start:
        raise ValueError("დასრულების თარიღი დაწყების თარიღზე ადრე ვერ იქნება.")

    if lt.day_unit == "calendar":
        requested_days = (end - start).days + 1
    else:
        requested_days = calculate_working_days(start_date, end_date, session)
    if requested_days <= 0:
        raise LeavePolicyError("მოთხოვნილ პერიოდში სამუშაო დღე არ არის (შაბათ-კვირა ან უქმე დღეებია).", "2.2")

    today = date.today()
    if from_assistant:
        _check_assistant_policy(session, emp, lt, start, end, requested_days, today)

    ent = session.scalar(
        select(LeaveEntitlement).where(
            LeaveEntitlement.employee_id == employee_id,
            LeaveEntitlement.leave_type == lt.code,
            LeaveEntitlement.year == start.year
        )
    )
    tracked = ent is not None or lt.code not in UNTRACKED_LEAVE_TYPES
    available = ent.remaining_days if ent else 0
    if tracked and available < requested_days:
        if lt.code == "SICK":
            raise LeavePolicyError(
                f"ანაზღაურებადი ავადმყოფობის დღეებიდან დარჩენილია {available}, მოთხოვნილია {requested_days}. "
                "ასეთ მოთხოვნას ასისტენტი არ ქმნის: მიმართეთ ადამიანური რესურსების სამსახურს, რომელიც "
                "აღრიცხვასა და ანაზღაურების პირობებს ინდივიდუალურად განსაზღვრავს.",
                "6.4",
            )
        raise LeavePolicyError(
            f"ბალანსი არ არის საკმარისი: ხელმისაწვდომია {available} დღე, მოთხოვნილია {requested_days}. "
            "შეგიძლიათ აირჩიოთ უფრო მოკლე პერიოდი ან სხვა სახის შვებულება.",
            "5.1",
        )

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
            "remaining_days_after": available - requested_days if tracked else None,
        }

    last_req = session.scalar(
        select(LeaveRequest).order_by(LeaveRequest.request_id.desc()).limit(1)
    )
    req_id = (last_req.request_id + 1) if last_req else 1
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    new_request = LeaveRequest(
        request_id=req_id,
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
        created_at=now_str
    )
    session.add(new_request)

    if ent:
        ent.pending_days += requested_days
        ent.remaining_days -= requested_days

    session.commit()

    return {
        "success": True,
        "request_id": req_id,
        "leave_type": lt.code,
        "start_date": start_date,
        "end_date": end_date,
        "requested_days": requested_days,
        "day_unit": lt.day_unit,
        "status": "PENDING",
        "created_via": created_via,
        "remaining_days": ent.remaining_days if ent else None
    }


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

    requests = session.scalars(query).all()
    return [
        {
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

    req = session.scalar(select(LeaveRequest).where(LeaveRequest.request_id == _parse_request_id(request_id)))
    if not req:
        raise ValueError(f"Leave request ID '{request_id}' not found.")

    if req.status.upper() != "PENDING":
        raise ValueError(f"Request '{request_id}' is already {req.status.upper()}.")
    if reviewer_id and req.employee_id == reviewer_id:
        raise PermissionError("A reviewer cannot approve or reject their own leave request.")

    ent = _entitlement_for(session, req)
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
    query = select(LeaveRequest).where(LeaveRequest.request_id == _parse_request_id(request_id))
    if employee_id:
        query = query.where(LeaveRequest.employee_id == employee_id)

    req = session.scalar(query)
    if not req:
        raise ValueError(f"Leave request ID '{request_id}' not found.")

    current = req.status.upper()
    if current in ("CANCELLED", "REJECTED"):
        raise ValueError(f"Request '{request_id}' is already {current}.")

    ent = _entitlement_for(session, req)
    if ent:
        if current == "PENDING":
            ent.pending_days -= req.days
            ent.remaining_days += req.days
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
