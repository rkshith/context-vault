"""Text chunker.

Splits one page of text into overlapping chunks:
  - accumulate whole sentences until ~TARGET_CHARS
  - keep a short trailing overlap so answers spanning chunk boundaries stay coherent
  - oversized sentences are hard-split on word boundaries
Chunks never cross pages, so page citations remain exact.
"""

import re
from dataclasses import dataclass

from app.ingestion.parsers import PageText

TARGET_CHARS = 900
OVERLAP_CHARS = 120

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass
class ChunkData:
    chunk_index: int
    page_number: int
    content: str


def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_SPLIT.split(text)
    return [part.strip() for part in parts if part and part.strip()]


def _hard_split(sentence: str, limit: int) -> list[str]:
    words = sentence.split()
    pieces: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > limit:
            pieces.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        pieces.append(current)
    return pieces or [sentence[:limit]]


def chunk_text(text: str, target: int = TARGET_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    sentences: list[str] = []
    for sentence in _split_sentences(text):
        if len(sentence) > target:
            sentences.extend(_hard_split(sentence, target))
        else:
            sentences.append(sentence)

    chunks: list[str] = []
    buffer = ""
    for sentence in sentences:
        if buffer and len(buffer) + 1 + len(sentence) > target:
            chunks.append(buffer)
            tail = buffer[-overlap:].strip()
            buffer = f"{tail} {sentence}".strip() if tail else sentence
        else:
            buffer = f"{buffer} {sentence}".strip() if buffer else sentence
    if buffer:
        chunks.append(buffer)

    return [chunk for chunk in chunks if chunk]


def chunk_pages(pages: list[PageText]) -> list[ChunkData]:
    chunks: list[ChunkData] = []
    index = 0
    for page in pages:
        for content in chunk_text(page.text):
            chunks.append(ChunkData(chunk_index=index, page_number=page.page_number, content=content))
            index += 1
    return chunks
