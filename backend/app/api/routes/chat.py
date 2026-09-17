import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import DbDep, UserDep
from app.core.rate_limit import chat_limit
from app.models import Conversation, Document, Message, MessageRole, User
from app.schemas.chat import ChatRequest, ChatResponse, Citation
from app.services import embedding, llm
from app.vectorstore import qdrant_repo

router = APIRouter(prefix="/chat", tags=["chat"])

NO_CONTEXT_REPLY = (
    "I couldn't find any relevant passages in your documents for this question. "
    "Try uploading a related document or rephrasing the question."
)


async def _get_owned_conversation(db, user: User, conversation_id: uuid.UUID) -> Conversation:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation


async def _history(db, conversation_id: uuid.UUID) -> list[dict]:
    result = await db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(llm.HISTORY_MESSAGES)
    )
    recent = list(result)
    recent.reverse()
    return [{"role": m.role.value, "content": m.content} for m in recent]


@router.post("", response_model=ChatResponse, dependencies=[Depends(chat_limit)])
async def chat(payload: ChatRequest, user: UserDep, db: DbDep) -> ChatResponse:
    document_ids: list[uuid.UUID] | None = None
    if payload.document_ids:
        result = await db.scalars(
            select(Document).where(
                Document.user_id == user.id,
                Document.id.in_(payload.document_ids),
            )
        )
        owned_ids = {d.id for d in result}
        missing = set(payload.document_ids) - owned_ids
        if missing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="One or more selected documents were not found",
            )
        document_ids = list(owned_ids)

    if payload.conversation_id is not None:
        conversation = await _get_owned_conversation(db, user, payload.conversation_id)
    else:
        conversation = Conversation(user_id=user.id, title=payload.message[:80])
        db.add(conversation)
        await db.flush()

    query_vector = await embedding.embed_query(payload.message)
    points = await qdrant_repo.search_chunks(user.id, query_vector, document_ids)
    citations = [
        Citation(
            document_id=uuid.UUID(point.payload["document_id"]),
            filename=point.payload["filename"],
            page_number=point.payload["page_number"],
            chunk_index=point.payload["chunk_index"],
            score=point.score,
        )
        for point in points
    ]

    if points:
        passages = [
            (point.payload["filename"], point.payload["page_number"], point.payload["text"])
            for point in points
        ]
        history = await _history(db, conversation.id)
        try:
            answer = await llm.generate_answer(payload.message, passages, history)
        except llm.LLMNotConfigured as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OPENROUTER_API_KEY is not configured on the server",
            ) from exc
    else:
        answer = NO_CONTEXT_REPLY

    db.add(Message(conversation_id=conversation.id, role=MessageRole.user, content=payload.message))
    db.add(
        Message(
            conversation_id=conversation.id,
            role=MessageRole.assistant,
            content=answer,
            citations=[c.model_dump(mode="json") for c in citations],
        )
    )
    await db.commit()

    return ChatResponse(conversation_id=conversation.id, answer=answer, citations=citations)


@router.post("/stream", dependencies=[Depends(chat_limit)])
async def chat_stream(payload: ChatRequest, user: UserDep, db: DbDep) -> StreamingResponse:
    """SSE stream: `citations` event, then `token` events, then `done`. Persists messages on completion."""
    document_ids: list[uuid.UUID] | None = None
    if payload.document_ids:
        result = await db.scalars(
            select(Document).where(
                Document.user_id == user.id,
                Document.id.in_(payload.document_ids),
            )
        )
        owned_ids = {d.id for d in result}
        if set(payload.document_ids) - owned_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="One or more selected documents were not found",
            )
        document_ids = list(owned_ids)

    if payload.conversation_id is not None:
        conversation = await _get_owned_conversation(db, user, payload.conversation_id)
    else:
        conversation = Conversation(user_id=user.id, title=payload.message[:80])
        db.add(conversation)
        await db.flush()

    query_vector = await embedding.embed_query(payload.message)
    points = await qdrant_repo.search_chunks(user.id, query_vector, document_ids)
    citations = [
        Citation(
            document_id=uuid.UUID(point.payload["document_id"]),
            filename=point.payload["filename"],
            page_number=point.payload["page_number"],
            chunk_index=point.payload["chunk_index"],
            score=point.score,
        )
        for point in points
    ]

    async def events():
        if not points:
            yield f"event: answer\ndata: {json.dumps({'text': NO_CONTEXT_REPLY})}\n\n"
            answer_text = NO_CONTEXT_REPLY
        else:
            try:
                passages = [
                    (p.payload["filename"], p.payload["page_number"], p.payload["text"])
                    for p in points
                ]
                history = await _history(db, conversation.id)
                answer_text = ""
                async for token in llm.stream_answer(payload.message, passages, history):
                    answer_text += token
                    yield f"event: token\ndata: {json.dumps({'text': token})}\n\n"
            except llm.LLMNotConfigured:
                yield f"event: error\ndata: {json.dumps({'detail': 'OPENROUTER_API_KEY is not configured'})}\n\n"
                return

        db.add(Message(conversation_id=conversation.id, role=MessageRole.user, content=payload.message))
        db.add(
            Message(
                conversation_id=conversation.id,
                role=MessageRole.assistant,
                content=answer_text,
                citations=[c.model_dump(mode="json") for c in citations],
            )
        )
        await db.commit()
        yield f"event: done\ndata: {json.dumps({'conversation_id': str(conversation.id)})}\n\n"

    first = (
        f"event: citations\ndata: {json.dumps([c.model_dump(mode='json') for c in citations])}\n\n"
    )

    async def stream():
        yield first
        async for event in events():
            yield event

    return StreamingResponse(stream(), media_type="text/event-stream")
