"""Understanding a message: what the employee wants, which leave type, which dates."""

import re
from datetime import datetime
from typing import List, Optional, Tuple

from src.assistant.keywords import (
    BALANCE_KEYWORDS,
    CREATE_KEYWORDS,
    DATE_PATTERN,
    EMPLOYEE_ALIAS_PATTERN,
    LEAVE_TYPE_KEYWORDS,
    QUESTION_WORDS,
    WANT_WORDS,
)

POLICY_QA = "POLICY_QA"
CHECK_BALANCE = "CHECK_BALANCE"
CREATE_LEAVE_REQUEST = "CREATE_LEAVE_REQUEST"


def classify_intent(message: str) -> str:
    """Classify a message as POLICY_QA, CHECK_BALANCE or CREATE_LEAVE_REQUEST."""
    msg = message.lower()

    if any(w in msg for w in BALANCE_KEYWORDS):
        return CHECK_BALANCE

    # "რამდენი დღით ადრე უნდა მოვითხოვო?" asks about the rules; a request names its dates.
    has_date = DATE_PATTERN.search(msg) is not None
    looks_like_question = "?" in msg or msg.split(" ", 1)[0] in QUESTION_WORDS
    if not has_date and looks_like_question:
        return POLICY_QA

    mentions_leave = "შვებულ" in msg
    if (
        any(w in msg for w in CREATE_KEYWORDS)
        or (mentions_leave and any(w in msg for w in WANT_WORDS))
        or (mentions_leave and has_date)
    ):
        return CREATE_LEAVE_REQUEST

    return POLICY_QA


def extract_leave_type(message: str) -> Optional[str]:
    msg = message.lower()
    for code, keywords in LEAVE_TYPE_KEYWORDS.items():
        if any(kw in msg for kw in keywords):
            return code
    return None


def extract_dates(message: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract (start, end) YYYY-MM-DD dates. A single date means a one-day leave."""
    valid: List[str] = []
    for d in DATE_PATTERN.findall(message):
        try:
            datetime.strptime(d, "%Y-%m-%d")
            valid.append(d)
        except ValueError:
            continue

    if not valid:
        return None, None
    if len(valid) == 1:
        return valid[0], valid[0]
    start, end = sorted(valid[:2])
    return start, end


def has_date(message: str) -> bool:
    return DATE_PATTERN.search(message) is not None


def normalize_answer(text: str) -> str:
    """Lower-case a short yes/no reply and strip punctuation and quotes."""
    return re.sub(r"[\s„“\"'.,!?]+", " ", text).strip().lower()


def resolve_employee_alias(raw_id: str) -> str:
    """Normalize a typed ID: 'e1001' -> 'E1001', fixed alias 'EMP001' -> 'E1001'."""
    employee_id = raw_id.strip().upper()
    match = EMPLOYEE_ALIAS_PATTERN.fullmatch(employee_id)
    if match:
        return f"E{1000 + int(match.group(1))}"
    return employee_id
