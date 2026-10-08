import os
import re
from types import SimpleNamespace

import pytest

import src.rag.retriever as retriever
from src.rag import NOT_FOUND_ANSWER, PolicyDocumentLoader, PolicyRAGEngine, build_sections, heading_number
from src.rag.chunking import CHUNK_SIZE

DOC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "documents")


@pytest.fixture(scope="module")
def chunks():
    return PolicyDocumentLoader(DOC_DIR).load_all_documents()


def labels(chunks, source_file):
    return [c.section for c in chunks if c.source_file == source_file]


@pytest.mark.parametrize("heading, number", [
    ("4. ყოველწლიური ანაზღაურებადი შვებულება", "4"),
    ("4.10 ფულადი კომპენსაცია", "4.10"),
    ("ა.2 რამდენი ხნით ადრე უნდა მოვითხოვო შვებულება?", "ა.2"),
    ("როგორ გამოვიყენოთ ეს დოკუმენტი", ""),
])
def test_heading_number(heading, number):
    assert heading_number(heading) == number


def test_build_sections_nests_sub_articles_and_drops_empty_headings():
    sections = build_sections([
        (0, "preamble"), (1, "4. ყოველწლიური"), (2, "4.1 ოდენობა"), (0, "24 დღე"), (1, "6. დისტანციური"), (0, "ტექსტი"),
    ])
    assert [(s.label, s.heading) for s in sections] == [
        ("", ""),
        ("მუხლი 4.1", "4. ყოველწლიური > 4.1 ოდენობა"),
        ("მუხლი 6", "6. დისტანციური"),
    ]


def test_all_documents_are_loaded(chunks):
    assert len({c.source_file for c in chunks}) == 7


def test_leave_policy_is_split_by_sub_article(chunks):
    leave = labels(chunks, "Leave_and_Absence_Policy_v4.0.docx")
    assert {"მუხლი 4.4", "მუხლი 4.6", "მუხლი 12.2", "მუხლი 12.3", "მუხლი 14"} <= set(leave)
    article = next(c for c in chunks if c.section == "მუხლი 12.3" and c.source_file.startswith("Leave"))
    assert "12.3 რისი გაკეთება არ შეუძლია HR ასისტენტს" in article.text
    assert "მომდევნო წლის თარიღებზე" in article.text


def test_pdf_headings_follow_article_sequence(chunks):
    found = [l for l in dict.fromkeys(labels(chunks, "Learning_and_Development_Policy_v1.2.pdf")) if l]
    numbers = [l.removeprefix("მუხლი ") for l in found]
    # Table cells like "31 მარტამდე" or "6 თვეზე ნაკლები" must not become articles.
    assert numbers == ["1.1", "1.2", "2.1", "2.2", "2.3", "3.1", "3.2", "3.3", "4",
                       "5.1", "5.2", "5.3", "5.4", "6.1", "6.2", "7", "8", "9", "10", "11"]


def test_pdf_page_headers_and_footers_are_removed(chunks):
    furniture = re.compile(r"^(გვერდი \d+|[A-Z]{2,}-[A-Z]{2,}-\d+ \||შპს „ნორთსტარ სერვისეზი“ \|)")
    for chunk in chunks:
        assert not any(furniture.match(line) for line in chunk.text.splitlines()), chunk.chunk_id


def test_chunks_start_with_document_title_and_article(chunks):
    chunk = next(c for c in chunks if c.source_file.startswith("Travel") and c.section == "მუხლი 5.1")
    title, heading = chunk.text.splitlines()[:2]
    assert "მივლინებისა და ხარჯების" in title
    assert heading == "5. სასტუმრო > 5.1 ერთი ღამის ლიმიტები"


def test_faq_questions_are_labelled(chunks):
    assert "პუნქტი ა.2" in labels(chunks, "Employee_FAQ_2025.docx")


def test_chunks_stay_near_chunk_size(chunks):
    assert max(len(c.text) for c in chunks) < CHUNK_SIZE + 300


class FakeClient:
    """Stands in for the Gemini endpoint: texts mentioning "ოდენობა" embed close to each other."""

    def __init__(self, answer):
        self.prompts = []
        self.embeddings = SimpleNamespace(create=self._embed)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))
        self.answer = answer

    def _embed(self, model, input, dimensions):
        return SimpleNamespace(data=[
            SimpleNamespace(embedding=[1.0, 0.0] if "ოდენობა" in text else [0.0, 1.0]) for text in input
        ])

    def _chat(self, model, messages, temperature):
        self.prompts.append(messages)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.answer))])


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(retriever, "EMBEDDING_CACHE_FILE", str(tmp_path / "embeddings.json"))


def test_context_and_prompt_carry_article_numbers(isolated_cache):
    client = FakeClient("24 სამუშაო დღე. [წყარო: Leave_and_Absence_Policy_v4.0.docx, მუხლი 4.1]")
    result = PolicyRAGEngine(DOC_DIR, client=client).answer_question("შვებულების ოდენობა")

    system, user = client.prompts[0]
    assert "მუხლი X.Y" in system["content"]
    assert re.search(r"\[წყარო: Leave_and_Absence_Policy_v4\.0\.docx \| მუხლი \d+\.\d+ \| პრიორიტეტი: 100\]",
                     user["content"])
    top = result["sources"][0]
    assert result["found"] and top["source_file"] == "Leave_and_Absence_Policy_v4.0.docx"
    assert top["section"].startswith("მუხლი")


def test_not_found_answer_is_reported(isolated_cache):
    client = FakeClient(NOT_FOUND_ANSWER)
    result = PolicyRAGEngine(DOC_DIR, client=client).answer_question("რა ფერისაა ოფისის კედლები?")
    assert result == {"answer": NOT_FOUND_ANSWER, "found": False, "sources": []}
