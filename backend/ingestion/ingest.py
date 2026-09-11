import argparse
import asyncio

from app.database.connection import SessionLocal, engine
from app.database.migrations import migrate_schema
from ingestion.service import ingest_dirty_documents, reconcile_local_documents


async def run() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(migrate_schema)
    async with SessionLocal() as session:
        await reconcile_local_documents(session)
        result = await ingest_dirty_documents(session)
    await engine.dispose()
    print(
        f"Processed {result['processed']} document(s), deleted {result['deleted']}, "
        f"failed {result['failed']}; dirty={result['dirty']}"
    )


def main() -> None:
    argparse.ArgumentParser(description="Synchronize configured documents with Pinecone").parse_args()
    asyncio.run(run())


if __name__ == "__main__":
    main()
