import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.agent import get_agent
from app.database.connection import SessionLocal, get_session
from app.database.models import Conversation, Message
from app.database.repository import add_message, create_conversation, get_conversation, list_conversations

router = APIRouter(prefix="/api")


class ChatRequest(BaseModel):
    conversation_id: uuid.UUID | None = None
    message: str = Field(min_length=1, max_length=20_000)


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", min_length=1, max_length=160)


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    role: str
    content: str
    created_at: datetime


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationResponse):
    messages: list[MessageResponse]


def sse(event: str, data: dict | str) -> str:
    payload = json.dumps(data)
    return f"event: {event}\ndata: {payload}\n\n"


def history_message(role: str, content: str):
    return HumanMessage(content=content) if role == "user" else AIMessage(content=content)


@router.get("/conversations", response_model=list[ConversationResponse])
async def conversations(session: AsyncSession = Depends(get_session)):
    return await list_conversations(session)


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
async def new_conversation(body: ConversationCreate, session: AsyncSession = Depends(get_session)):
    return await create_conversation(session, body.title)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def conversation_detail(conversation_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    conversation = await get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conversation.messages.sort(key=lambda message: message.created_at)
    return conversation


@router.post("/chat")
async def chat(body: ChatRequest):
    async def stream() -> AsyncIterator[str]:
        async with SessionLocal() as session:
            try:
                conversation: Conversation | None = None
                if body.conversation_id:
                    conversation = await get_conversation(session, body.conversation_id)
                    if conversation is None:
                        yield sse("error", {"message": "Conversation not found"})
                        return
                else:
                    title = body.message.strip()[:60]
                    conversation = await create_conversation(session, title)

                history = [history_message(item.role, item.content) for item in conversation.messages]
                await add_message(session, conversation, "user", body.message.strip())
                yield sse("metadata", {"conversation_id": str(conversation.id)})

                state = {"messages": [*history, HumanMessage(content=body.message.strip())]}
                final_response = ""
                async for event in get_agent().astream_events(state, version="v2"):
                    if event["event"] == "on_chat_model_stream":
                        chunk = event["data"]["chunk"].content
                        if isinstance(chunk, str) and chunk:
                            final_response += chunk
                            yield sse("token", chunk)

                if not final_response:
                    raise RuntimeError("The model returned an empty response")

                message: Message = await add_message(
                    session, conversation, "assistant", final_response
                )
                yield sse("done", {"message_id": str(message.id)})
            except Exception as exc:
                await session.rollback()
                yield sse("error", {"message": str(exc)})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
