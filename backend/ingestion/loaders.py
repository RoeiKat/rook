from pathlib import Path
import tempfile

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_core.documents import Document

SUPPORTED_EXTENSIONS = {".md", ".pdf", ".txt"}


def load_documents(directory: Path) -> list[Document]:
    documents: list[Document] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        loader = PyPDFLoader(str(path)) if path.suffix.lower() == ".pdf" else TextLoader(str(path), encoding="utf-8")
        documents.extend(loader.load())
    return documents


def load_document_bytes(filename: str, content: bytes) -> list[Document]:
    """Load one validated document while retaining the project's existing loaders."""
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError("Unsupported document extension")
    with tempfile.NamedTemporaryFile(suffix=suffix) as handle:
        handle.write(content)
        handle.flush()
        loader = PyPDFLoader(handle.name) if suffix == ".pdf" else TextLoader(handle.name, encoding="utf-8")
        return loader.load()
