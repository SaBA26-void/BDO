"""
Georgian AI Assistant (Northstar Services).
Routes one logged-in employee's messages to the policy RAG engine or to the leave MCP server.
Scope follows Article 12 of the leave policy: policy questions, the employee's own balance,
and new requests for assistant-supported leave types after explicit confirmation.
"""

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from fastmcp import Client

from src.assistant import intents, messages
from src.assistant.keywords import CONFIRM_WORDS, DECLINE_WORDS
from src.rag import PolicyRAGEngine

CALLER_ROLE = "employee"
DEFAULT_LEAVE_TYPE = "ANNUAL"

Reply = Tuple[str, Dict[str, Any]]  # (text shown to the employee, raw data for tests/logging)


async def call_tool(client: Client, name: str, **arguments: Any) -> Dict[str, Any]:
    """Call an MCP tool; the leave tools return a JSON string."""
    result = await client.call_tool(name, arguments)
    return json.loads(result.content[0].text)


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
        self._draft: Optional[Dict[str, Any]] = None       # dry-run result waiting for "კი"
        self._awaiting_dates_for: Optional[str] = None     # leave type whose dates we asked for

    # ------------------------------------------------------------------ #
    # Setup
    # ------------------------------------------------------------------ #
    @classmethod
    async def login(cls, client: Client, raw_id: str, doc_dir: Optional[str] = None) -> Optional["GeorgianAIAssistant"]:
        """Resolve the typed ID to an existing employee via the MCP server; None if unknown."""
        employee_id = intents.resolve_employee_alias(raw_id)
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

    def _type_name(self, code: str) -> str:
        return messages.leave_type_name(self.leave_types, code)

    def _unit(self, code: str) -> str:
        return messages.day_unit_label(self.leave_types, code)

    def _assistant_can_file(self, code: str) -> bool:
        """Article 12.2: the leave_types table says which types the assistant may file."""
        return bool(self.leave_types.get(code, {}).get("assistant_supported"))

    # ------------------------------------------------------------------ #
    # Public entry point
    # ------------------------------------------------------------------ #
    async def process_message(self, message: str) -> Dict[str, Any]:
        """Handle one message for the logged-in employee and return the reply."""
        if self._draft is None:
            return await self._route(message)

        # A draft is waiting: the message is either a yes, a no, or something new.
        draft, self._draft = self._draft, None
        answer = intents.normalize_answer(message)
        if answer in CONFIRM_WORDS:
            reply, data = await self._submit_draft(draft)
            return {"intent": "CONFIRM_LEAVE_REQUEST", "reply": reply, "data": data}
        if answer in DECLINE_WORDS:
            return {
                "intent": "DECLINE_LEAVE_REQUEST",
                "reply": messages.DRAFT_DECLINED,
                "data": {"success": False, "created": False},
            }

        result = await self._route(message)
        result["reply"] = messages.DRAFT_DROPPED_PREFIX + result["reply"]
        return result

    async def _route(self, message: str) -> Dict[str, Any]:
        intent = intents.classify_intent(message)

        # If we just asked for dates and the employee sent some, treat it as the pending request.
        awaiting, self._awaiting_dates_for = self._awaiting_dates_for, None
        if awaiting and intent != intents.CHECK_BALANCE and intents.has_date(message):
            intent = intents.CREATE_LEAVE_REQUEST

        if intent == intents.CHECK_BALANCE:
            reply, data = await self._handle_balance()
        elif intent == intents.CREATE_LEAVE_REQUEST:
            reply, data = await self._handle_create(message, fallback_type=awaiting)
        else:
            reply, data = await self._handle_policy(message)
        return {"intent": intent, "reply": reply, "data": data}

    # ------------------------------------------------------------------ #
    # Intent handlers
    # ------------------------------------------------------------------ #
    async def _handle_policy(self, message: str) -> Reply:
        try:
            rag_result = await asyncio.to_thread(lambda: self.rag_engine.answer_question(message))
        except Exception as e:
            return messages.policy_error(e), {"success": False, "error": str(e)}
        return messages.policy_answer(rag_result), rag_result

    async def _handle_balance(self) -> Reply:
        year = datetime.now().year
        data = await self._call("get_leave_balance", employee_id=self.employee_id, year=year)
        if not data.get("success"):
            return messages.balance_error(data), data

        balances = data.get("balances", [])
        if not balances:
            return messages.balance_missing(year, self.employee_name, self.employee_id), data
        return messages.balance(year, self.employee_name, self.employee_id, balances, self.leave_types), data

    async def _handle_create(self, message: str, fallback_type: Optional[str] = None) -> Reply:
        code = intents.extract_leave_type(message) or fallback_type or DEFAULT_LEAVE_TYPE

        if not self._assistant_can_file(code):
            reply = messages.hr_only_redirect(code, self._type_name(code))
            data = {"success": False, "created": False, "leave_type": code, "article": messages.hr_only_article(code)}
            return reply, data

        start_date, end_date = intents.extract_dates(message)
        if not start_date:
            self._awaiting_dates_for = code
            return messages.ask_for_dates(self._type_name(code)), {"success": False, "error": "missing_dates", "leave_type": code}

        preview = await self._call(
            "create_leave_request",
            employee_id=self.employee_id, leave_type=code,
            start_date=start_date, end_date=end_date, dry_run=True,
        )
        if not preview.get("success"):
            return messages.refusal(preview), preview

        self._draft = preview
        reply = messages.draft_preview(
            self.employee_name, self.employee_id, self._type_name(code), self._unit(code), preview
        )
        return reply, preview

    async def _submit_draft(self, draft: Dict[str, Any]) -> Reply:
        data = await self._call(
            "create_leave_request",
            employee_id=self.employee_id, leave_type=draft["leave_type"],
            start_date=draft["start_date"], end_date=draft["end_date"],
            reason="შექმნილია HR ასისტენტით, თანამშრომლის დადასტურებით",
        )
        if not data.get("success"):
            return messages.refusal(data), data

        code = data["leave_type"]
        return messages.request_created(self._type_name(code), self._unit(code), data), data
