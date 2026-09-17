from fastapi import APIRouter
from sqlalchemy import text

from app.db.session import SessionLocal
from app.vectorstore.client import get_qdrant

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Aggregate health check: verifies PostgreSQL and Qdrant connectivity."""
    components = {"database": "ok", "qdrant": "ok"}
    status = "ok"

    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
    except Exception as exc:
        components["database"] = f"error: {exc.__class__.__name__}"
        status = "degraded"

    try:
        await get_qdrant().get_collections()
    except Exception as exc:
        components["qdrant"] = f"error: {exc.__class__.__name__}"
        status = "degraded"

    return {"status": status, "components": components}
