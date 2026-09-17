"""Document ingestion pipeline.

upload route -> background task -> process_document():
  parse -> chunk -> embed -> store chunks (Postgres) + vectors (Qdrant)

Runs off the chat request path. Any failure marks the document as failed
with a readable error instead of surfacing a 500 to the uploader.
"""

import asyncio
import logging
import uuid
from pathlib import Path

from app.db.session import SessionLocal
from app.ingestion.chunker import chunk_pages
from app.ingestion.parsers import parse_file
from app.models import Chunk, Document, DocumentStatus
from app.services import embedding
from app.vectorstore import qdrant_repo

logger = logging.getLogger(__name__)


async def process_document(document_id: uuid.UUID) -> None:
    async with SessionLocal() as db:
        document = await db.get(Document, document_id)
        if document is None:
            return

        try:
            document.status = DocumentStatus.processing
            document.error = None
            await db.commit()

            path = Path(document.storage_path)
            pages = await asyncio.to_thread(parse_file, document.file_type, path)
            if not pages:
                raise ValueError("No extractable text found in document")

            chunks = chunk_pages(pages)
            if not chunks:
                raise ValueError("Document produced no text chunks")

            vectors = await embedding.embed_texts([chunk.content for chunk in chunks])

            rows = [
                Chunk(
                    id=uuid.uuid4(),
                    document_id=document.id,
                    user_id=document.user_id,
                    chunk_index=chunk.chunk_index,
                    page_number=chunk.page_number,
                    content=chunk.content,
                )
                for chunk in chunks
            ]
            db.add_all(rows)
            await db.flush()

            await qdrant_repo.upsert_chunks(
                document_id=document.id,
                user_id=document.user_id,
                filename=document.original_filename,
                items=[
                    (row.id, row.chunk_index, row.page_number, row.content, vector)
                    for row, vector in zip(rows, vectors)
                ],
            )

            document.page_count = max(page.page_number for page in pages)
            document.chunk_count = len(rows)
            document.status = DocumentStatus.ready
            await db.commit()

            logger.info("Ingested document %s: %d chunks, %d pages", document_id, len(rows), document.page_count)

        except Exception:
            await db.rollback()
            failed = await db.get(Document, document_id)
            if failed is not None:
                failed.status = DocumentStatus.failed
                failed.error = "Processing failed. Check server logs for details."
                await db.commit()
            logger.exception("Ingestion failed for document %s", document_id)
