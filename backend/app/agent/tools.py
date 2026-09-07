from langchain_core.tools import tool

from app.rag.retriever import retrieve


@tool
async def search_documents(query: str) -> str:
    """Search the user's document library for information relevant to a query.

    Use this tool before answering questions about the user's documents, projects,
    notes, or other personal information that may be stored in the knowledge base.
    """
    documents = await retrieve(query)
    if not documents:
        return "No relevant documents were found."

    results: list[str] = []
    for index, document in enumerate(documents, start=1):
        source = document.metadata.get("source", "Unknown source")
        results.append(f"[Document {index} | Source: {source}]\n{document.page_content}")
    return "\n\n".join(results)
