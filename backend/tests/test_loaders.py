from ingestion.loaders import load_document_bytes


def test_text_bytes_are_loaded_without_a_temporary_file(monkeypatch):
    def unexpected_temporary_file(*args, **kwargs):
        raise AssertionError("text ingestion must not use temporary files")

    monkeypatch.setattr(
        "ingestion.loaders.tempfile.NamedTemporaryFile",
        unexpected_temporary_file,
    )

    documents = load_document_bytes("notes.md", "hello rook".encode())

    assert len(documents) == 1
    assert documents[0].page_content == "hello rook"
    assert documents[0].metadata == {"source": "notes.md"}
