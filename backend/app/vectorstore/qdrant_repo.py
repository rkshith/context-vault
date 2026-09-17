"""Qdrant operations.

Collection layout:
  - one collection for all users ("chunks")
  - every point carries user_id + document_id in its payload
  - payload indexes on user_id / document_id keep tenant-scoped queries fast
  - every read/delete goes through a mandatory user_id filter
"""

import uuid

from qdrant_client import models

from app.core.config import get_settings
from app.vectorstore.client import get_qdrant

settings = get_settings()


def _filter(user_id: uuid.UUID, document_ids: list[uuid.UUID] | None = None) -> models.Filter:
    must: list[models.Condition] = [
        models.FieldCondition(key="user_id", match=models.MatchValue(value=str(user_id)))
    ]
    if document_ids:
        must.append(
            models.FieldCondition(
                key="document_id",
                match=models.MatchAny(any=[str(d) for d in document_ids]),
            )
        )
    return models.Filter(must=must)


async def ensure_collection() -> None:
    client = get_qdrant()
    if await client.collection_exists(settings.qdrant_collection):
        return

    await client.create_collection(
        collection_name=settings.qdrant_collection,
        vectors_config=models.VectorParams(
            size=settings.embed_dim,
            distance=models.Distance.COSINE,
        ),
    )
    await client.create_payload_index(
        collection_name=settings.qdrant_collection,
        field_name="user_id",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )
    await client.create_payload_index(
        collection_name=settings.qdrant_collection,
        field_name="document_id",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )


async def upsert_chunks(
    document_id: uuid.UUID,
    user_id: uuid.UUID,
    filename: str,
    items: list[tuple[uuid.UUID, int, int, str, list[float]]],
) -> None:
    """items: (chunk_id, chunk_index, page_number, text, vector)."""
    if not items:
        return

    points = [
        models.PointStruct(
            id=str(chunk_id),
            vector=vector,
            payload={
                "user_id": str(user_id),
                "document_id": str(document_id),
                "chunk_id": str(chunk_id),
                "filename": filename,
                "page_number": page_number,
                "chunk_index": chunk_index,
                "text": text,
            },
        )
        for chunk_id, chunk_index, page_number, text, vector in items
    ]
    await get_qdrant().upsert(collection_name=settings.qdrant_collection, points=points)


async def search_chunks(
    user_id: uuid.UUID,
    query_vector: list[float],
    document_ids: list[uuid.UUID] | None = None,
    limit: int | None = None,
) -> list[models.ScoredPoint]:
    result = await get_qdrant().query_points(
        collection_name=settings.qdrant_collection,
        query=query_vector,
        query_filter=_filter(user_id, document_ids),
        limit=limit or settings.top_k,
        score_threshold=settings.score_threshold,
        with_payload=True,
    )
    return result.points


async def delete_document_points(user_id: uuid.UUID, document_id: uuid.UUID) -> None:
    await get_qdrant().delete(
        collection_name=settings.qdrant_collection,
        points_selector=models.FilterSelector(filter=_filter(user_id, [document_id])),
    )
