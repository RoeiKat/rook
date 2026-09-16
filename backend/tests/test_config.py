from app.config import async_database_url, get_settings


def test_async_database_url_adapts_neon_connection_options():
    url = (
        "postgresql://rook:secret@example.neon.tech/rook"
        "?sslmode=require&channel_binding=require&application_name=rook"
    )

    normalized = async_database_url(url)

    assert normalized.startswith("postgresql+asyncpg://")
    assert "ssl=require" in normalized
    assert "application_name=rook" in normalized
    assert "sslmode=" not in normalized
    assert "channel_binding=" not in normalized


def test_settings_use_pooled_url_for_app_and_direct_url_for_migrations(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://rook@direct.example/rook?sslmode=require")
    monkeypatch.setenv(
        "DATABASE_URL_POOLED",
        "postgresql://rook@pooled.example/rook?sslmode=require",
    )
    monkeypatch.delenv("DATABASE_URL_UNPOOLED", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert "pooled.example" in settings.database_url
    assert "direct.example" in settings.database_migration_url
    get_settings.cache_clear()
