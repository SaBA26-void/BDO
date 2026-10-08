"""Answering a policy question: retrieve the relevant chunks and ask the LLM, citing the source."""

import os
from typing import Any, Dict, Optional

from openai import OpenAI

from src.rag.loader import PolicyDocumentLoader
from src.rag.retriever import PolicyRetriever

# Gemini is used through its OpenAI-compatible endpoint.
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
CHAT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DOC_DIR = os.path.join(PROJECT_ROOT, "documents")

NOT_FOUND_ANSWER = (
    "მოწოდებულ კომპანიის პოლიტიკის დოკუმენტებში აღნიშნულ საკითხზე ინფორმაცია ვერ მოიძებნა. "
    "გთხოვთ, მიმართოთ HR დეპარტამენტს."
)

SYSTEM_PROMPT = (
    "შენ ხარ კომპანია ნორთსტარ სერვისეზის HR AI ასისტენტი.\n"
    "უპასუხე მომხმარებლის კითხვას მხოლოდ მოწოდებული კონტექსტის საფუძველზე, ქართულ ენაზე.\n"
    "კონტექსტის ფრაგმენტები დალაგებულია პრიორიტეტის მიხედვით. პასუხი დააფუძნე ყველაზე მაღალი "
    "პრიორიტეტის წყაროს, რომელიც კითხვას პასუხობს; დაბალი პრიორიტეტის წყარო გამოიყენე მხოლოდ მაშინ, "
    "თუ მაღალი პრიორიტეტის წყაროებში ეს ინფორმაცია არ არის. წინააღმდეგობის შემთხვევაში ყოველთვის "
    "მაღალი პრიორიტეტის წყაროა სწორი (მაგ. Leave_and_Absence_Policy_v4.0 overrides Employee_Handbook_v3.1; "
    "Remote_and_Hybrid_Work_Policy_v2.0 overrides Employee_FAQ_2025 and Employee_Handbook_v3.1).\n"
    "პასუხი იყოს ზუსტი და სრული: მოიყვანე კონკრეტული რიცხვები და პირობები.\n"
    f"თუ პასუხი კონტექსტში არ არის, უპასუხე ზუსტად ასე: {NOT_FOUND_ANSWER}\n"
    "თითოეული ფრაგმენტის სათაურში მითითებულია ფაილი და მუხლი (ან FAQ-ის პუნქტი).\n"
    "პასუხის ბოლოს აუცილებლად მიუთითე გამოყენებული წყარო და მუხლი ფორმატით: "
    "[წყარო: ფაილის_სახელი, მუხლი X.Y]. თუ რამდენიმე მუხლს ეყრდნობი, ჩამოთვალე ყველა."
)


def make_gemini_client() -> OpenAI:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set. Add it to your .env file.")
    return OpenAI(api_key=api_key, base_url=GEMINI_BASE_URL)


class PolicyRAGEngine:
    def __init__(self, doc_dir: Optional[str] = None, client: Optional[OpenAI] = None):
        self.doc_dir = doc_dir if doc_dir is not None else DEFAULT_DOC_DIR
        self.client = client if client is not None else make_gemini_client()
        self.loader = PolicyDocumentLoader(self.doc_dir)
        self.chunks = self.loader.load_all_documents()
        self.retriever = PolicyRetriever(self.chunks, self.client)

    def answer_question(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        results = self.retriever.retrieve(query, top_k=top_k)

        context_parts, sources = [], []
        for chunk, score in results:
            label = f"{chunk.source_file} | {chunk.section}" if chunk.section else chunk.source_file
            context_parts.append(f"--- [წყარო: {label} | პრიორიტეტი: {chunk.priority}] ---\n{chunk.text}")
            sources.append({
                "source_file": chunk.source_file,
                "section": chunk.section,
                "score": round(score, 3),
                "text": chunk.text[:150] + "..."
            })

        answer_text = self._ask_llm("\n\n".join(context_parts), query)
        if NOT_FOUND_ANSWER in answer_text:
            return {"answer": NOT_FOUND_ANSWER, "found": False, "sources": []}
        return {"answer": answer_text, "found": True, "sources": sources}

    def _ask_llm(self, context: str, query: str) -> str:
        response = self.client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"კონტექსტი:\n{context}\n\nკითხვა: {query}"}
            ],
            temperature=0.2
        )
        return response.choices[0].message.content.strip()


if __name__ == "__main__":
    # Quick manual check: python -m src.rag.engine "რამდენი დღე მაქვს წლიური შვებულება?"
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    engine = PolicyRAGEngine()
    question = " ".join(sys.argv[1:]) or "რამდენი დღე მაქვს წლიური შვებულება?"
    result = engine.answer_question(question)
    print(result["answer"])
    for s in result["sources"]:
        print(f"  - {s['source_file']} {s['section']} (score={s['score']})")
