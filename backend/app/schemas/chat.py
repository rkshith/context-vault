import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: uuid.UUID | None = None
    # Empty/None -> search across all the user's ready documents.
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class Citation(BaseModel):
    document_id: uuid.UUID
    filename: str
    page_number: int
    chunk_index: int
    score: float


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    answer: str
    citations: list[Citation]


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    citations: list | None
    created_at: datetime
