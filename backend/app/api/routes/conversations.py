import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DbDep, UserDep
from app.models import Conversation, Message, User
from app.schemas.chat import ConversationOut, MessageOut

router = APIRouter(prefix="/conversations", tags=["conversations"])


class MessageListOut(BaseModel):
    conversation_id: uuid.UUID
    messages: list[MessageOut]


async def _get_owned_conversation(db, user: User, conversation_id: uuid.UUID) -> Conversation:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation


@router.get("", response_model=list[ConversationOut])
async def list_conversations(user: UserDep, db: DbDep) -> list[Conversation]:
    result = await db.scalars(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
    )
    return list(result)


@router.get("/{conversation_id}/messages", response_model=MessageListOut)
async def get_messages(conversation_id: uuid.UUID, user: UserDep, db: DbDep) -> MessageListOut:
    await _get_owned_conversation(db, user, conversation_id)
    result = await db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    return MessageListOut(conversation_id=conversation_id, messages=list(result))


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: uuid.UUID, user: UserDep, db: DbDep) -> None:
    conversation = await _get_owned_conversation(db, user, conversation_id)
    await db.delete(conversation)
    await db.commit()
