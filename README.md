# Lyftr AI

A full-stack, multi-turn AI chatbot built with React, FastAPI, LiteLLM, and SQLite. It includes sequential API-key failover, built-in response caching, per-response token metadata, and an on-demand failure simulation hook.

## 1. Live URLs

The frontend is deployed on Vercel. The backend is prepared for Render with a persistent disk; deployment is pending connection of the Render account and entry of the real provider keys.

| Deliverable | URL / status |
| --- | --- |
| Frontend | Deployed on Vercel: https://vercel.com/anima24/frontend (add the public app URL before submission) |
| Backend | Render Blueprint ready: `render.yaml` (pending Render setup) |
| Public GitHub repository | https://github.com/anima-08/lyft |
| Demo video | Pending recording of the deployed app |

### Deploy the backend on Render

Render is used instead of Vercel because this app stores required conversation history in SQLite. Vercel Functions provide only temporary local storage, while Render can mount a persistent disk at `/data`.

1. In the [Render Dashboard](https://dashboard.render.com), select **New → Blueprint** and connect the `anima-08/lyft` repository on branch `main`.
2. Render detects [`render.yaml`](render.yaml). Review the `lyftr-ai-backend` Docker service, its paid `0.5c-512mb` plan, and its 1 GB disk mounted at `/data`.
3. When prompted, enter:
   - `LLM_API_KEYS`: two or more real provider keys, separated by commas.
   - `ALLOWED_ORIGINS`: the exact public Vercel frontend origin, such as `https://your-app.vercel.app`, with no trailing slash.
4. Apply the Blueprint and wait for the first deploy. The configuration fixes `DATABASE_URL=sqlite:////data/app.db`, enables failure simulation, uses one instance, and checks `/health`.
5. After the service is live, copy its public `https://…onrender.com` URL. In the Vercel frontend project, set `VITE_API_BASE_URL` to that URL for Production and redeploy the frontend.
6. Open `<backend-url>/health` and confirm it returns `status: "ok"`, then test chat, cache hits, failover, and history through the Vercel app.

The Render disk is paid and limited to one service instance. Render briefly stops the old instance during a disk-backed redeploy to protect SQLite from simultaneous writers. Never put real keys in Git or send them in chat; enter them only in Render's environment settings.

No real keys, `.env` files, or credentials belong in the repository.

## 2. Run locally: with Docker and without

### With Docker

Requirements: Docker with Compose v2.24+ and Make.

1. Copy the example environment file and replace both placeholder keys with real keys for the configured provider:

   ```bash
   cp .env.example .env
   ```

2. Start both services:

   ```bash
   make up
   ```

3. Open:

   - Frontend: http://localhost:3000
   - Backend: http://localhost:8000/health

4. Stop the services with `make down`. The named `sqlite_data` volume retains `/data/app.db` across container restarts. `make down` does not delete that volume.

The frontend production image serves the Vite build through Nginx. Both Dockerfiles use multi-stage builds; the backend runtime uses a Python virtual environment and a non-root user, and the frontend runtime contains only Nginx and static assets.

### Without Docker

Requirements: Python 3.12+, Node.js 22+, and npm.

Backend:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
export LLM_API_KEYS="real-key-1,real-key-2"
export DATABASE_URL="sqlite:///./app.db"
export ALLOWED_ORIGINS="http://localhost:3000"
export ENABLE_FAILURE_SIMULATION=true
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

On Windows, activate the environment with `.venv\Scripts\activate` and set variables in PowerShell instead of using `export`.

Frontend, in a second terminal:

```bash
cd frontend
npm ci
export VITE_API_BASE_URL="http://localhost:8000"
npm run dev
```

### Configuration

All configuration is environment-driven. `.env.example` lists every supported variable.

| Variable | Purpose |
| --- | --- |
| `LLM_API_KEYS` | Comma-separated provider keys; IDs are assigned as `key_1`, `key_2`, etc. At least two are required. |
| `LLM_MODEL` | LiteLLM model name; defaults to `gemini/gemini-2.5-flash`. |
| `DATABASE_URL` | SQLite URL. Docker forces `sqlite:////data/app.db`. |
| `ALLOWED_ORIGINS` | Comma-separated frontend origins allowed by CORS. |
| `ENABLE_FAILURE_SIMULATION` | Enables `X-Simulate-Failure`; must be `true` on the deployed backend. |
| `DEFAULT_SYSTEM_PROMPT` | Default instructions prepended to every model request. |
| `CACHE_TTL_SECONDS` | In-memory cache lifetime; defaults to one hour. |
| `REQUEST_TIMEOUT_SECONDS` | Per-provider request timeout. |
| `MAX_OUTPUT_TOKENS` | Maximum completion tokens. |
| `TEMPERATURE` | Sampling temperature. |
| `VITE_API_BASE_URL` | Backend base URL embedded in the frontend build. |
| `BACKEND_PORT` / `FRONTEND_PORT` | Optional Docker host-port overrides. |

## 3. Design decisions: key fallback, caching, SQLite session storage

### Key fallback

The gateway calls `litellm.completion` sequentially with one key at a time. A rate limit, quota error, timeout, connection failure, 5xx response, or invalid/empty provider response advances to the next key. The API key itself is never returned or logged. If every key fails, the endpoint returns `503 {"detail":"all providers unavailable"}` and no messages are written.

`X-Simulate-Failure` is parsed per request and honored only when enabled. It supports `key_1=429`, `key_1=429,key_2=500`, and `*=429`, using only the statuses in the assignment. Simulation does not alter global state.

### Caching

LiteLLM's built-in in-memory cache is enabled globally. Its key is based on the model and complete ordered message list: system prompt, stored conversation history, and the new user message. It intentionally excludes the API key and session ID, so an identical first prompt in a new session can hit the same cached response while a different prompt cannot.

A cache-hit signal from LiteLLM sets `resolution_source` to `LLM_CACHE`, preserves the original reply and token usage, and reports `key_id: null` and `fallback_attempts: 0`. A newly generated response reports `LIVE_INFERENCE` and the successful key ID. The cache is process-local; required conversation history remains persistent in the SQLite volume.

### SQLite session storage

SQLite is the only application datastore. The schema is created automatically and includes `sessions` plus indexed `messages` tables. A successful user/assistant exchange is committed in one transaction; validation and provider failures never create a session or append history. The history endpoint returns messages oldest-first and excludes the system prompt.

The optional system prompt is stored per session. If omitted later, the session's previous prompt is reused. A per-session striped lock prevents concurrent requests for the same session from building context from a partially committed exchange, while allowing unrelated sessions to proceed independently. WAL mode and a busy timeout improve SQLite concurrency.

## 4. Verification: how to see failover, cache hits and per-message token usage

These examples assume the backend runs locally and two keys are configured.

### Health and live inference

```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"s-demo-1","message":"What is the capital of France?"}'
```

The response contains `LIVE_INFERENCE`, the LiteLLM model name, integer latency, per-request input/output tokens, `key_id`, and `fallback_attempts`. The UI displays these values beside that reply only; it does not show conversation totals.

### Cache hit

Send the same first message in another new session:

```bash
curl -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"s-demo-2","message":"What is the capital of France?"}'
```

The second response should report `LLM_CACHE`, identical reply text and token usage, `key_id: null`, and lower latency. Changing the message or system prompt produces a different cache key.

### Failover and total failure

```bash
curl -i -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -H 'X-Simulate-Failure: key_1=429' \
  -d '{"session_id":"s-demo-3","message":"Give me a one-sentence resilience tip."}'

curl -i -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -H 'X-Simulate-Failure: *=429' \
  -d '{"session_id":"s-demo-4","message":"This must not be stored."}'
```

The first returns a real answer with `key_id: "key_2"` and `fallback_attempts: 1`. The second returns 503. The failed session remains unknown:

```bash
curl -i http://localhost:8000/sessions/s-demo-4/messages
```

### Multi-turn history

```bash
curl -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"s-demo-1","message":"What is its population?"}'

curl http://localhost:8000/sessions/s-demo-1/messages
```

The second model request includes the earlier exchange from SQLite even though the client sends only the new message.

### Automated tests

```bash
make test
```

Or run `cd backend && python -m pytest` and `cd frontend && npm test` separately. Tests cover the exact API/UI contracts, validation, history isolation, system-prompt persistence, cache metadata, failover, total failure without history writes, CORS, and malformed simulation headers.

## 5. Setup Used: your editor and AI tools

- Editor and development environment: Qoder Desktop.
- AI assistance: Qoder coding assistant for implementation, test authoring, and specification verification.
- Backend tooling: Python 3.12, FastAPI, LiteLLM, SQLite, pytest, Ruff, and Uvicorn.
- Frontend tooling: Node.js, React, Vite, Vitest, React Testing Library, and Nginx.

## 6. Bonus features (if any): what you added beyond the requirements and why

- Optional per-session system prompt with persistence, so follow-up requests retain custom instructions.
- Session-ID copy control and responsive desktop/mobile layouts.
- Visible request states, keyboard controls, accessible errors, and reduced-motion support.
- Bounded, TTL-controlled LiteLLM in-memory caching with no external datastore.
- Automated backend and frontend contract tests, plus strict structured JSON error handling.
