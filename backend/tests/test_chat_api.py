"""Exercise access and the existing streaming workflow with real database writes."""

import json
import os
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import chat
from app.auth import hash_password
from app.config import get_settings
from app.database.connection import get_session
from app.database.models import Base, Conversation, Message
from app.main import app

HEADERS = {"Origin": "http://localhost:5173", "X-CSRF-Protection": "1"}


@pytest.fixture(params=["sqlite", "postgres"])
async def database(request):
    if request.param == "sqlite":
        engine = create_async_engine("sqlite+aiosqlite://")
        admin_engine = None
    else:
        url = os.getenv("TEST_DATABASE_URL")
        if not url:
            pytest.skip("Set TEST_DATABASE_URL to run isolated PostgreSQL API checks")
        schema = "test_" + uuid.uuid4().hex
        admin_engine = create_async_engine(url)
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        if admin_engine is not None:
            async with admin_engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await admin_engine.dispose()


@pytest.fixture
async def api(database, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-with-more-than-32-characters")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("ADMIN_USERNAME", "test-admin")
    monkeypatch.setenv("ADMIN_ACCESS_PASSWORD", "test-access-password")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", hash_password("test-password"))
    monkeypatch.setenv("FRONTEND_ORIGINS", "http://localhost:5173")
    get_settings.cache_clear()

    async def override_session():
        async with database() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setattr(chat, "SessionLocal", database)
    title = AsyncMock(return_value="Roei's Python Projects")
    monkeypatch.setattr(chat, "generate_title", title)
    states = []
    inserted_titles = []

    def record_insert(mapper, connection, target):
        inserted_titles.append(target.title)

    event.listen(Conversation, "before_insert", record_insert)

    async def events(state, version):
        states.append(state)
        for token in ["A grounded ", "answer."]:
            yield {"event": "on_chat_model_stream", "data": {"chunk": SimpleNamespace(content=token)}}

    agent = Mock(return_value=SimpleNamespace(astream_events=events))
    monkeypatch.setattr(chat, "get_agent", agent)

    @asynccontextmanager
    async def client():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver", headers=HEADERS
        ) as instance:
            yield instance

    try:
        yield SimpleNamespace(
            client=client, database=database, title=title, agent=agent, states=states,
            inserted_titles=inserted_titles,
        )
    finally:
        event.remove(Conversation, "before_insert", record_insert)
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def events(response):
    assert response.status_code == 200, response.text
    result = []
    for block in response.text.strip().split("\n\n"):
        name, payload = block.split("\n", 1)
        result.append((name.removeprefix("event: "), json.loads(payload.removeprefix("data: "))))
    return result


async def test_first_message_title_cookie_stream_and_followup(api, monkeypatch):
    real_sse = chat.sse
    completion_was_persisted = []
    real_add_message = chat.add_message

    async def checked_add_message(session, conversation, role, content):
        message = await real_add_message(session, conversation, role, content)
        if role == "assistant":
            async with api.database() as reader:
                assert await reader.get(Message, message.id) is not None
            completion_was_persisted.append(str(message.id))
        return message

    def checked_sse(event, data):
        if event == "done":
            assert data["message_id"] in completion_was_persisted
        return real_sse(event, data)

    monkeypatch.setattr(chat, "add_message", checked_add_message)
    monkeypatch.setattr(chat, "sse", checked_sse)
    async with api.client() as visitor:
        response = await visitor.post("/api/chat", json={"message": "  What Python projects has Roei built?  "})
        assert "HttpOnly" in response.headers["set-cookie"]
        stream = events(response)
        assert [name for name, _ in stream] == ["metadata", "token", "token", "done"]
        metadata = stream[0][1]
        assert metadata["title"] == "Roei's Python Projects"
        assert api.inserted_titles == [metadata["title"]]
        assert "".join(data for name, data in stream if name == "token") == "A grounded answer."
        api.title.assert_awaited_once_with("What Python projects has Roei built?")
        conversation_id = metadata["conversation_id"]

        # A fresh client with the browser's cookie can reopen after a page refresh.
        async with api.client() as refreshed:
            refreshed.cookies.update(visitor.cookies)
            reopened = await refreshed.get(f"/api/conversations/{conversation_id}")
            assert reopened.status_code == 200
            assert [item["content"] for item in reopened.json()["messages"]] == [
                "What Python projects has Roei built?", "A grounded answer."
            ]
            followup = await refreshed.post("/api/chat", json={"conversation_id": conversation_id, "message": "Tell me more"})
            assert events(followup)[0][1] == metadata
        assert api.title.await_count == 1
        assert [item.content for item in api.states[-1]["messages"]] == [
            "What Python projects has Roei built?", "A grounded answer.", "Tell me more"
        ]


async def test_explicit_creation_has_final_title_and_no_message(api):
    async with api.client() as visitor:
        response = await visitor.post("/api/conversations", json={"message": "What Python projects has Roei built?"})
        assert response.status_code == 201
        created = response.json()
        assert created["title"] == "Roei's Python Projects"
        assert api.inserted_titles == [created["title"]]
        async with api.database() as session:
            stored = await session.get(Conversation, uuid.UUID(created["id"]))
            assert stored.title == created["title"]
            assert stored.visitor_session_id is not None
            assert await session.scalar(select(func.count()).select_from(Message)) == 0
        api.agent.assert_not_called()
        await visitor.post("/api/chat", json={"conversation_id": created["id"], "message": "What Python projects has Roei built?"})
        detail = (await visitor.get(f'/api/conversations/{created["id"]}')).json()
        assert [message["role"] for message in detail["messages"]] == ["user", "assistant"]
        assert api.title.await_count == 1


@pytest.mark.parametrize("path,body", [
    ("/api/chat", {"message": " \n\t "}),
    ("/api/conversations", {"message": " \n "}),
    ("/api/conversations", {}),
    ("/api/conversations", {"title": "New conversation"}),
])
async def test_invalid_creation_does_not_insert_or_call_models(api, path, body):
    async with api.client() as visitor:
        assert (await visitor.post(path, json=body)).status_code == 422
    api.title.assert_not_called()
    api.agent.assert_not_called()
    async with api.database() as session:
        assert await session.scalar(select(func.count()).select_from(Conversation)) == 0
        assert await session.scalar(select(func.count()).select_from(Message)) == 0


async def test_cross_session_and_nonexistent_ids_are_indistinguishable(api):
    async with api.client() as owner, api.client() as stranger:
        created = await owner.post("/api/chat", json={"message": "What are Roei's projects?"})
        conversation_id = events(created)[0][1]["conversation_id"]
        api.title.reset_mock()
        api.agent.reset_mock()
        for candidate in [conversation_id, str(uuid.uuid4())]:
            detail = await stranger.get(f"/api/conversations/{candidate}")
            continuation = await stranger.post("/api/chat", json={"conversation_id": candidate, "message": "secret?"})
            assert detail.status_code == continuation.status_code == 404
            assert detail.json() == continuation.json() == {"detail": "Conversation not found"}
            assert "text/event-stream" not in continuation.headers["content-type"]
        assert (await stranger.get("/api/conversations")).status_code == 401
        assert (await owner.get("/api/conversations")).status_code == 401
    api.title.assert_not_called()
    api.agent.assert_not_called()
    async with api.database() as session:
        assert await session.scalar(select(func.count()).select_from(Message)) == 2


async def test_administrator_can_inspect_historical_rows_and_logout(api):
    async with api.database() as session:
        historical = Conversation(title="Original historical title")
        session.add(historical)
        await session.commit()
        historical_id = str(historical.id)
    async with api.client() as administrator:
        assert (await administrator.get(f"/api/conversations/{historical_id}")).status_code == 404
        assert (await administrator.post("/api/auth/access", json={"password": "test-access-password"})).status_code == 200
        login = await administrator.post("/api/auth/login", json={"username": "test-admin", "password": "test-password"})
        assert login.status_code == 200
        listing = await administrator.get("/api/conversations")
        assert listing.status_code == 200
        assert listing.json()[0]["title"] == "Original historical title"
        assert (await administrator.get(f"/api/conversations/{historical_id}")).status_code == 200
        continuation = await administrator.post("/api/chat", json={"conversation_id": historical_id, "message": "Hello"})
        assert events(continuation)[0][1]["title"] == "Original historical title"
        assert (await administrator.post("/api/auth/logout")).status_code == 200
        assert (await administrator.get("/api/conversations")).status_code == 401
        assert (await administrator.get(f"/api/conversations/{historical_id}")).status_code == 404
    api.title.assert_not_called()


async def test_failed_stream_does_not_persist_partial_assistant_or_emit_done(api, monkeypatch):
    async def failed_events(state, version):
        yield {"event": "on_chat_model_stream", "data": {"chunk": SimpleNamespace(content="Partial")}}
        raise RuntimeError("provider secret details")

    monkeypatch.setattr(chat, "get_agent", lambda: SimpleNamespace(astream_events=failed_events))
    async with api.client() as visitor:
        response = await visitor.post("/api/chat", json={"message": "What has Roei built?"})
        stream = events(response)
        assert [event for event, _ in stream] == ["metadata", "token", "error"]
        assert "provider secret details" not in response.text
        detail = (await visitor.get(f'/api/conversations/{stream[0][1]["conversation_id"]}')).json()
        assert [message["role"] for message in detail["messages"]] == ["user"]


@pytest.mark.parametrize("headers", [
    {}, {"Origin": "http://localhost:5173"},
    {"Origin": "https://untrusted.example", "X-CSRF-Protection": "1"},
])
async def test_mutations_require_csrf_before_model_or_write(api, headers):
    async with api.client() as visitor:
        visitor.headers.clear()
        response = await visitor.post("/api/chat", json={"message": "Hello"}, headers=headers)
        assert response.status_code == 403
    api.title.assert_not_called()
    api.agent.assert_not_called()


async def test_login_validation_does_not_echo_password(api):
    secret_password = "private-password-" * 100
    async with api.client() as visitor:
        await visitor.post("/api/auth/access", json={"password": "test-access-password"})
        response = await visitor.post("/api/auth/login", json={"username": "test-admin", "password": secret_password})
        assert response.status_code == 422
        assert "private-password" not in response.text
        assert all("input" not in error for error in response.json()["detail"])


@pytest.mark.parametrize("path", ["/api/chat", "/api/conversations"])
async def test_title_model_failure_falls_back_before_insertion_and_chat_still_works(api, monkeypatch, path):
    from app.agent import titles

    monkeypatch.setattr(chat, "generate_title", titles.generate_title)
    model = SimpleNamespace(ainvoke=AsyncMock(side_effect=TimeoutError("sensitive provider error")))
    monkeypatch.setattr(titles, "init_chat_model", lambda _: model)
    async with api.client() as visitor:
        response = await visitor.post(path, json={"message": "What projects has Roei built with Python?"})
        expected = "What projects has Roei built"
        assert api.inserted_titles == [expected]
        if path == "/api/chat":
            assert events(response)[0][1]["title"] == expected
            assert events(response)[-1][0] == "done"
        else:
            assert response.status_code == 201
            assert response.json()["title"] == expected
