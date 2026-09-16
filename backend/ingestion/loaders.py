from pathlib import Path
import tempfile

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_core.documents import Document

SUPPORTED_EXTENSIONS = {".md", ".pdf", ".txt"}
TEXT_ENCODING = "utf-8"
PDF_EXTENSION = ".pdf"


def _loader_for_path(path: Path, suffix: str):
    """Return the existing loader appropriate for a temporary or local path."""
    # PDFs need page-aware parsing; other supported files are UTF-8 text.
    if suffix == PDF_EXTENSION:
        return PyPDFLoader(str(path))
    # Decode Markdown and text files consistently.
    return TextLoader(str(path), encoding=TEXT_ENCODING)


def load_documents(directory: Path) -> list[Document]:
    """Load every supported document found recursively under a directory."""
    # Accumulate documents returned by each file loader.
    documents: list[Document] = []
    # Sort paths so repeated ingestion runs process files deterministically.
    for path in sorted(directory.rglob("*")):
        # Ignore directories and unsupported file types.
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        # Select a loader from the file's normalized extension.
        loader = _loader_for_path(path, path.suffix.lower())
        # Append every page or text document produced by the loader.
        documents.extend(loader.load())
    # Return the complete ordered set of loaded documents.
    return documents


def load_document_bytes(filename: str, content: bytes) -> list[Document]:
    """Load one supported byte payload through the existing file loaders."""
    # Normalize the supplied filename extension before validating it.
    suffix = Path(filename).suffix.lower()
    # Reject content types that the ingestion pipeline cannot parse.
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError("Unsupported document extension")
    # Close the temporary handle before path-based loaders reopen it. Windows
    # otherwise keeps an exclusive lock on NamedTemporaryFile.
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            handle.write(content)
            handle.flush()
            temporary_path = Path(handle.name)
        loader = _loader_for_path(temporary_path, suffix)
        return loader.load()
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
