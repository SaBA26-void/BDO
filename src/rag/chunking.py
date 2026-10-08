"""Splitting a document into sections (articles) and then into embedding-sized chunks."""

import re
from dataclasses import dataclass, field
from typing import List, Tuple

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150

# "4.", "4.4", FAQ "ა." / "ა.2" at the start of a heading.
HEADING_NUMBER = re.compile(r"^(\d{1,2}|[ა-ჰ])(?:\.(\d{1,2}))?\.?\s")


class DocumentChunk:
    def __init__(self, text: str, source_file: str, chunk_id: str, priority: int = 50, section: str = ""):
        self.text = text
        self.source_file = source_file
        self.chunk_id = chunk_id
        self.priority = priority
        self.section = section
        self.embedding: List[float] = []


@dataclass
class Section:
    number: str  # "4.4", "6", FAQ "ა.2"; empty for the document preamble
    heading: str  # "4. ყოველწლიური ... > 4.4 მოთხოვნის წარდგენა ..."
    lines: List[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        if not self.number:
            return ""
        return f"მუხლი {self.number}" if self.number[0].isdigit() else f"პუნქტი {self.number}"


def heading_number(heading: str) -> str:
    match = HEADING_NUMBER.match(heading)
    if not match:
        return ""
    return f"{match.group(1)}.{match.group(2)}" if match.group(2) else match.group(1)


def build_sections(blocks: List[Tuple[int, str]]) -> List[Section]:
    """Group (level, text) blocks into sections. Level 1/2 are article/sub-article headings, 0 is body text."""
    sections = [Section(number="", heading="")]
    article = ""
    for level, text in blocks:
        text = text.strip()
        if not text:
            continue
        if level == 1:
            article = text
            sections.append(Section(number=heading_number(text), heading=text))
        elif level == 2:
            heading = f"{article} > {text}" if article else text
            sections.append(Section(number=heading_number(text), heading=heading))
        else:
            sections[-1].lines.append(text)
    return [s for s in sections if s.lines]


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
