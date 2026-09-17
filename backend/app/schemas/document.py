import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_filename: str
    file_type: str
    size_bytes: int
    status: str
    error: str | None
    page_count: int | None
    chunk_count: int | None
    created_at: datetime
    updated_at: datetime
