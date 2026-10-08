"""Reading the DOCX and PDF policy documents into DocumentChunks."""

import glob
import os
import re
from typing import List, Tuple

import docx
from pypdf import PdfReader

from src.rag.chunking import DocumentChunk, build_sections, split_text

PDF_ARTICLE_HEADING = re.compile(r"^(\d{1,2})\.\s+\S")
PDF_SUBARTICLE_HEADING = re.compile(r"^(\d{1,2})\.(\d{1,2})\s+\S")
# Every PDF page starts with "შპს „ნორთსტარ სერვისეზი“ | <title>", a document code line and the page number.
PDF_PAGE_HEADER = re.compile(r"^შპს „ნორთსტარ სერვისეზი“\s*\|\s*(.+)$")
PDF_PAGE_FURNITURE = re.compile(r"^([A-Z]{2,}-[A-Z]{2,}-\d+\s*\|.*|გვერდი \d+)$")

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

# (level, text) where level 1 = article heading, 2 = sub-article heading, 0 = body text.
Block = Tuple[int, str]


class PolicyDocumentLoader:
    def __init__(self, doc_dir: str):
        self.doc_dir = doc_dir

    def load_all_documents(self) -> List[DocumentChunk]:
        chunks = []
        for filepath in sorted(glob.glob(os.path.join(self.doc_dir, "*.*"))):
            filename = os.path.basename(filepath)
            if filename.endswith(".docx"):
                title, blocks = read_docx(filepath)
            elif filename.endswith(".pdf"):
                title, blocks = read_pdf(filepath)
            else:
                continue

            priority = DOCUMENT_PRIORITIES.get(filename, DEFAULT_PRIORITY)
            for section in build_sections(blocks):
                header = "\n".join(part for part in (title or filename, section.heading) if part)
                for piece in split_text("\n".join(section.lines)):
                    chunks.append(DocumentChunk(
                        text=f"{header}\n{piece}",
                        source_file=filename,
                        chunk_id=f"{filename}_chunk_{len(chunks) + 1}",
                        priority=priority,
                        section=section.label,
                    ))
        return chunks


def read_docx(filepath: str) -> Tuple[str, List[Block]]:
    """Headings come from the Heading 1/2 paragraph styles; tables are kept in document order."""
    doc = docx.Document(filepath)
    title, blocks = "", []
    for block in doc.iter_inner_content():
        if isinstance(block, docx.table.Table):
            for row in block.rows:
                blocks.append((0, " | ".join(cell.text.strip() for cell in row.cells)))
            continue
        style = block.style.name if block.style is not None else ""
        if style == "Title" and not title:
            title = block.text.strip()
        elif style == "Heading 1":
            blocks.append((1, block.text))
        elif style == "Heading 2":
            blocks.append((2, block.text))
        else:
            blocks.append((0, block.text))
    return title, blocks


def read_pdf(filepath: str) -> Tuple[str, List[Block]]:
    """PDF text has no styles, so a numbered line counts as a heading only if it continues the
    article sequence; this skips table cells such as "200 ლარი" and wrapped lines."""
    title, blocks = "", []
    article, sub = 0, 0
    for page in PdfReader(filepath).pages:
        for line in (page.extract_text() or "").splitlines():
            line = line.strip()
            header = PDF_PAGE_HEADER.match(line)
            if header:
                title = title or header.group(1).strip()
                continue
            if PDF_PAGE_FURNITURE.match(line):
                continue

            top = PDF_ARTICLE_HEADING.match(line)
            child = PDF_SUBARTICLE_HEADING.match(line)
            if top and int(top.group(1)) == article + 1:
                article, sub = article + 1, 0
                blocks.append((1, line))
            elif child and int(child.group(1)) == article and int(child.group(2)) == sub + 1:
                sub += 1
                blocks.append((2, line))
            else:
                blocks.append((0, line))
    return title, blocks
