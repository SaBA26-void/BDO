from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from src.database import PublicHoliday

def get_public_holidays(session: Session) -> set:
    """Return set of holiday date strings ('YYYY-MM-DD')."""
    holidays = session.query(PublicHoliday.date).all()
    return {h.date for h in holidays}

def calculate_working_days(start_date_str: str, end_date_str: str, session: Session) -> int:
    """Calculate working days excluding weekends and public holidays."""
    start = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end = datetime.strptime(end_date_str, "%Y-%m-%d").date()

    if end < start:
        raise ValueError("End date cannot be earlier than start date.")

    holidays = get_public_holidays(session)
    curr = start
    working_days = 0

    while curr <= end:
        # weekday <5 means mon to fri and not in holidays
        if curr.weekday() < 5 and curr.strftime("%Y-%m-%d") not in holidays:
            working_days += 1
        curr += timedelta(days=1)

    return working_days