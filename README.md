# Rook

Rook is a personal AI assistant MVP with a React chat interface, FastAPI streaming
API, PostgreSQL conversation history, and a LangChain `create_agent` backed by the
LangGraph runtime. The agent can query Pinecone through a document-search tool.

## Run with Docker

1. Copy `backend/.env.example` to `backend/.env`, configure the model, and set a
   random `SESSION_SECRET` of at least 32 characters. For the local HTTP URLs
   below, explicitly set `COOKIE_SECURE=false`; keep it `true` when using HTTPS.
2. Provide `OPENAI_API_KEY` for OpenAI models/embeddings. Set `PINECONE_API_KEY` and an existing `PINECONE_INDEX` to enable RAG. Without a
   Pinecone key, chat still works and retrieval returns no context.
3. Run `docker compose up --build`.
4. Open `http://localhost:5173`.

The API is available at `http://localhost:8000`. Startup runs an additive,
transactional schema migration, including on an existing database. Existing
conversation titles and messages are preserved; conversations created before
visitor ownership was introduced are accessible only to the administrator.

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
use the same embedding model and Pinecone namespace.

## Models

Models are plain strings in the existing Python files:

- `app/agent/agent.py`: `model = "ollama:granite4.1:3b"`
- `app/rag/vector_store.py`: `embedding_model = "openai:text-embedding-3-small"`

Edit those strings to change models. Model selection does not read `.env`.
API keys and the Ollama connection URL remain in `.env`. Changing the
embedding model requires re-ingestion into a compatible Pinecone index/namespace.

The model string lives beside your chat agent in `app/agent/agent.py`. The agent
passes it directly to LangChain's `create_agent`; `app/agent/titles.py` uses the
same string for a direct, tool-free `init_chat_model(...).ainvoke(...)` call. The
existing document-search tool and answering agent remain in place. When Docker connects
to Ollama running on the host machine, use
`OLLAMA_BASE_URL=http://host.docker.internal:11434`. For a remote Ollama server,
replace it with that server's URL.

## Interface and logo

The public interface has a narrow logo/theme rail, top-right New conversation
and information controls, and a centered welcome/composer. The three welcome
sentences and typing timings are together in `frontend/src/components/Welcome.tsx`.
Reduced-motion preferences show a static heading. Colors and responsive layout
are in `frontend/src/index.css`; theme selection persists under `rook.theme`.

Replace `frontend/public/rook.svg` to update both logo placements through
`RookLogo.tsx`. The supplied SVG's geometry is unchanged; its black artwork is
inverted for dark mode. The info tooltip text is `INFO_TEXT` in `ChatWindow.tsx`.

After editing the frontend, rebuild its Docker image as well as the backend:
`docker compose up -d --build frontend backend`, then reload `http://localhost:5173`.
Local `node_modules`, build output, and backend virtual environments are excluded
from Docker contexts.

## Visitor sessions and administrator history

Visitors can chat without logging in. A server-issued HttpOnly cookie owns each
visitor's conversations, so the same browser can reopen them after refreshing.
The locally stored conversation UUID is only a convenience; a different visitor
receives the same `404` as for a nonexistent conversation. Clearing or expiring
the visitor cookie removes that browser's access. Global history is available
only at `/admin` after backend-verified administrator login.

To enable administrator login, set `ADMIN_USERNAME` and `ADMIN_PASSWORD_HASH` in
`backend/.env`. Generate the hash interactively from `backend/`:

```powershell
python -m app.auth
```

The helper prompts for the password without echoing it. Store the resulting hash,
not the password. Wrap the hash in single quotes in `.env` so Docker Compose keeps
its dollar signs literal: `ADMIN_PASSWORD_HASH='<generated hash>'`.
Generate `SESSION_SECRET` with a cryptographically secure random
generator; for example, `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
There are no default administrator credentials. Missing administrator settings
leave global history protected. Missing `SESSION_SECRET` disables browser-session
operations while `/health` remains public.

There is no registration endpoint or user creation flow. The only administrator
is the username/password hash you manage in `.env`; login cannot create accounts.
Session and password helpers are kept together in `app/auth.py`, with the
HTTP authentication routes in `app/api/auth.py`.

Set a separate `ADMIN_ACCESS_PASSWORD` in `backend/.env` to protect the login
page itself. Visit `/admin/access` and enter that password first; the frontend
sends it in the body of `POST /api/auth/access`. Correct verification establishes
an eight-hour HttpOnly access cookie. `GET /api/auth/access` verifies that cookie
before the frontend renders `/admin`, `/admin/login`, or `/login`. Missing,
incorrect, expired, or invalid access redirects to the homepage. Registration
remains disabled, and `/register` and `/registration` redirect home.

The backend also requires this access cookie on `POST /api/auth/login`; knowing
only the administrator's login credentials cannot bypass the page gate. The
access cookie grants no conversation privileges by itself. Logout revokes both
cookies server-side. Changing `ADMIN_ACCESS_PASSWORD` and restarting the backend
invalidates previous access. Access-password attempts have their own rate limit.
Keep this value in the backend `.env` only, never in a `VITE_*` variable. The
frontend asks you to type it; it does not contain a copy of the expected secret.

Administrator sessions expire after eight hours and logout revokes them in the
database. Successful login rotates the session. Changing the administrator
credentials or session secret also invalidates previous administrator sessions.
Failed login attempts are limited to five per fifteen-minute window per client
address, shared across backend workers through PostgreSQL. Configure proxy trust
at deployment so the backend receives the intended client address.

Set `FRONTEND_ORIGINS` to a comma-separated list of exact allowed origins. All
mutation requests require both a matching `Origin` and `X-CSRF-Protection: 1`;
the frontend sends the header and includes cookies on normal and streaming
requests. Cookies use `SameSite=Lax`, so deploy the UI and API on the same site
(the same-origin frontend proxy is supported). Production requires HTTPS and
`COOKIE_SECURE=true`. `COOKIE_SECURE=false` is an explicit local HTTP opt-in.

## Conversation creation and streaming

New conversation creates a local draft. The first question goes to `POST
/api/chat` with `{ "conversation_id": null, "message": "..." }`. Before inserting
the conversation, the backend generates a plain title of at most five words and
160 characters. Title generation has an eight-second timeout and a deterministic
question-based fallback. Follow-ups preserve the original title. Title generation
does not invoke retrieval, appear in chat history, or enter the answer stream.

The streaming contract remains `metadata`, `token`, `done`, and `error`.
`metadata` now includes both `conversation_id` and the persisted `title`.
The assistant answer is committed before `done`; stream failures emit a sanitized
`error` and do not save a partial assistant answer as completed.

`POST /api/conversations` remains available for API clients but now requires
`{ "message": "<first question>" }`. It creates a titled, owned conversation
without storing a message or generating an answer. Send the question once to
`POST /api/chat` with the returned ID to start the exchange. Empty requests and
the old title-only payload are rejected. Authentication endpoints are
`POST /api/auth/login`, `POST /api/auth/logout`, and `GET /api/auth/session`.

## Tests

```powershell
cd backend
pytest

cd ..\frontend
npm test
npm run build
```

External models and Pinecone are mocked in tests. To also run API and migration
checks against PostgreSQL, set `TEST_DATABASE_URL` to an isolated test database
before running `pytest`. The tests create and remove their own randomly named
schemas; the database user must have permission to create schemas. They verify
legacy data preservation, migration rollback/idempotency, ownership, and normal
streaming persistence against PostgreSQL.
