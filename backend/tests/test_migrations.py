"""Verify additive upgrades against PostgreSQL, including rollback and old data."""

import os
import uuid

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.database.migrations import migrate_schema


@pytest.mark.postgres
async def test_existing_postgresql_database_migrates_without_changing_history():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to an isolated PostgreSQL database")
    schema = "migration_test_" + uuid.uuid4().hex
    admin_engine = create_async_engine(database_url)
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(database_url, connect_args={"server_settings": {"search_path": schema}})
    conversation_id, message_id = uuid.uuid4(), uuid.uuid4()
    try:
        async with engine.begin() as connection:
            await connection.execute(text("""
                CREATE TABLE conversations (
                    id UUID PRIMARY KEY,
                    title VARCHAR(160) NOT NULL DEFAULT 'New conversation',
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
            """))
            await connection.execute(text("""
                CREATE TABLE messages (
                    id UUID PRIMARY KEY,
                    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE NOT NULL,
                    role VARCHAR(16) NOT NULL, content TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
            """))
            await connection.execute(
                text("INSERT INTO conversations (id,title) VALUES (:id,:title)"),
                {"id": conversation_id, "title": "Historical title with original words intact"},
            )
            await connection.execute(
                text("INSERT INTO messages (id,conversation_id,role,content) VALUES (:id,:conversation_id,'user','Original content')"),
                {"id": message_id, "conversation_id": conversation_id},
            )
        # A failed deployment transaction can roll back all schema changes.
        with pytest.raises(RuntimeError, match="rollback"):
            async with engine.begin() as connection:
                await connection.run_sync(migrate_schema)
                raise RuntimeError("rollback")
        async with engine.begin() as connection:
            columns = await connection.run_sync(lambda sync: inspect(sync).get_columns("conversations"))
            assert "visitor_session_id" not in {column["name"] for column in columns}
            await connection.run_sync(migrate_schema)
            await connection.run_sync(migrate_schema)
            old = (await connection.execute(text("SELECT * FROM conversations WHERE id=:id"), {"id": conversation_id})).mappings().one()
            assert old["title"] == "Historical title with original words intact"
            assert old["visitor_session_id"] is None
            assert await connection.scalar(text("SELECT content FROM messages WHERE id=:id"), {"id": message_id}) == "Original content"
            assert await connection.scalar(text("SELECT count(*) FROM schema_migrations")) == 2
            columns = await connection.run_sync(lambda sync: inspect(sync).get_columns("conversations"))
            assert next(column for column in columns if column["name"] == "title")["default"] is None
            foreign_keys = await connection.run_sync(lambda sync: inspect(sync).get_foreign_keys("conversations"))
            assert any(key["referred_table"] == "visitor_sessions" for key in foreign_keys)
    finally:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin_engine.dispose()
