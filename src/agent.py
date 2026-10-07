"""
Georgian AI Assistant Agent (Northstar Services)
Routes Georgian messages for one logged-in employee to the policy RAG engine or to the
leave MCP server. Scope follows Article 12 of the leave policy: policy questions, the
employee's own balance, and new ANNUAL / SICK / UNPAID requests after explicit confirmation.
"""

import asyncio
import json
import re
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List

from fastmcp import Client

from src.rag import PolicyRAGEngine

# Order matters: UNPAID wording contains the ANNUAL keyword "ანაზღაურებადი",
# and ANNUAL keywords are generic, so specific types are checked first.
LEAVE_TYPE_KEYWORDS = {
    "UNPAID": ["უანაზღაურებ", "არაანაზღაურებ", "ანაზღაურების გარეშე", "უხელფასო"],
    "SICK": ["ავადმყოფობ", "ბიულეტენ", "ექიმ", "ჯანმრთელობ", "ავად"],
    "STUDY": ["სასწავლო", "საგამოცდო", "გამოცდ", "უნივერსიტეტ", "ტრენინგ"],
    "BEREAVEMENT": ["გლოვ", "დაკრძალვ", "გარდაცვალ"],
    "PARENTAL": ["მშობლის", "დედობ", "მამობ", "დეკრეტ", "ბავშვის მოვლ", "შვილად აყვან"],
    "ANNUAL": ["ანაზღაურებადი", "წლიური", "ყოველწლიური", "ჩვეულებრივი", "კუთვნილი", "დასვენებ"],
}
DEFAULT_LEAVE_TYPE = "ANNUAL"
CALLER_ROLE = "employee"
ASSISTANT_LEAVE_TYPES = {"ANNUAL", "SICK", "UNPAID"}

# Article 12.2: explain the rule and redirect instead of creating the request.
HR_ONLY_RULES = {
    "BEREAVEMENT": (
        "8",
        "გლოვის შვებულება: ახლო ოჯახის წევრის გარდაცვალებისას არაუმეტეს 3 სამუშაო დღე, სხვა "
        "ნათესავისთვის 1 სამუშაო დღე თითო შემთხვევაზე. გამოიყენება გარდაცვალებიდან 30 კალენდარული "
        "დღის განმავლობაში; წინასწარი შეტყობინება საჭირო არ არის. მოთხოვნა წარადგინეთ HR პორტალით ან "
        "ადამიანური რესურსების სამსახურის მეშვეობით, შვებულების პირველი დღიდან არაუგვიანეს 2 სამუშაო "
        "დღისა, და მიუთითეთ ნათესაური კავშირი და გარდაცვალების თარიღი.",
    ),
    "STUDY": (
        "9",
        "სასწავლო და საგამოცდო შვებულება: წელიწადში არაუმეტეს 5 სამუშაო დღე იმ კვალიფიკაციის "
        "გამოცდებისთვის, რომელიც თქვენს დამტკიცებულ სწავლის გეგმაშია — გამოცდის დღე და მის წინ "
        "არაუმეტეს 1 დღე მოსამზადებლად. მოთხოვნა წარადგინეთ HR პორტალით ან HR-ის მეშვეობით სულ მცირე "
        "10 სამუშაო დღით ადრე და მიუთითეთ გამოცდის დასახელება და თარიღი.",
    ),
    "PARENTAL": (
        "10",
        "მშობლის შვებულება (დედობის, ბავშვის მოვლის, მამობის, შვილად აყვანის) HR პორტალით ან "
        "ასისტენტით არ წარდგება. მიმართეთ პირდაპირ ადამიანური რესურსების სამსახურს არაუგვიანეს 8 "
        "კვირით ადრე სავარაუდო დაწყებამდე; HR განსაზღვრავს ხანგრძლივობას, ანაზღაურებასა და დოკუმენტებს.",
    ),
}

BALANCE_KEYWORDS = [
    "ბალანს", "ნაშთ", "დამრჩა", "დამრჩენია", "მაქვს დარჩენილი", "დარჩენილი მაქვს",
]
# Explicit action phrasing only; a bare "შვებულება" is usually a policy question.
CREATE_KEYWORDS = [
    "მინდა შვებულება", "მინდა ავიღო", "ავიღო", "ავიღებ", "მოვითხოვ", "მოთხოვნის შექმნა",
    "დამიფორმე", "გამიფორმე", "გაფორმება", "დაარეგისტრირე", "დარეგისტრირება",
    "შვებულების აღება", "შვებულებაში გასვლა", "გავალ შვებულებაში", "მჭირდება შვებულება",
]
WANT_WORDS = ["მინდა", "მჭირდება"]

CONFIRM_WORDS = {"კი", "დიახ"}
DECLINE_WORDS = {"არა", "არ მინდა", "გაუქმება", "გააუქმე"}

DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
EMPLOYEE_ALIAS_PATTERN = re.compile(r"EMP(\d{1,3})")

DAY_UNIT_KA = {"calendar": "კალენდარული დღე", "working": "სამუშაო დღე"}
LEAVE_POLICY_FILE = "Leave_and_Absence_Policy_v4.0.docx"


def resolve_employee_alias(raw_id: str) -> str:
    """Normalize a typed ID: 'e1001' -> 'E1001', fixed alias 'EMP001' -> 'E1001'."""
    employee_id = raw_id.strip().upper()
    match = EMPLOYEE_ALIAS_PATTERN.fullmatch(employee_id)
    if match:
        return f"E{1000 + int(match.group(1))}"
    return employee_id


def _normalize_answer(text: str) -> str:
    return re.sub(r"[\s„“\"'.,!?]+", " ", text).strip().lower()


class GeorgianAIAssistant:
    def __init__(
        self,
        client: Client,
        employee_id: str,
        employee_name: str,
        leave_types: Dict[str, Dict[str, Any]],
        doc_dir: Optional[str] = None,
    ):
        self.client = client
        self.employee_id = employee_id
        self.employee_name = employee_name
        self.leave_types = leave_types
        self.doc_dir = doc_dir
        self._rag_engine: Optional[PolicyRAGEngine] = None
        self._draft: Optional[Dict[str, Any]] = None
        self._awaiting_dates_for: Optional[str] = None

    @classmethod
    async def login(cls, client: Client, raw_id: str, doc_dir: Optional[str] = None) -> Optional["GeorgianAIAssistant"]:
        """Resolve the typed ID to an existing employee via the MCP server; None if unknown."""
        employee_id = resolve_employee_alias(raw_id)
        if not employee_id:
            return None
        balance = await call_tool(
            client, "get_leave_balance",
            caller_id=employee_id, caller_role=CALLER_ROLE, employee_id=employee_id,
        )
        if not balance.get("success"):
            return None
        types = await call_tool(client, "list_leave_types")
        leave_types = {lt["code"]: lt for lt in types.get("leave_types", [])}
        return cls(client, balance["employee_id"], balance["employee_name"], leave_types, doc_dir)

    async def _call(self, name: str, **arguments: Any) -> Dict[str, Any]:
        """Call a leave tool as the logged-in employee; the server enforces the employee role."""
        return await call_tool(
            self.client, name, caller_id=self.employee_id, caller_role=CALLER_ROLE, **arguments
        )

    @property
    def rag_engine(self) -> PolicyRAGEngine:
        # Built lazily: it needs GEMINI_API_KEY and embeds documents, which leave tools don't need.
        if self._rag_engine is None:
            self._rag_engine = PolicyRAGEngine(self.doc_dir)
        return self._rag_engine

    def leave_type_name(self, code: str) -> str:
        return self.leave_types.get(code, {}).get("name", code)

    def day_unit_label(self, code: str) -> str:
        return DAY_UNIT_KA.get(self.leave_types.get(code, {}).get("day_unit"), "დღე")

    # ------------------------------------------------------------------ #
    # Intent classification and entity extraction
    # ------------------------------------------------------------------ #
    @staticmethod
    def classify_intent(message: str) -> str:
        """Classify a message as POLICY_QA, CHECK_BALANCE or CREATE_LEAVE_REQUEST."""
        msg = message.lower()

        if any(w in msg for w in BALANCE_KEYWORDS):
            return "CHECK_BALANCE"

        if (
            any(w in msg for w in CREATE_KEYWORDS)
            or ("შვებულ" in msg and any(w in msg for w in WANT_WORDS))
            or ("შვებულ" in msg and DATE_PATTERN.search(msg))
        ):
            return "CREATE_LEAVE_REQUEST"

        return "POLICY_QA"

    @staticmethod
    def extract_leave_type(message: str) -> Optional[str]:
        msg = message.lower()
        for code, keywords in LEAVE_TYPE_KEYWORDS.items():
            if any(kw in msg for kw in keywords):
                return code
        return None

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

    # ------------------------------------------------------------------ #
    # Intent handlers
    # ------------------------------------------------------------------ #
    async def _handle_policy(self, message: str) -> Tuple[str, Dict[str, Any]]:
        try:
            rag_res = await asyncio.to_thread(lambda: self.rag_engine.answer_question(message))
        except Exception as e:
            return f"❌ პოლიტიკის დოკუმენტებში ძებნა ვერ მოხერხდა: {e}", {"success": False, "error": str(e)}

        answer = rag_res["answer"]
        if rag_res["found"] and "წყარო" not in answer and rag_res["sources"]:
            answer += f"\n\n[წყარო: {rag_res['sources'][0]['source_file']}]"
        return answer, rag_res

    async def _handle_balance(self) -> Tuple[str, Dict[str, Any]]:
        year = datetime.now().year
        data = await self._call("get_leave_balance", employee_id=self.employee_id, year=year)
        if not data.get("success"):
            return f"❌ შეცდომა ბალანსის შემოწმებისას: {data.get('error')}", data

        balances = data.get("balances", [])
        if not balances:
            return f"ℹ️ {year} წლის შვებულების ბალანსი ვერ მოიძებნა ({self.employee_name}, {self.employee_id}).", data

        lines = [f"📊 შვებულების ბალანსი {year} წლისთვის — {self.employee_name} ({self.employee_id}):"]
        for b in balances:
            code = b["leave_type"]
            total = f"{b['total_days']}"
            if b.get("carried_over_days"):
                total += f", მ.შ. გადმოტანილი {b['carried_over_days']}"
            lines.append(
                f"• {self.leave_type_name(code)}: ხელმისაწვდომია {max(b['remaining_days'], 0)} "
                f"{self.day_unit_label(code)} (კუთვნილი: {total}; დამტკიცებული: {b['used_days']}; "
                f"განხილვის პროცესში: {b['pending_days']})"
            )
        return "\n".join(lines), data

    async def _handle_create(self, message: str, fallback_type: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
        lt_code = self.extract_leave_type(message) or fallback_type or DEFAULT_LEAVE_TYPE
        lt_name = self.leave_type_name(lt_code)

        if lt_code not in ASSISTANT_LEAVE_TYPES:
            article, rule = HR_ONLY_RULES[lt_code]
            reply = (
                f"ℹ️ ამ სახის მოთხოვნას („{lt_name}“) HR ასისტენტი არ ქმნის.\n\n{rule}\n\n"
                f"📖 {LEAVE_POLICY_FILE}, მუხლი {article} (და მუხლი 12.3)."
            )
            return reply, {"success": False, "created": False, "leave_type": lt_code, "article": article}

        start_date, end_date = self.extract_dates(message)
        if not start_date:
            self._awaiting_dates_for = lt_code
            reply = (
                f"📅 მოთხოვნისთვის („{lt_name}“) მიუთითეთ პერიოდი ფორმატით YYYY-MM-DD, "
                f"მაგალითად: „2026-11-02-დან 2026-11-06-მდე“."
            )
            return reply, {"success": False, "error": "missing_dates", "leave_type": lt_code}

        preview = await self._call(
            "create_leave_request",
            employee_id=self.employee_id, leave_type=lt_code,
            start_date=start_date, end_date=end_date, dry_run=True,
        )
        if not preview.get("success"):
            return self._refusal(preview), preview

        self._draft = preview
        reply = (
            "📝 გთხოვთ, გადაამოწმოთ მოთხოვნა:\n"
            f"• თანამშრომელი: {self.employee_name} ({self.employee_id})\n"
            f"• შვებულების სახე: {lt_name}\n"
            f"• პერიოდი: {start_date} – {end_date}\n"
            f"• დღეების რაოდენობა: {preview['requested_days']} {self.day_unit_label(lt_code)}\n"
            f"• ბალანსი მოთხოვნის შემდეგ: {preview['remaining_days_after']}\n\n"
            "შევქმნა მოთხოვნა? დასადასტურებლად დაწერეთ „კი“ ან „დიახ“, გასაუქმებლად – „არა“."
        )
        return reply, preview

    async def _submit_draft(self, draft: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        data = await self._call(
            "create_leave_request",
            employee_id=self.employee_id, leave_type=draft["leave_type"],
            start_date=draft["start_date"], end_date=draft["end_date"],
            reason="შექმნილია HR ასისტენტით, თანამშრომლის დადასტურებით",
        )
        if not data.get("success"):
            return self._refusal(data), data

        lt_code = data["leave_type"]
        reply = (
            "✅ მოთხოვნა შეიქმნა.\n"
            f"• მოთხოვნის ID: {data['request_id']}\n"
            f"• შვებულების სახე: {self.leave_type_name(lt_code)}\n"
            f"• პერიოდი: {data['start_date']} – {data['end_date']} "
            f"({data['requested_days']} {self.day_unit_label(lt_code)})\n"
            "• სტატუსი: განხილვის პროცესში — ეს შვებულების დამტკიცებას არ ნიშნავს (მუხლი 12.2).\n"
            f"• დარჩენილი ბალანსი: {data['remaining_days']}"
        )
        return reply, data

    @staticmethod
    def _refusal(data: Dict[str, Any]) -> str:
        reply = f"❌ მოთხოვნა ვერ შეიქმნა: {data.get('error')}"
        if data.get("article"):
            reply += f"\n📖 {LEAVE_POLICY_FILE}, მუხლი {data['article']}."
        return reply

    # ------------------------------------------------------------------ #
    # Router
    # ------------------------------------------------------------------ #
    async def _route(self, message: str) -> Dict[str, Any]:
        intent = self.classify_intent(message)

        awaiting, self._awaiting_dates_for = self._awaiting_dates_for, None
        if awaiting and intent != "CHECK_BALANCE" and DATE_PATTERN.search(message):
            intent = "CREATE_LEAVE_REQUEST"

        if intent == "CHECK_BALANCE":
            reply, data = await self._handle_balance()
        elif intent == "CREATE_LEAVE_REQUEST":
            reply, data = await self._handle_create(message, fallback_type=awaiting)
        else:
            reply, data = await self._handle_policy(message)
        return {"intent": intent, "reply": reply, "data": data}

    async def process_message(self, message: str) -> Dict[str, Any]:
        """Handle one message for the logged-in employee and return the reply."""
        if self._draft is None:
            return await self._route(message)

        draft, self._draft = self._draft, None
        answer = _normalize_answer(message)
        if answer in CONFIRM_WORDS:
            reply, data = await self._submit_draft(draft)
            return {"intent": "CONFIRM_LEAVE_REQUEST", "reply": reply, "data": data}
        if answer in DECLINE_WORDS:
            return {
                "intent": "DECLINE_LEAVE_REQUEST",
                "reply": "მოთხოვნა არ შეიქმნა.",
                "data": {"success": False, "created": False},
            }

        result = await self._route(message)
        result["reply"] = "ℹ️ წინა მოთხოვნა არ შეიქმნა, რადგან „კი“ არ დაწერეთ.\n\n" + result["reply"]
        return result


async def call_tool(client: Client, name: str, **arguments: Any) -> Dict[str, Any]:
    """Call an MCP tool; the leave tools return a JSON string."""
    result = await client.call_tool(name, arguments)
    return json.loads(result.content[0].text)
