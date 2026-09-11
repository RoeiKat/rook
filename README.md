# Rook

Rook is a React and FastAPI chat application. Conversations and messages live in
PostgreSQL, answers stream from a LangChain agent, and optional document search
uses Pinecone.

## Development with Docker

Copy the example backend environment file, then start the application:

```powershell
Copy-Item backend/.env.example backend/.env
docker compose up --build
```

Open `http://localhost:5173`. Docker Compose runs Vite and Uvicorn in development
mode, so frontend and backend changes reload without rebuilding. Browser errors
point to the TypeScript source. The backend is available at `http://localhost:8000`.

The development setup has a local-only session secret and uses non-Secure cookies
over HTTP. You therefore do not need to configure authentication before testing
public chat. Production mode (`APP_ENV=production`) requires a random
`SESSION_SECRET` of at least 32 characters and defaults to Secure cookies.

Source changes reload automatically. After changing an environment variable or a
dependency, recreate or rebuild the relevant container:

```powershell
docker compose up -d --force-recreate backend
```

## Environment files

Backend settings are documented in `backend/.env.example`:

- `LLM_PROVIDER` and `LLM_MODEL` select the chat and title model.
- `EMBEDDING_PROVIDER` and `EMBEDDING_MODEL` select the embedding model.
- `OLLAMA_BASE_URL` points Docker at Ollama on the host machine.
- `OPENAI_API_KEY` is required when an OpenAI model is selected.
- `PINECONE_API_KEY`, `PINECONE_INDEX`, and `PINECONE_NAMESPACE` configure RAG.
- `DOCUMENT_STORAGE_LOCAL_PATH` and `DOCUMENT_UPLOAD_MAX_BYTES` configure local
  storage and the upload limit.
- `ADMIN_USERNAME` and `ADMIN_PASSWORD_HASH` enable the `/admin` login.
- `FRONTEND_ORIGINS` lists browser origins allowed to call the API.

Frontend settings are documented separately in `frontend/.env.example`:

- `VITE_API_URL` is the public API URL used by the browser. Leave it empty when
  using the included Vite proxy.
- `API_PROXY_TARGET` is the backend target used only by the Vite development
  server. Docker Compose sets it to `http://backend:8000` automatically.

Only variables prefixed with `VITE_` are included in browser code. Never put
passwords, API keys, or session secrets in the frontend environment file.

## Local development without Docker

Run PostgreSQL separately and then start the backend:

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
Copy-Item .env.example .env
npm install
npm run dev
```

## How conversations work

The visitor cookie contains a signed browser-session ID. The backend uses that ID
to prevent one visitor from opening another visitor's conversation. The cookie is
HttpOnly, so React does not read or manage it.

The current conversation ID is also stored in `localStorage`. This lets the UI ask
the backend to reopen that conversation after a refresh; the cookie remains the
actual ownership check.

Clicking **New conversation** only clears the current ID and messages in the
browser. It does not create a database row. The next submitted message sends a
null `conversation_id`, and the backend then:

1. creates the conversation and title;
2. saves the user message;
3. streams the assistant answer;
4. saves the completed assistant message.

The relevant code is concentrated in `backend/app/api/chat.py`,
`backend/app/auth.py`, and `frontend/src/components/ConversationChat.tsx`.

## Inspect PostgreSQL

Open an interactive PostgreSQL prompt in the Docker container:

```powershell
docker compose exec postgres psql -U rook -d rook
```

Useful read-only queries:

```sql
SELECT id, title, visitor_session_id, created_at, updated_at
FROM conversations
ORDER BY created_at DESC;

SELECT conversation_id, role, content, created_at
FROM messages
ORDER BY created_at DESC;

SELECT c.title, m.role, m.content, m.created_at
FROM conversations AS c
JOIN messages AS m ON m.conversation_id = c.id
ORDER BY c.created_at DESC, m.created_at;
```

Exit with `\q`. If `/api/chat` fails before returning its `metadata` event, check
these tables to see whether the first write occurred.

## Administrator login

The public chat needs no account. The `/admin` page uses one username and password
to list all conversations. Generate a password hash from `backend/`:

```powershell
python -m app.auth
```

Put the username and generated hash in `backend/.env`. Wrap the hash in single
quotes because it contains dollar signs:

```env
ADMIN_USERNAME=roei
ADMIN_PASSWORD_HASH='<generated hash>'
```

The browser receives one admin cookie after login. Logout deletes its matching
server-side session and clears the cookie.

## Document ingestion

Administrators can open `/admin`, select **Knowledge base**, and upload `.txt`,
`.md`, or `.pdf` documents. The default Docker configuration stores originals in
`backend/ingestion/documents`; PostgreSQL remains the inventory and synchronization
source of truth. Files placed there manually are discovered on the next inventory
or ingestion request.

The **Ingest changes** action replaces each changed document's Pinecone vectors by
stable document ID before upserting deterministic chunk IDs. Failed runs stay dirty
and can be retried. Deletion removes vectors first, then the original object, then
the database record; every step is safe to retry.

The CLI calls the same reconciliation and ingestion service as the administrator
API:

```powershell
cd backend
python -m ingestion.ingest
```

Documents and queries must use the same embedding model. Changing that model
requires re-ingesting into a compatible Pinecone index or namespace.

## Tests and production frontend image

Frontend tests live in `frontend/tests`.

```powershell
cd backend
pytest

cd ..\frontend
npm test
npm run build
```

Docker Compose uses the `development` stage of the frontend Dockerfile. To create
the optional Nginx production image:

```powershell
docker build --target production -t rook-frontend ./frontend
```
