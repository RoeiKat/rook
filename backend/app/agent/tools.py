import re

from langchain_core.tools import tool

from app.rag.retriever import retrieve


_ROEI_NAME_VARIANTS = re.compile(
    r"(?<!\w)(?:Roei|roei|ROEI|Roi|roi|Roie|roie|ROIE|רועי)(?!\w)"
)
_RETRIEVAL_SUBJECT = re.compile(r"(?<!\w)(?:Roei|Rook)(?!\w)")


def normalize_roei_query(query: str) -> str:
    """Normalize explicit name variants without rewriting financial uppercase ROI."""
    return _ROEI_NAME_VARIANTS.sub("Roei", query)


@tool
async def search_documents(query: str) -> str:
    """Look up facts needed to answer a question about Roei or Rook.

    Use only for factual questions, never greetings or small talk. Include Roei or
    Rook in the query, and base the answer only on explicit facts in the result.
    """
    normalized_query = normalize_roei_query(query)
    if not _RETRIEVAL_SUBJECT.search(normalized_query):
        return (
            "No lookup was performed because the query does not identify Roei or Rook."
        )

    documents = await retrieve(normalized_query)
    if not documents:
        return "No relevant information was found."

    results = [
        f"[Context {index}]\n{document.page_content}"
        for index, document in enumerate(documents, start=1)
    ]
    return (
        "Use this internal context to answer directly. Never mention the context or "
        "how it was obtained. State only explicit claims and do not infer missing facts.\n\n"
        + "\n\n".join(results)
    )
