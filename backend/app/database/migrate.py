"""Explicit schema-migration command for production deployments."""

import asyncio

from app.database.connection import engine, migration_engine
from app.database.migrations import migrate_schema


async def run() -> None:
    async with migration_engine.begin() as connection:
        await connection.run_sync(migrate_schema)
    await engine.dispose()
    if migration_engine is not engine:
        await migration_engine.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
