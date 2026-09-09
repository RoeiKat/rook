import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import Identity
from app.database.models import Conversation, Message


async def create_conversation(
    session: AsyncSession, title: str, visitor_session_id: uuid.UUID
) -> Conversation:
    if not title.strip() or len(title) > 160 or len(title.split()) > 5:
        raise ValueError("A validated, concise conversation title is required")
    if visitor_session_id is None:
        raise ValueError("Visitor ownership is required for new conversations")
    conversation = Conversation(title=title, visitor_session_id=visitor_session_id)
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return conversation


async def list_conversations(session: AsyncSession, identity: Identity) -> list[Conversation]:
    if not identity.is_admin:
        raise PermissionError("Administrator authentication required")
    result = await session.scalars(select(Conversation).order_by(Conversation.updated_at.desc()))
    return list(result)


async def get_conversation(
    session: AsyncSession, conversation_id: uuid.UUID, identity: Identity
) -> Conversation | None:
    query = select(Conversation).where(Conversation.id == conversation_id)
    if not identity.is_admin:
        query = query.where(Conversation.visitor_session_id == identity.visitor_session_id)
    # selectinload only runs for authorized rows returned by the ownership predicate.
    return await session.scalar(query.options(selectinload(Conversation.messages)))


async def add_message(
    session: AsyncSession, conversation: Conversation, role: str, content: str
) -> Message:
    message = Message(conversation_id=conversation.id, role=role, content=content)
    session.add(message)
    conversation.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(message)
    return message
