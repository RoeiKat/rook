import argparse
import asyncio

from app.database.connection import SessionLocal, engine
from app.database.migrations import migrate_schema
from ingestion.service import ingest_dirty_documents, reconcile_local_documents


async def run() -> None:
    """Migrate storage, reconcile documents, and ingest all pending changes."""
    # Open a transaction dedicated to schema migration.
    async with engine.begin() as connection:
        # Run the synchronous migration function through SQLAlchemy's async bridge.
        await connection.run_sync(migrate_schema)
    # Open one database session for reconciliation and ingestion.
    async with SessionLocal() as session:
        # Reflect manual local-file changes in the database.
        await reconcile_local_documents(session)
        # Synchronize dirty database records with Pinecone.
        result = await ingest_dirty_documents(session)
    # Release pooled database connections before the process exits.
    await engine.dispose()
    # Print a concise summary for operators and scripts.
    print(
        f"Processed {result['processed']} document(s), deleted {result['deleted']}, "
        f"failed {result['failed']}; dirty={result['dirty']}"
    )


def main() -> None:
    """Parse CLI arguments and execute the asynchronous ingestion run."""
    # Validate that no unsupported CLI arguments were supplied.
    argparse.ArgumentParser(description="Synchronize configured documents with Pinecone").parse_args()
    # Create an event loop and run ingestion to completion.
    asyncio.run(run())


# Execute the CLI only when this module is run directly.
if __name__ == "__main__":
    main()
