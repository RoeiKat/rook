# Rook

Rook is a React and FastAPI chat application. Conversations and messages live in
PostgreSQL, answers stream from a LangChain agent, and optional document search
uses Pinecone.

## Development with Docker

Copy the example environment files, configure `backend/.env`, then start the
application. By default Compose starts only the application services; it uses the
database and document-storage URLs from `backend/.env`:

```powershell
Copy-Item backend/.env.example backend/.env
Copy-Item frontend/.env.example frontend/.env
docker compose up --build
```

The bundled PostgreSQL 16 container remains available as an opt-in fallback. Set
`DATABASE_URL` to `postgresql+asyncpg://rook:rook@postgres:5432/rook`, remove any
pooled URL override, select local document storage if desired, then run:

```powershell
docker compose --profile local-db up --build
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

- `OLLAMA_BASE_URL` is required and points at the self-hosted Ollama-compatible
  inference service. There is no localhost fallback in application code.
- `PINECONE_API_KEY`, `PINECONE_INDEX`, and `PINECONE_NAMESPACE` configure RAG.
- `DATABASE_URL_POOLED` selects the normal application connection when supplied;
  `DATABASE_URL_UNPOOLED` selects the direct migration connection. `DATABASE_URL`
  remains the fallback for both.
- `DOCUMENT_STORAGE_PROVIDER` selects `local` or `s3` storage.
- `AWS_ENDPOINT_URL_S3`, `AWS_REGION`, `AWS_ACCESS_KEY_ID`,
  `AWS_SECRET_ACCESS_KEY`, and `S3_BUCKET` configure Neon Object Storage.
- `DOCUMENT_STORAGE_LOCAL_PATH` configures the optional local fallback, and
  `DOCUMENT_UPLOAD_MAX_BYTES` sets the upload limit. The default is 4 MiB so a
  multipart upload remains below Vercel's 4.5 MB Function request limit.
- `ADMIN_USERNAME` and `ADMIN_PASSWORD_HASH` enable the administrator login.
- `ADMIN_LOGIN_MAX_ATTEMPTS` and `ADMIN_LOGIN_WINDOW_SECONDS` limit failed
  administrator logins per source address. The defaults are 5 attempts per 15 minutes.
- `FRONTEND_ORIGINS` lists browser origins allowed to call the API.
- `MIGRATE_ON_STARTUP` controls the compatibility startup migration. Leave it
  enabled for the first deployment; later releases can run
  `python -m app.database.migrate` explicitly and disable it.

Frontend settings are documented separately in `frontend/.env.example`:

- `VITE_API_URL` is the public API URL used by the browser. Leave it empty when
  using the included Vite proxy.
- `VITE_ADMIN_PATH` selects the unadvertised administrator page path. Use a long,
  random path beginning with `/`; authentication and rate limiting remain the
  actual security boundaries because frontend values are visible in browser code.
- `API_PROXY_TARGET` is the backend target used only by the Vite development
  server. Docker Compose sets it to `http://backend:8000` automatically.

Only variables prefixed with `VITE_` are included in browser code. Never put
passwords, API keys, or session secrets in the frontend environment file.

When `VITE_API_URL` is empty, requests such as `/api/auth/session` go to the same
origin as the frontend. During development Vite forwards `/api` to
`API_PROXY_TARGET`; the production Nginx image also forwards `/api` to the backend.
Set `VITE_API_URL` only when the browser must call a separately hosted public API.

## Deploy to Vercel

Import this repository twice from the Vercel dashboard. Use `backend` as the
root directory for the FastAPI project and `frontend` as the root directory for
the Vite project.

Deploy the backend first. Vercel detects `backend/app/main.py` as the FastAPI
entry point, while `backend/vercel.json` enables Fluid compute and gives the
streaming function the Hobby-plan maximum duration. Configure these backend
environment variables in Vercel:

- `APP_ENV=production`
- `DATABASE_URL_POOLED` with the Neon pooled connection string
- `DATABASE_URL_UNPOOLED` with the Neon direct connection string
- `SESSION_SECRET` with at least 32 random characters
- `FRONTEND_ORIGINS` with the exact public frontend origin
- `OLLAMA_BASE_URL` with the reachable self-hosted inference origin
- `PINECONE_API_KEY`, `PINECONE_INDEX`, and `PINECONE_NAMESPACE`
- `DOCUMENT_STORAGE_PROVIDER=s3`, `S3_BUCKET`, `AWS_ENDPOINT_URL_S3`,
  `AWS_REGION`, `AWS_ACCESS_KEY_ID`, and `AWS_SECRET_ACCESS_KEY`
- the optional administrator settings described below

Production rejects local document storage because a Vercel Function's local
filesystem is not persistent. Use the pooled database URL for request traffic
and the direct URL for migrations.

For the first backend deployment, leave `MIGRATE_ON_STARTUP` enabled so the
existing transactional, advisory-locked migration initializes the database.
For later releases, run the migration separately with production environment
variables and then set `MIGRATE_ON_STARTUP=false`:

```powershell
cd backend
python -m app.database.migrate
```

For the frontend project, set `API_PROXY_TARGET` to the backend's public origin,
for example `https://rook-api.example.vercel.app`, and leave `VITE_API_URL`
empty. `frontend/vercel.mjs` proxies `/api` and `/health` to that backend so the
current HttpOnly session cookies remain same-origin in the browser. It also
provides the SPA fallback required for direct visits to the administrator path.

Environment-variable changes apply only to new Vercel deployments, so redeploy
after changing either project's configuration.

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

The public chat needs no account. The path configured by `VITE_ADMIN_PATH` uses one
username and password to list all conversations. Generate a password hash from
`backend/`:

```powershell
python -m app.auth
```

Put the username and generated hash in `backend/.env`. Wrap the hash in single
quotes because it contains dollar signs:

```env
ADMIN_USERNAME=roei
ADMIN_PASSWORD_HASH='<generated hash>'
ADMIN_LOGIN_MAX_ATTEMPTS=5
ADMIN_LOGIN_WINDOW_SECONDS=900
```

The browser receives one admin cookie after login. Logout deletes its matching
server-side session and clears the cookie. Failed login records are stored as
one-way source-address hashes in PostgreSQL and expire from the active window
automatically.

## Document ingestion

Administrators can open the configured `VITE_ADMIN_PATH`, select **Knowledge base**, and upload `.txt`,
`.md`, or `.pdf` documents. With `DOCUMENT_STORAGE_PROVIDER=s3`, originals are
stored in the configured private Neon bucket while PostgreSQL remains the inventory
and synchronization source of truth. Local storage remains available for offline
development; files placed there manually are discovered on the next inventory or
ingestion request.

The **Ingest changes** action replaces each changed document's Pinecone vectors by
stable document ID before upserting deterministic chunk IDs. Failed runs stay dirty
and can be retried. Deletion removes vectors first, then the original object, then
the database record; every step is safe to retry.

The protected **Rebuild Pinecone** action is the recovery path after a database
volume reset or legacy ingestion. After confirmation, it clears only Rook's
configured Pinecone namespace and re-ingests every managed document. A
rebuild with no managed documents leaves that namespace empty.

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

For a production image, pass public frontend settings at build time because Vite
embeds them into the static bundle:

```powershell
docker build --target production `
  --build-arg VITE_ADMIN_PATH=/your-random-administrator-path `
  --build-arg VITE_API_URL=https://api.example.com `
  -t rook-frontend ./frontend
```
