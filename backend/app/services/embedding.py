"""Embedding provider.

FastEmbed runs a local ONNX model (no API key, no network calls after the
first model download). Both document chunks and user questions are embedded
with the same model. Swapping to a remote embedding API later only requires
replacing the two private functions.
"""

import asyncio

from fastembed import TextEmbedding

from app.core.config import get_settings

settings = get_settings()

_model: TextEmbedding | None = None


def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        _model = TextEmbedding(
            model_name=settings.embedding_model,
            cache_dir=settings.fastembed_cache_dir,
        )
    return _model


def _embed_sync(texts: list[str]) -> list[list[float]]:
    return [vector.tolist() for vector in _get_model().embed(texts)]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    # Model inference is CPU-bound; keep it off the event loop.
    return await asyncio.to_thread(_embed_sync, texts)


async def embed_query(text: str) -> list[float]:
    vectors = await embed_texts([text])
    return vectors[0]
