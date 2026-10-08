"""Georgian reply texts. Only formatting lives here - no decisions, no tool calls."""

from typing import Any, Dict, List

LEAVE_POLICY_FILE = "Leave_and_Absence_Policy_v4.0.docx"
DAY_UNIT_KA = {"calendar": "კალენდარული დღე", "working": "სამუშაო დღე"}

# Article 12.2: for these types the assistant explains the rule and redirects to HR.
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
GENERIC_HR_ONLY_RULE = ("12.3", "ამ სახის შვებულების მოთხოვნას HR ასისტენტი არ ქმნის. მიმართეთ HR-ს.")


def leave_type_name(leave_types: Dict[str, Dict[str, Any]], code: str) -> str:
    return leave_types.get(code, {}).get("name", code)


def day_unit_label(leave_types: Dict[str, Dict[str, Any]], code: str) -> str:
    return DAY_UNIT_KA.get(leave_types.get(code, {}).get("day_unit"), "დღე")


def welcome(employee_name: str, employee_id: str) -> str:
    return (
        f"\nგამარჯობა, {employee_name} ({employee_id})!\n"
        "შემიძლია ვუპასუხო პოლიტიკის კითხვებს, გაჩვენოთ თქვენი შვებულების ბალანსი და შევქმნა "
        "ყოველწლიური, ავადმყოფობის ან უხელფასო შვებულების მოთხოვნა.\n"
        "გასასვლელად დაწერეთ „გასვლა“."
    )


def policy_answer(rag_result: Dict[str, Any]) -> str:
    """The RAG answer, with a source line appended if the model forgot to cite one."""
    answer = rag_result["answer"]
    if rag_result["found"] and "წყარო" not in answer and rag_result["sources"]:
        top = rag_result["sources"][0]
        label = f"{top['source_file']}, {top['section']}" if top["section"] else top["source_file"]
        answer += f"\n\n[წყარო: {label}]"
    return answer


def policy_error(error: Exception) -> str:
    return f"❌ პოლიტიკის დოკუმენტებში ძებნა ვერ მოხერხდა: {error}"


def balance_error(data: Dict[str, Any]) -> str:
    return f"❌ შეცდომა ბალანსის შემოწმებისას: {data.get('error')}"


def balance_missing(year: int, employee_name: str, employee_id: str) -> str:
    return f"ℹ️ {year} წლის შვებულების ბალანსი ვერ მოიძებნა ({employee_name}, {employee_id})."


def balance(
    year: int, employee_name: str, employee_id: str,
    balances: List[Dict[str, Any]], leave_types: Dict[str, Dict[str, Any]],
) -> str:
    """Article 5.2: show approved and pending days alongside the available balance."""
    lines = [f"📊 შვებულების ბალანსი {year} წლისთვის — {employee_name} ({employee_id}):"]
    for b in balances:
        code = b["leave_type"]
        total = f"{b['total_days']}"
        if b.get("carried_over_days"):
            total += f", მ.შ. გადმოტანილი {b['carried_over_days']}"
        lines.append(
            f"• {leave_type_name(leave_types, code)}: ხელმისაწვდომია {max(b['remaining_days'], 0)} "
            f"{day_unit_label(leave_types, code)} (კუთვნილი: {total}; დამტკიცებული: {b['used_days']}; "
            f"განხილვის პროცესში: {b['pending_days']})"
        )
    return "\n".join(lines)


def hr_only_redirect(code: str, type_name: str) -> str:
    article, rule = HR_ONLY_RULES.get(code, GENERIC_HR_ONLY_RULE)
    return (
        f"ℹ️ ამ სახის მოთხოვნას („{type_name}“) HR ასისტენტი არ ქმნის.\n\n{rule}\n\n"
        f"📖 {LEAVE_POLICY_FILE}, მუხლი {article} (და მუხლი 12.3)."
    )


def hr_only_article(code: str) -> str:
    return HR_ONLY_RULES.get(code, GENERIC_HR_ONLY_RULE)[0]


def ask_for_dates(type_name: str) -> str:
    return (
        f"📅 მოთხოვნისთვის („{type_name}“) მიუთითეთ პერიოდი ფორმატით YYYY-MM-DD, "
        f"მაგალითად: „2026-11-02-დან 2026-11-06-მდე“."
    )


def draft_preview(
    employee_name: str, employee_id: str, type_name: str, unit: str, preview: Dict[str, Any]
) -> str:
    """Article 12.2: show type, dates and day count and ask for explicit confirmation."""
    return (
        "📝 გთხოვთ, გადაამოწმოთ მოთხოვნა:\n"
        f"• თანამშრომელი: {employee_name} ({employee_id})\n"
        f"• შვებულების სახე: {type_name}\n"
        f"• პერიოდი: {preview['start_date']} – {preview['end_date']}\n"
        f"• დღეების რაოდენობა: {preview['requested_days']} {unit}\n"
        f"• ბალანსი მოთხოვნის შემდეგ: {preview['remaining_days_after']}\n\n"
        "შევქმნა მოთხოვნა? დასადასტურებლად დაწერეთ „კი“ ან „დიახ“, გასაუქმებლად – „არა“."
    )


def request_created(type_name: str, unit: str, data: Dict[str, Any]) -> str:
    return (
        "✅ მოთხოვნა შეიქმნა.\n"
        f"• მოთხოვნის ID: {data['request_id']}\n"
        f"• შვებულების სახე: {type_name}\n"
        f"• პერიოდი: {data['start_date']} – {data['end_date']} "
        f"({data['requested_days']} {unit})\n"
        "• სტატუსი: განხილვის პროცესში — ეს შვებულების დამტკიცებას არ ნიშნავს (მუხლი 12.2).\n"
        f"• დარჩენილი ბალანსი: {data['remaining_days']}"
    )


def refusal(data: Dict[str, Any]) -> str:
    """Article 12.3: explain why the request was not created and cite the article."""
    reply = f"❌ მოთხოვნა ვერ შეიქმნა: {data.get('error')}"
    if data.get("article"):
        reply += f"\n📖 {LEAVE_POLICY_FILE}, მუხლი {data['article']}."
    return reply


DRAFT_DECLINED = "მოთხოვნა არ შეიქმნა."
DRAFT_DROPPED_PREFIX = "ℹ️ წინა მოთხოვნა არ შეიქმნა, რადგან „კი“ არ დაწერეთ.\n\n"
