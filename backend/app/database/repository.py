import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Conversation, Message


async def create_conversation(session: AsyncSession, title: str = "New conversation") -> Conversation:
    conversation = Conversation(title=title)
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return conversation


async def list_conversations(session: AsyncSession) -> list[Conversation]:
    result = await session.scalars(select(Conversation).order_by(Conversation.updated_at.desc()))
    return list(result)


async def get_conversation(session: AsyncSession, conversation_id: uuid.UUID) -> Conversation | None:
    return await session.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(selectinload(Conversation.messages))
    )


async def add_message(
    session: AsyncSession, conversation: Conversation, role: str, content: str
) -> Message:
    message = Message(conversation_id=conversation.id, role=role, content=content)
    session.add(message)
    conversation.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(message)
    return message
