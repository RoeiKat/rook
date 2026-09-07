import argparse
from pathlib import Path

from app.rag.vector_store import get_vector_store
from ingestion.chunking import chunk_documents
from ingestion.loaders import load_documents


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest local documents into Pinecone")
    parser.add_argument("directory", nargs="?", type=Path, default=Path(__file__).parent / "documents")
    args = parser.parse_args()
    documents = load_documents(args.directory)
    chunks = chunk_documents(documents)
    if not chunks:
        print(f"No supported documents found in {args.directory}")
        return
    get_vector_store().add_documents(chunks)
    print(f"Ingested {len(chunks)} chunks from {len(documents)} document pages")


if __name__ == "__main__":
    main()
