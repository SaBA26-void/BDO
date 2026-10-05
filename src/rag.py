"""
RAG Engine for Georgian Policy Documents (Northstar Services)
Extracts, chunks, embeds, retrieves, and generates answers from DOCX and PDF documents.
"""

import os
import glob
import json
import math
import time
import hashlib
from typing import List, Dict, Any, Optional, Tuple

import docx
from pypdf import PdfReader
from dotenv import load_dotenv
from openai import OpenAI, RateLimitError

load_dotenv()

# Gemini is used through its OpenAI-compatible endpoint.
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
CHAT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
# Small batches + retry keep us inside the free-tier tokens-per-minute quota.
EMBEDDING_BATCH_SIZE = 20
EMBEDDING_DIMENSIONS = 768
RATE_LIMIT_RETRIES = 6
RATE_LIMIT_WAIT_SECONDS = 20

EMBEDDING_CACHE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "embeddings_cache.json"
)

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150

NOT_FOUND_ANSWER = (
    "მოწოდებულ კომპანიის პოლიტიკის დოკუმენტებში აღნიშნულ საკითხზე ინფორმაცია ვერ მოიძებნა. "
    "გთხოვთ, მიმართოთ HR დეპარტამენტს."
)

# Current policies outrank the FAQ, which defers to them; Remote v2.0 replaces the FAQ's and
# handbook Article 6's remote-work rules. The handbook is the oldest source.
DOCUMENT_PRIORITIES = {
    "Leave_and_Absence_Policy_v4.0.docx": 100,
    "Remote_and_Hybrid_Work_Policy_v2.0.pdf": 90,
    "Information_Security_Policy_v3.2.pdf": 90,
    "Learning_and_Development_Policy_v1.2.pdf": 90,
    "Travel_and_Expense_Policy_v2.3.pdf": 90,
    "Employee_FAQ_2025.docx": 40,
    "Employee_Handbook_v3.1.docx": 10,
}
DEFAULT_PRIORITY = 50

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
    "პასუხის ბოლოს აუცილებლად მიუთითე გამოყენებული წყარო ფორმატით: [წყარო: ფაილის_სახელი]."
)


class DocumentChunk:
    def __init__(self, text: str, source_file: str, chunk_id: str, priority: int = 50, section: str = ""):
        self.text = text
        self.source_file = source_file
        self.chunk_id = chunk_id
        self.priority = priority
        self.section = section
        self.embedding: List[float] = []


def split_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Split text into ~size-character chunks on line boundaries, with overlap."""
    chunks, current = [], ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if current and len(current) + len(line) > size:
            chunks.append(current)
            current = current[-overlap:]
        current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


class PolicyDocumentLoader:
    def __init__(self, doc_dir: str):
        self.doc_dir = doc_dir

    def load_all_documents(self) -> List[DocumentChunk]:
        chunks = []
        for filepath in sorted(glob.glob(os.path.join(self.doc_dir, "*.*"))):
            filename = os.path.basename(filepath)
            if filename.endswith(".docx"):
                pages = [("", self._read_docx(filepath))]
            elif filename.endswith(".pdf"):
                pages = [(f"გვერდი {i + 1}", page.extract_text() or "")
                         for i, page in enumerate(PdfReader(filepath).pages)]
            else:
                continue

            priority = DOCUMENT_PRIORITIES.get(filename, DEFAULT_PRIORITY)
            for section, text in pages:
                for piece in split_text(text):
                    chunks.append(DocumentChunk(
                        text=piece,
                        source_file=filename,
                        chunk_id=f"{filename}_chunk_{len(chunks) + 1}",
                        priority=priority,
                        section=section,
                    ))
        return chunks

    @staticmethod
    def _read_docx(filepath: str) -> str:
        doc = docx.Document(filepath)
        lines = []
        for block in doc.iter_inner_content():  # paragraphs and tables in document order
            if isinstance(block, docx.table.Table):
                for row in block.rows:
                    lines.append(" | ".join(cell.text.strip() for cell in row.cells))
            else:
                lines.append(block.text)
        return "\n".join(lines)


def cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class PolicyRetriever:
    def __init__(self, chunks: List[DocumentChunk], client: OpenAI):
        self.chunks = chunks
        self.client = client
        self._embed_chunks()

    def _embed_chunks(self) -> None:
        """Embed chunks, reusing cached vectors so unchanged documents are embedded only once."""
        cache = {}
        if os.path.exists(EMBEDDING_CACHE_FILE):
            with open(EMBEDDING_CACHE_FILE, encoding="utf-8") as f:
                cache = json.load(f)

        keys = [hashlib.sha256(f"{EMBEDDING_MODEL}:{c.text}".encode("utf-8")).hexdigest() for c in self.chunks]
        missing = [i for i, key in enumerate(keys) if key not in cache]
        if missing:
            new_embeddings = self._embed([self.chunks[i].text for i in missing])
            for i, embedding in zip(missing, new_embeddings):
                cache[keys[i]] = embedding
            os.makedirs(os.path.dirname(EMBEDDING_CACHE_FILE), exist_ok=True)
            with open(EMBEDDING_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({key: cache[key] for key in keys}, f)

        for chunk, key in zip(self.chunks, keys):
            chunk.embedding = cache[key]

    def _embed(self, texts: List[str]) -> List[List[float]]:
        embeddings = []
        for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = texts[start:start + EMBEDDING_BATCH_SIZE]
            for attempt in range(RATE_LIMIT_RETRIES):
                try:
                    response = self.client.embeddings.create(
                        model=EMBEDDING_MODEL, input=batch, dimensions=EMBEDDING_DIMENSIONS
                    )
                    break
                except RateLimitError:
                    if attempt == RATE_LIMIT_RETRIES - 1:
                        raise
                    time.sleep(RATE_LIMIT_WAIT_SECONDS)
            embeddings.extend(item.embedding for item in response.data)
        return embeddings

    def retrieve(self, query: str, top_k: int = 3) -> List[Tuple[DocumentChunk, float]]:
        query_embedding = self._embed([query])[0]
        scored_chunks = [(chunk, cosine_similarity(query_embedding, chunk.embedding)) for chunk in self.chunks]
        scored_chunks.sort(key=lambda x: x[1], reverse=True)

        # Relevance picks the chunks; priority orders them so the newest policy comes first.
        # Multiplying similarity by priority would drown relevant lower-priority documents,
        # since embedding similarities fall in a narrow range.
        top = scored_chunks[:top_k]
        top.sort(key=lambda x: (x[0].priority, x[1]), reverse=True)
        return top


class PolicyRAGEngine:
    def __init__(self, doc_dir: Optional[str] = None, client: Optional[OpenAI] = None):
        if doc_dir is None:
            doc_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "documents")
        if client is None:
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise RuntimeError("GEMINI_API_KEY is not set. Add it to your .env file.")
            client = OpenAI(api_key=api_key, base_url=GEMINI_BASE_URL)

        self.doc_dir = doc_dir
        self.client = client
        self.loader = PolicyDocumentLoader(doc_dir)
        self.chunks = self.loader.load_all_documents()
        self.retriever = PolicyRetriever(self.chunks, client)

    def answer_question(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        results = self.retriever.retrieve(query, top_k=top_k)

        retrieved_texts = []
        sources = []
        for chunk, score in results:
            label = f"{chunk.source_file} | {chunk.section}" if chunk.section else chunk.source_file
            retrieved_texts.append(f"--- [წყარო: {label} | პრიორიტეტი: {chunk.priority}] ---\n{chunk.text}")
            sources.append({
                "source_file": chunk.source_file,
                "section": chunk.section,
                "score": round(score, 3),
                "text": chunk.text[:150] + "..."
            })

        context_str = "\n\n".join(retrieved_texts)
        response = self.client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"კონტექსტი:\n{context_str}\n\nკითხვა: {query}"}
            ],
            temperature=0.2
        )
        answer_text = response.choices[0].message.content.strip()
        if NOT_FOUND_ANSWER in answer_text:
            return {"answer": NOT_FOUND_ANSWER, "found": False, "sources": []}

        return {"answer": answer_text, "found": True, "sources": sources}


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    engine = PolicyRAGEngine()
    question = " ".join(sys.argv[1:]) or "რამდენი დღე მაქვს წლიური შვებულება?"
    result = engine.answer_question(question)
    print(result["answer"])
    for s in result["sources"]:
        print(f"  - {s['source_file']} {s['section']} (score={s['score']})")
