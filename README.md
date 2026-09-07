# Rook

Rook is a personal AI assistant MVP with a React chat interface, FastAPI streaming
API, PostgreSQL conversation history, and a LangChain `create_agent` backed by the
LangGraph runtime. The agent can query Pinecone through a document-search tool.

## Run with Docker

1. Copy `backend/.env.example` to `backend/.env` and provide `OPENAI_API_KEY`.
2. Set `PINECONE_API_KEY` and an existing `PINECONE_INDEX` to enable RAG. Without a
   Pinecone key, chat still works and retrieval returns no context.
3. Run `docker compose up --build`.
4. Open `http://localhost:5173`.

The API is available at `http://localhost:8000`. Database tables are created at
backend startup for this MVP.

## Local development

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

## Ingest documents

Place `.txt`, `.md`, or `.pdf` files in `backend/ingestion/documents`, then run this
from `backend`:

```powershell
python -m ingestion.ingest
```

A different directory can be passed as the first argument. Documents and queries
use the same embedding factory and Pinecone namespace.

## Switch to Ollama

Change configuration only:

```env
LLM_MODEL=ollama:granite4.1:3b
EMBEDDING_MODEL=ollama:nomic-embed-text
OLLAMA_BASE_URL=http://localhost:11434
```

LangChain resolves each integration from the prefix in the model string. The agent
and RAG code do not contain provider-specific branches.

## Tests

```powershell
cd backend
pytest

cd ..\frontend
npm test
npm run build
```
