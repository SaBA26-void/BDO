import asyncio

import pytest
from fastmcp import Client

from mcp_server.app import mcp
from src.assistant import GeorgianAIAssistant
from src.assistant.intents import classify_intent, extract_dates, extract_leave_type, resolve_employee_alias


@pytest.mark.parametrize("message, intent", [
    ("რამდენი დღე დამრჩა შვებულებიდან?", "CHECK_BALANCE"),
    ("მაჩვენე ჩემი ბალანსი", "CHECK_BALANCE"),
    ("მინდა შვებულება 2026-11-02-დან 2026-11-04-მდე", "CREATE_LEAVE_REQUEST"),
    ("ავად ვარ, გამიფორმე ავადმყოფობის შვებულება", "CREATE_LEAVE_REQUEST"),
    ("რამდენი დღით ადრე უნდა მოვითხოვო შვებულება?", "POLICY_QA"),
    ("როგორ ავიღო უხელფასო შვებულება", "POLICY_QA"),
    ("შეიძლება ავიღო შვებულება 2026-11-02-დან 2026-11-04-მდე?", "CREATE_LEAVE_REQUEST"),
    ("რა არის სასტუმროს ლიმიტი მივლინებისას?", "POLICY_QA"),
])
def test_classify_intent(message, intent):
    assert classify_intent(message) == intent


@pytest.mark.parametrize("message, leave_type", [
    ("მინდა უხელფასო შვებულება", "UNPAID"),
    ("ანაზღაურების გარეშე შვებულება მჭირდება", "UNPAID"),
    ("ავად ვარ და ბიულეტენი მჭირდება", "SICK"),
    ("მინდა ყოველწლიური შვებულება", "ANNUAL"),
    ("ბებია გარდამეცვალა, გლოვის შვებულება მჭირდება", "BEREAVEMENT"),
    ("გამოცდისთვის მჭირდება შვებულება", "STUDY"),
    ("მინდა შვებულება", None),
])
def test_extract_leave_type(message, leave_type):
    assert extract_leave_type(message) == leave_type


def test_extract_dates_orders_range_and_accepts_single_day():
    assert extract_dates("2026-11-06-მდე, 2026-11-02-დან") == ("2026-11-02", "2026-11-06")
    assert extract_dates("მხოლოდ 2026-11-02") == ("2026-11-02", "2026-11-02")
    assert extract_dates("2026-13-40") == (None, None)


@pytest.mark.parametrize("raw, expected", [("e1001", "E1001"), ("EMP001", "E1001"), (" emp7 ", "E1007")])
def test_resolve_employee_alias(raw, expected):
    assert resolve_employee_alias(raw) == expected


def run_conversation(employee_id, messages):
    async def run():
        async with Client(mcp) as client:
            assistant = await GeorgianAIAssistant.login(client, employee_id)
            if assistant is None:
                return None
            return [await assistant.process_message(m) for m in messages]
    return asyncio.run(run())


def test_login_rejects_unknown_employee():
    assert run_conversation("E9999", []) is None


def test_balance_conversation():
    [result] = run_conversation("E1007", ["რამდენი დღე დამრჩა?"])
    assert result["intent"] == "CHECK_BALANCE"
    assert "ხელმისაწვდომია 15" in result["reply"]


def test_request_is_created_only_after_confirmation():
    preview, confirmed, balance = run_conversation("E1007", [
        "მინდა ყოველწლიური შვებულება 2026-11-02-დან 2026-11-04-მდე",
        "კი",
        "ბალანსი",
    ])
    assert preview["data"]["dry_run"]
    assert confirmed["intent"] == "CONFIRM_LEAVE_REQUEST"
    assert confirmed["data"]["status"] == "PENDING"
    assert confirmed["data"]["created_via"] == "assistant"
    assert "ხელმისაწვდომია 12" in balance["reply"]


def test_declined_draft_creates_nothing():
    _, declined, balance = run_conversation("E1007", [
        "მინდა შვებულება 2026-11-02-დან 2026-11-04-მდე",
        "არა",
        "ბალანსი",
    ])
    assert declined["intent"] == "DECLINE_LEAVE_REQUEST"
    assert "ხელმისაწვდომია 15" in balance["reply"]


def test_policy_refusal_cites_article():
    [result] = run_conversation("E1004", ["მინდა ყოველწლიური შვებულება 2026-11-02-დან 2026-11-03-მდე"])
    assert "მუხლი 4.3" in result["reply"]


def test_bereavement_is_redirected_to_hr():
    [result] = run_conversation("E1001", ["გლოვის შვებულება მჭირდება 2026-10-12"])
    assert result["data"]["created"] is False
    assert "მუხლი 8" in result["reply"]
