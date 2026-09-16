import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.agent import get_agent
from app.auth import Identity, apply_visitor_cookie, get_identity, require_admin, require_csrf
from app.database.connection import SessionLocal, get_session
from app.database.models import Conversation, Message
from app.database.repository import add_message, create_conversation, get_conversation, list_conversations
from app.prompts.system import SYSTEM_PROMPT

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)
NEW_CONVERSATION_TITLE = "New Conversation"


class InitialQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=20_000)

    @field_validator("message")
    @classmethod
    def trim_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message must not be blank")
        return value


class ChatRequest(InitialQuestion):
    conversation_id: uuid.UUID | None = None


class ConversationCreate(InitialQuestion):
    pass


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


def event_content(value: object) -> str:
    """Convert a tool event result into the text stored for administrator review."""
    if value is None:
        return ""
    content = getattr(value, "content", value)
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, default=str)


@router.get("/conversations", response_model=list[ConversationResponse])
async def conversations(
    response: Response,
    identity: Identity = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    response.headers["Cache-Control"] = "no-store"
    apply_visitor_cookie(response, identity)
    return await list_conversations(session, identity)


async def create_new_conversation(
    session: AsyncSession, identity: Identity
) -> Conversation:
    conversation = await create_conversation(
        session, NEW_CONVERSATION_TITLE, identity.visitor_session_id
    )
    await add_message(session, conversation, "system", SYSTEM_PROMPT)
    return conversation


@router.post(
    "/conversations", response_model=ConversationResponse, status_code=201,
    dependencies=[Depends(require_csrf)],
)
async def new_conversation(
    body: ConversationCreate,
    response: Response,
    identity: Identity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
):
    conversation = await create_new_conversation(session, identity)
    apply_visitor_cookie(response, identity)
    return conversation


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def conversation_detail(
    conversation_id: uuid.UUID,
    response: Response,
    include_internal: bool = False,
    identity: Identity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
):
    response.headers["Cache-Control"] = "no-store"
    conversation = await get_conversation(session, conversation_id, identity)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    apply_visitor_cookie(response, identity)
    messages = sorted(conversation.messages, key=lambda message: message.created_at)
    if identity.is_admin and include_internal:
        if not any(message.role == "system" for message in messages):
            messages.insert(0, Message(
                id=uuid.uuid5(conversation.id, "system-prompt"),
                conversation_id=conversation.id,
                role="system",
                content=SYSTEM_PROMPT,
                created_at=conversation.created_at,
            ))
        messages.sort(key=lambda message: (message.role != "system", message.created_at))
    else:
        messages = [message for message in messages if message.role in {"user", "assistant"}]
    return ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[MessageResponse.model_validate(message) for message in messages],
    )


@router.delete(
    "/conversations/{conversation_id}", status_code=204,
    dependencies=[Depends(require_csrf)],
)
async def delete_conversation(
    conversation_id: uuid.UUID,
    identity: Identity = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    conversation = await get_conversation(session, conversation_id, identity)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await session.delete(conversation)
    await session.commit()
    return Response(status_code=204)


@router.post("/chat", dependencies=[Depends(require_csrf)])
async def chat(body: ChatRequest, identity: Identity = Depends(get_identity)):
    # Finish validation, authorization, ownership and the first write before SSE
    # headers are sent. Keep the stream's database session independent of FastAPI's
    # dependency teardown timing.
    async with SessionLocal() as session:
        if body.conversation_id:
            conversation = await get_conversation(session, body.conversation_id, identity)
            if conversation is None:
                raise HTTPException(status_code=404, detail="Conversation not found")
            history = [
                history_message(item.role, item.content)
                for item in sorted(conversation.messages, key=lambda item: item.created_at)
                if item.role in {"user", "assistant"}
            ]
        else:
            conversation = await create_new_conversation(session, identity)
            history = []
        await add_message(session, conversation, "user", body.message)
        conversation_id, title = conversation.id, conversation.title

    async def stream() -> AsyncIterator[str]:
        async with SessionLocal() as session:
            try:
                yield sse("metadata", {"conversation_id": str(conversation_id), "title": title})
                conversation = await get_conversation(session, conversation_id, identity)
                if conversation is None:
                    raise RuntimeError("Conversation became unavailable")

                state = {"messages": [*history, HumanMessage(content=body.message)]}
                final_response = ""
                async for event in get_agent().astream_events(state, version="v2"):
                    if event["event"] == "on_chat_model_stream":
                        chunk = event["data"]["chunk"].content
                        if isinstance(chunk, str) and chunk:
                            final_response += chunk
                            yield sse("token", chunk)
                    elif event["event"] == "on_tool_end":
                        content = event_content(event.get("data", {}).get("output"))
                        if content:
                            await add_message(session, conversation, "tool", content)

                if not final_response:
                    raise RuntimeError("The model returned an empty response")

                message: Message = await add_message(
                    session, conversation, "assistant", final_response
                )
                yield sse("done", {"message_id": str(message.id)})
            except Exception as exc:
                await session.rollback()
                # Provider exception messages can contain request credentials.
                logger.error("Assistant response failed (%s)", type(exc).__name__)
                yield sse(
                    "error",
                    {"message": "Assistant is currently unavailable. Please try again."},
                )

    response = StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
    apply_visitor_cookie(response, identity)
    return response
