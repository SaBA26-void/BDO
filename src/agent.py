"""
Georgian AI Assistant Agent (Northstar Services)
Integrates Intent Classification, Entity Extraction, MCP Leave Tools, and Policy RAG.
"""

import re
import json
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List

from src.rag import PolicyRAGEngine
from src.service.employee_service import get_employee
from mcp_server.tools import (
    create_leave_request,
    get_leave_balance,
    list_leave_requests,
    cancel_leave_request,
    list_leave_types,
)

# Order matters: more specific types are checked before ANNUAL, whose keywords are generic.
LEAVE_TYPE_KEYWORDS = {
    "UNPAID": ["უანაზღაურებელი", "ანაზღაურების გარეშე", "უხელფასო"],
    "SICK": ["ავადმყოფობ", "ბიულეტენ", "ექიმ", "ჯანმრთელობ", "ავად"],
    "STUDY": ["სასწავლო", "საგამოცდო", "გამოცდ", "უნივერსიტეტ", "ტრენინგ"],
    "BEREAVEMENT": ["გლოვ", "დაკრძალვ", "გარდაცვალ"],
    "ANNUAL": ["ანაზღაურებადი", "წლიური", "ყოველწლიური", "ჩვეულებრივი", "კუთვნილი", "დასვენებ"],
}
DEFAULT_LEAVE_TYPE = "ANNUAL"

CANCEL_KEYWORDS = ["გაუქმება", "გავაუქმო", "გააუქმე", "გაუქმდეს", "წაშალე", "წაშლა"]
LIST_KEYWORDS = [
    "ჩემი მოთხოვნები", "მოთხოვნების სია", "მოთხოვნების ისტორია", "ისტორია",
    "სტატუსი", "ჩემი შვებულებები", "რა მოთხოვნები მაქვს",
]
BALANCE_KEYWORDS = [
    "ბალანს", "ნაშთ", "დამრჩა", "დამრჩენია", "მაქვს დარჩენილი", "დარჩენილი მაქვს",
]
# Explicit action phrasing only; a bare "შვებულება" is usually a policy question.
CREATE_KEYWORDS = [
    "მინდა შვებულება", "მინდა ავიღო", "ავიღო", "ავიღებ", "მოვითხოვ", "მოთხოვნის შექმნა",
    "დამიფორმე", "გამიფორმე", "გაფორმება", "დაარეგისტრირე", "დარეგისტრირება",
    "შვებულების აღება", "შვებულებაში გასვლა", "გავალ შვებულებაში", "მჭირდება შვებულება",
]

DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
REQUEST_ID_PATTERN = re.compile(r"(?:REQ|#|ID[:\s]*)?\s*(\d+)", re.IGNORECASE)

STATUS_KA = {
    "PENDING": "განხილვის პროცესში",
    "APPROVED": "დამტკიცებული",
    "REJECTED": "უარყოფილი",
    "CANCELLED": "გაუქმებული",
}


class GeorgianAIAssistant:
    def __init__(self, doc_dir: Optional[str] = None):
        self.doc_dir = doc_dir
        self._rag_engine: Optional[PolicyRAGEngine] = None
        self.leave_type_names = self._load_leave_type_names()

    @property
    def rag_engine(self) -> PolicyRAGEngine:
        # Built lazily: it needs GEMINI_API_KEY and embeds documents, which leave tools don't need.
        if self._rag_engine is None:
            self._rag_engine = PolicyRAGEngine(self.doc_dir)
        return self._rag_engine

    @staticmethod
    def _load_leave_type_names() -> Dict[str, str]:
        data = json.loads(list_leave_types())
        return {lt["code"]: lt["name"] for lt in data.get("leave_types", [])}

    def leave_type_name(self, code: str) -> str:
        return self.leave_type_names.get(code, code)

    # ------------------------------------------------------------------ #
    # Intent classification
    # ------------------------------------------------------------------ #
    def classify_intent(self, message: str) -> str:
        """Classify user query into actionable HR intents."""
        msg = message.lower()

        if any(w in msg for w in CANCEL_KEYWORDS):
            return "CANCEL_LEAVE_REQUEST"

        if any(w in msg for w in LIST_KEYWORDS):
            return "LIST_LEAVE_REQUESTS"

        if any(w in msg for w in BALANCE_KEYWORDS):
            return "CHECK_BALANCE"

        if any(w in msg for w in CREATE_KEYWORDS) or (
            "შვებულ" in msg and len(DATE_PATTERN.findall(msg)) >= 1
        ):
            return "CREATE_LEAVE_REQUEST"

        return "POLICY_QA"

    # ------------------------------------------------------------------ #
    # Entity extraction
    # ------------------------------------------------------------------ #
    def extract_leave_type(self, message: str) -> Tuple[str, str]:
        """Extract leave type code and Georgian display name from text."""
        msg = message.lower()
        for code, keywords in LEAVE_TYPE_KEYWORDS.items():
            if any(kw in msg for kw in keywords):
                return code, self.leave_type_name(code)
        return DEFAULT_LEAVE_TYPE, self.leave_type_name(DEFAULT_LEAVE_TYPE)

    @staticmethod
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

    @staticmethod
    def extract_request_id(message: str) -> Optional[str]:
        """Extract a leave request ID, ignoring digits that belong to dates."""
        cleaned = DATE_PATTERN.sub(" ", message)
        match = REQUEST_ID_PATTERN.search(cleaned)
        return match.group(1) if match else None

    # ------------------------------------------------------------------ #
    # Intent handlers
    # ------------------------------------------------------------------ #
    def _handle_balance(self, employee_id: str, emp_name: str) -> Tuple[str, Dict[str, Any]]:
        year = datetime.now().year
        data = json.loads(get_leave_balance(employee_id=employee_id, year=year))
        if not data.get("success"):
            return f"❌ შეცდომა ბალანსის შემოწმებისას: {data.get('error')}", data

        balances = data.get("balances", [])
        if not balances:
            return f"ℹ️ {emp_name}-ისთვის {year} წლის შვებულების ბალანსი ვერ მოიძებნა.", data

        lines = [f"📊 {emp_name}-ის შვებულების ბალანსი {year} წლისთვის:"]
        for b in balances:
            lines.append(
                f"• {self.leave_type_name(b['leave_type'])}: დარჩენილია {b['remaining_days']} დღე "
                f"(სულ: {b['entitled_days']}, გამოყენებული: {b['used_days']}, "
                f"განხილვაში: {b['pending_days']})"
            )
        return "\n".join(lines), data

    def _handle_create(self, message: str, employee_id: str, emp_name: str) -> Tuple[str, Dict[str, Any]]:
        lt_code, lt_name = self.extract_leave_type(message)
        start_date, end_date = self.extract_dates(message)

        if not start_date:
            reply = (
                f"📅 {lt_name}-ის მოთხოვნის შესაქმნელად მიუთითეთ პერიოდი ფორმატით YYYY-MM-DD, "
                f"მაგალითად: „მინდა ავიღო შვებულება 2026-06-01-დან 2026-06-05-მდე“."
            )
            return reply, {"success": False, "error": "missing_dates", "leave_type": lt_code}

        data = json.loads(create_leave_request(
            employee_id=employee_id,
            leave_type=lt_code,
            start_date=start_date,
            end_date=end_date,
            reason=f"მოთხოვნილია AI ასისტენტის მეშვეობით: {message[:100]}",
        ))

        if not data.get("success"):
            return f"❌ მოთხოვნის შექმნა ვერ მოხერხდა: {data.get('error')}", data

        reply = (
            f"✅ შვებულების მოთხოვნა წარმატებით დარეგისტრირდა!\n\n"
            f"• თანამშრომელი: {emp_name}\n"
            f"• მოთხოვნის ID: {data['request_id']}\n"
            f"• შვებულების ტიპი: {lt_name}\n"
            f"• პერიოდი: {start_date} -დან {end_date} -მდე ({data['requested_days']} სამუშაო დღე)\n"
            f"• სტატუსი: {STATUS_KA.get(data['status'], data['status'])}\n"
            f"• დარჩენილი ბალანსი: {data['remaining_days']} დღე"
        )
        data.update({"leave_type": lt_code, "start_date": start_date, "end_date": end_date})
        return reply, data

    def _handle_list(self, employee_id: str, emp_name: str) -> Tuple[str, Dict[str, Any]]:
        data = json.loads(list_leave_requests(employee_id=employee_id))
        if not data.get("success"):
            return f"❌ მოთხოვნების ჩატვირთვა ვერ მოხერხდა: {data.get('error')}", data

        reqs = data.get("requests", [])
        if not reqs:
            return f"ℹ️ {emp_name}-ისთვის შვებულების მოთხოვნები ვერ მოიძებნა.", data

        lines = [f"📋 {emp_name}-ის შვებულების მოთხოვნები:"]
        for r in reqs:
            status = (r.get("status") or "").upper()
            lines.append(
                f"• ID: {r['request_id']} | {self.leave_type_name(r['leave_type'])} | "
                f"{r['start_date']} - {r['end_date']} ({r['days']} დღე) | "
                f"სტატუსი: {STATUS_KA.get(status, status)}"
            )
        return "\n".join(lines), data

    def _handle_cancel(self, message: str, employee_id: str) -> Tuple[str, Dict[str, Any]]:
        request_id = self.extract_request_id(message)
        if not request_id:
            reply = (
                "🔎 გასაუქმებლად მიუთითეთ მოთხოვნის ID, მაგალითად: „გააუქმე მოთხოვნა 12“. "
                "თქვენი მოთხოვნების სანახავად დაწერეთ „ჩემი მოთხოვნები“."
            )
            return reply, {"success": False, "error": "missing_request_id"}

        data = json.loads(cancel_leave_request(request_id=request_id, employee_id=employee_id))
        if not data.get("success"):
            return f"❌ მოთხოვნის გაუქმება ვერ მოხერხდა: {data.get('error')}", data

        return f"🗑️ მოთხოვნა ID {data['request_id']} წარმატებით გაუქმდა და ბალანსი აღდგა.", data

    # ------------------------------------------------------------------ #
    # Router
    # ------------------------------------------------------------------ #
    def process_message(self, message: str, employee_id: str = "E1001") -> Dict[str, Any]:
        """Process user message, execute mapped intent, and return clean response."""
        intent = self.classify_intent(message)

        if intent == "POLICY_QA":
            rag_res = self.rag_engine.answer_question(message)
            return {"intent": intent, "reply": rag_res["answer"], "data": rag_res}

        emp = get_employee(employee_id)
        if not emp:
            return {
                "intent": intent,
                "reply": f"❌ თანამშრომელი '{employee_id}' ვერ მოიძებნა.",
                "data": {"success": False, "error": "employee_not_found"},
            }
        # The DB tools expect the canonical ID (e.g. E1001), not aliases like EMP001.
        employee_id = emp["employee_id"]
        emp_name = emp["full_name"]

        if intent == "CHECK_BALANCE":
            reply, data = self._handle_balance(employee_id, emp_name)
        elif intent == "CREATE_LEAVE_REQUEST":
            reply, data = self._handle_create(message, employee_id, emp_name)
        elif intent == "LIST_LEAVE_REQUESTS":
            reply, data = self._handle_list(employee_id, emp_name)
        else:
            reply, data = self._handle_cancel(message, employee_id)

        return {"intent": intent, "reply": reply, "data": data}


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    assistant = GeorgianAIAssistant()
    text = " ".join(sys.argv[1:]) or "მაჩვენე ჩემი ბალანსი"
    result = assistant.process_message(text)
    print(f"[{result['intent']}]\n{result['reply']}")
