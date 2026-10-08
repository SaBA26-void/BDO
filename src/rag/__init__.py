"""
RAG for the Georgian policy documents (Northstar Services).

    chunking.py   - sections (articles) and text chunks
    loader.py     - reading DOCX / PDF files into chunks, document priorities
    retriever.py  - embeddings, cache, similarity search
    engine.py     - prompt + LLM answer with source citation
"""

from dotenv import load_dotenv

load_dotenv()  # must run before the submodules read GEMINI_* from the environment

from src.rag.chunking import DocumentChunk, Section, build_sections, heading_number, split_text  # noqa: E402
from src.rag.loader import DOCUMENT_PRIORITIES, PolicyDocumentLoader  # noqa: E402
from src.rag.retriever import PolicyRetriever  # noqa: E402
from src.rag.engine import NOT_FOUND_ANSWER, SYSTEM_PROMPT, PolicyRAGEngine  # noqa: E402

__all__ = [
    "DocumentChunk", "Section", "build_sections", "heading_number", "split_text",
    "DOCUMENT_PRIORITIES", "PolicyDocumentLoader",
    "PolicyRetriever",
    "NOT_FOUND_ANSWER", "SYSTEM_PROMPT", "PolicyRAGEngine",
]
