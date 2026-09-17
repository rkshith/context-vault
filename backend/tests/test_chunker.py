from app.ingestion.chunker import chunk_pages, chunk_text
from app.ingestion.parsers import PageText


def test_short_text_single_chunk():
    chunks = chunk_text("Hello world. This is a test.")
    assert len(chunks) == 1
    assert "Hello world" in chunks[0]


def test_long_text_splits_with_overlap():
    sentences = " ".join(f"Sentence number {i} with some content here." for i in range(60))
    chunks = chunk_text(sentences, target=300, overlap=50)
    assert len(chunks) > 1
    assert all(len(c) <= 600 for c in chunks)
    assert all(c.strip() for c in chunks)


def test_empty_text_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_chunks_never_cross_pages():
    pages = [PageText(1, "First page content here."), PageText(2, "Second page content here.")]
    chunks = chunk_pages(pages)
    assert [c.page_number for c in chunks] == [1, 2]
    assert [c.chunk_index for c in chunks] == [0, 1]


def test_oversized_sentence_hard_splits():
    long_sentence = "word " * 500
    chunks = chunk_text(long_sentence.strip() + ".", target=200, overlap=20)
    assert len(chunks) > 1
    assert all(len(c) <= 400 for c in chunks)
