"""Small, transactional migrations for the existing PostgreSQL schema."""

from sqlalchemy import Connection, inspect, text

from app.database.models import Base, Conversation

OWNERSHIP_MIGRATION = "001_visitor_and_administrator_sessions"
INGESTION_MIGRATION = "002_knowledge_documents"


def migrate_schema(connection: Connection) -> None:
    """Run inside engine.begin(); preserve every existing conversation and message."""
    if connection.dialect.name == "postgresql":
        # Multiple API workers may start together. Serialize their schema changes.
        connection.execute(text("SELECT pg_advisory_xact_lock(734029410)"))
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version VARCHAR(100) PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
    )
    ownership_applied = connection.scalar(
        text("SELECT version FROM schema_migrations WHERE version = :version"),
        {"version": OWNERSHIP_MIGRATION},
    )
    # Creates missing tables, including ownership/session storage, on both new and old DBs.
    Base.metadata.create_all(connection)
    if not ownership_applied:
        columns = {column["name"] for column in inspect(connection).get_columns("conversations")}
        if "visitor_session_id" not in columns:
            uuid_type = "UUID" if connection.dialect.name == "postgresql" else "CHAR(32)"
            connection.execute(
                text(
                    f"ALTER TABLE conversations ADD COLUMN visitor_session_id {uuid_type} "
                    "REFERENCES visitor_sessions(id)"
                )
            )
        for index in Conversation.__table__.indexes:
            index.create(connection, checkfirst=True)
        if connection.dialect.name == "postgresql":
            connection.execute(text("ALTER TABLE conversations ALTER COLUMN title DROP DEFAULT"))
        connection.execute(
            text("INSERT INTO schema_migrations (version) VALUES (:version)"),
            {"version": OWNERSHIP_MIGRATION},
        )

    ingestion_applied = connection.scalar(
        text("SELECT version FROM schema_migrations WHERE version = :version"),
        {"version": INGESTION_MIGRATION},
    )
    if not ingestion_applied:
        connection.execute(text(
            "INSERT INTO ingestion_state (id, is_running) VALUES (1, false) "
            "ON CONFLICT (id) DO NOTHING"
        ))
        connection.execute(
            text("INSERT INTO schema_migrations (version) VALUES (:version)"),
            {"version": INGESTION_MIGRATION},
        )
