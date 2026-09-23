# Bootstrap: hackathon skeleton (Kazakhtelecom track)

You are building the foundation of a hackathon project. The case is not published yet, so build a
case-agnostic skeleton that will be extended once the case is known. Work in the phases below.
After each phase, run its checks, report the results, and STOP. Do not start the next phase until
I reply "continue".

## Global rules

- Never run `git commit`, `git push`, or any destructive git command. I commit after verifying each phase.
- Use current stable versions of everything. If unsure of a library's API or a CLI's flags, read the
  installed package source or the command's `--help` output. Do not guess.
- Fail fast: missing configuration raises at startup. No silent fallbacks, no swallowed exceptions.
- Keep it simple: no auth, no React Router, no Redux, no extra services or abstractions.
- Commands that need network access (`uv add`, `npm install`, `npx`) must be requested for approval, not skipped.

## Target layout

```
.
├── AGENTS.md
├── CLAUDE.md
├── README.md
├── compose.yaml
├── Dockerfile
├── .dockerignore
├── .gitignore
├── docs/
│   ├── bootstrap.md        (this file)
│   ├── case.md
│   └── plan.md
├── backend/
│   ├── pyproject.toml, uv.lock, .python-version
│   ├── .env.example
│   ├── alembic.ini
│   ├── migrations/
│   └── app/
│       ├── __init__.py
│       ├── config.py
│       ├── db.py
│       ├── models.py
│       ├── llm.py
│       ├── agent.py
│       ├── seed.py
│       └── main.py
└── frontend/
    ├── vite.config.ts
    └── src/
        ├── api/
        │   ├── schema.d.ts   (generated)
        │   └── client.ts
        ├── index.css
        ├── App.tsx
        └── main.tsx
```

---

## Phase 1: Repo foundation

1. Create `AGENTS.md` with exactly this content:

```markdown
# Kazakhtelecom track — hackathon project

## Context
- Case, rubric, mentor answers, data description: docs/case.md
- Demo script, models, endpoints, agent tools: docs/plan.md
- Read both before every task. Nothing outside the demo script gets built.

## Roles
- Codex: writes and edits all code in backend/ and frontend/, runs the check commands.
- Chat assistant (Claude/ChatGPT): idea generation, drafts of docs/plan.md, pitch text. Never edits the repo.
- Humans: pick the idea, approve the schema, review every migration, verify each task, make all git commits.

## Stack
- backend/: Python, FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy 2.0 async + asyncpg, Alembic,
  PostgreSQL 18, OpenAI Python SDK (Responses API). Package manager: uv.
- frontend/: React + TypeScript + Vite, Tailwind CSS v4, shadcn/ui, TanStack Query, openapi-fetch.
  Single page, no router.
- All API routes live under /api. Frontend API types come from frontend/src/api/schema.d.ts,
  generated from FastAPI's OpenAPI schema.
- Production: one Docker image; FastAPI serves the built frontend. Deployed on Railway with managed Postgres.

## Commands
- Database: `docker compose up -d` (repo root)
- Backend dev: `cd backend && uv run fastapi dev app/main.py`
- Backend check: `cd backend && uv run ruff check . && uv run pyright`
- New migration: `cd backend && uv run alembic revision --autogenerate -m "<msg>"`
- Apply migrations: `cd backend && uv run alembic upgrade head`
- Frontend dev: `cd frontend && npm run dev` (proxies /api to 127.0.0.1:8000)
- Regenerate API types (backend must be running): `cd frontend && npm run gen:api`
- Frontend check: `cd frontend && npm run build`

## Rules
- Do only the task asked. No refactors, no edits to unrelated files.
- Every endpoint has Pydantic request/response models and a return type annotation.
- All config comes from app/config.py; secrets and the model name come from env vars, never hardcoded.
- Never edit frontend/src/api/schema.d.ts by hand; run gen:api.
- Never create, edit or apply Alembic migrations unless the task explicitly says so.
  When you create one, show its upgrade() and stop for review before applying it.
- Raise errors; never silently return empty data or swallow exceptions.
- If unsure of a library signature, read the installed package source or --help instead of guessing.
- After changes, run the relevant check command and report the result.
- Never run git commit or git push.
```

2. Create `CLAUDE.md` containing only this line (Claude Code imports AGENTS.md through it):

```
@AGENTS.md
```

3. Create `docs/case.md`:

```markdown
# Case
<paste the full case text>

# Judging rubric
<paste the criteria and weights>

# Mentor answers
- End user:
- Success metric:
- Can case data be sent to the OpenAI API:
- Language requirement (kk / ru / en):
- What they already tried:

# Data
- Files:
- Columns:
- Sample rows (5):
```

4. Create `docs/plan.md`:

```markdown
# One-line pitch

# Demo script (max 5 steps — what the jury sees at each step)

# Models (tables, columns, types, relations — only what the demo needs)

# Endpoints (method, path, request fields, response fields)

# Agent tools (name, typed arguments, what it returns)

# Real vs mocked
```

5. Create `.gitignore`:

```
.env
.venv/
node_modules/
frontend/dist/
__pycache__/
*.pyc
```

6. Create `compose.yaml`:

```yaml
services:
  db:
    image: postgres:18
    environment:
      POSTGRES_USER: app
      POSTGRES_PASSWORD: app
      POSTGRES_DB: app
    ports:
      - "5433:5432"  # host 5433 avoids clashing with a locally installed Postgres on 5432
    volumes:
      - pgdata:/var/lib/postgresql  # Postgres 18+ mount path; the old /var/lib/postgresql/data breaks
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d app"]
      interval: 2s
      timeout: 3s
      retries: 15

volumes:
  pgdata:
```

**Checks:** `docker compose up -d`, then `docker compose ps` shows `db` as healthy.
**STOP.**

---

## Phase 2: Backend

### Setup

- Run `uv init backend`, then delete the sample `main.py` and `README.md` that uv generates inside `backend/`.
- In `backend/`: `uv add "fastapi[standard]" "sqlalchemy[asyncio]" asyncpg alembic pydantic-settings openai`
- In `backend/`: `uv add --dev ruff pyright`
- Create `backend/.env.example`:

```
DATABASE_URL=postgresql://app:app@127.0.0.1:5433/app
OPENAI_API_KEY=
OPENAI_MODEL=
```

### Files

**`app/__init__.py`**: empty.

**`app/config.py`**
- `Settings(BaseSettings)` with `model_config = SettingsConfigDict(env_file=".env", extra="ignore")`.
- Fields: `database_url: str`, `openai_api_key: str`, `openai_model: str`, `frontend_dist: str | None = None`.
- Module-level `settings = Settings()` so missing variables fail at import time.

**`app/db.py`**
- `DATABASE_URL = make_url(settings.database_url).set(drivername="postgresql+asyncpg")`.
  Railway provides plain `postgresql://`; this forces the async driver.
- `engine = create_async_engine(DATABASE_URL)`, `SessionLocal = async_sessionmaker(engine, expire_on_commit=False)`.
- `class Base(DeclarativeBase)`.
- `async def get_session()` dependency that yields a session.
- `SessionDep = Annotated[AsyncSession, Depends(get_session)]`.

**`app/models.py`**
- One table, `AgentRun` (`agent_runs`): `id` int primary key, `user_input` Text, `answer` Text,
  `steps` JSONB (list of step objects), `created_at` timestamptz with `server_default=func.now()`.
- Use SQLAlchemy 2.0 typed `Mapped[...]` / `mapped_column` style.

**Alembic**
- In `backend/`: `uv run alembic init -t async migrations` (async template: env.py runs migrations
  through an async engine).
- In `migrations/env.py`, directly after `config = context.config`:
  - Import `DATABASE_URL` and `Base` from `app.db`, and `import app.models` so every table registers.
  - `config.set_main_option("sqlalchemy.url", DATABASE_URL.render_as_string(hide_password=False).replace("%", "%%"))`.
    The `%%` escape is required: alembic.ini is parsed by configparser, which treats `%` as interpolation.
  - Replace `target_metadata = None` with `target_metadata = Base.metadata`.

**`app/llm.py`**
- `client = AsyncOpenAI(api_key=settings.openai_api_key)`. Pass the key explicitly: pydantic-settings
  reads `.env` but does not export it to `os.environ`, so the SDK would not find it on its own.
- `async def structured[T: BaseModel](*, instructions: str, input: str, schema: type[T]) -> T`:
  calls the Responses API parse method with `text_format=schema` and `model=settings.openai_model`,
  returns `output_parsed`, and raises if it is `None`.

**`app/agent.py`**: a small, generic tool-calling loop (the "harness" of our product agent)
- A `Tool` dataclass: `name`, `description`, `args_model: type[BaseModel]`,
  `handler: async (session, args) -> dict`.
- Pydantic models: `AgentStep` (`tool: str`, `arguments: dict`, `result: dict`) and `AgentAnswer` (`answer: str`).
- `async def run_agent(session, message: str, tools: list[Tool], max_steps: int = 8) -> tuple[AgentAnswer, list[AgentStep]]`:
  - Uses Responses API function calling. Build each tool's JSON schema from `args_model` in strict mode.
    If the installed SDK provides a helper that converts a Pydantic model into a strict function schema,
    use it rather than hand-rolling the conversion.
  - Loop: call the model, execute every function call it requests, append each result as a function call
    output tied to its call id, and repeat until the model returns a final message.
  - The final message is parsed into `AgentAnswer` via structured output. Verify in the installed SDK
    source that the parse method accepts `tools` together with `text_format`.
  - Record every executed call as an `AgentStep`.
  - Raise `AgentStepLimitError` when `max_steps` is exceeded, and `ValueError` on an unknown tool name.
- `TOOLS` registry with one demo tool, `count_agent_runs` (no arguments), that returns
  `{"count": <rows in agent_runs>}`. It proves the tool → DB path and will be replaced by case-specific tools.

**`app/seed.py`**
- Runnable as `python -m app.seed`. Must be idempotent: skip loading if data already exists.
- For now, log `No seed data configured` and exit 0. Keep a clear `async def main()` entry point so it can
  later load files from `backend/data/`.

**`app/main.py`**
- `api = APIRouter(prefix="/api")`.
- `GET /api/health` → `HealthOut(status="ok", database="ok")` after executing `SELECT 1` through the session.
  A DB failure must propagate as an error, never be reported as ok.
- `POST /api/agent/run`, body `AgentRunIn(message: str, min_length=1)` → `AgentRunOut(id, answer, steps, created_at)`.
  Runs `run_agent` with `TOOLS`, persists an `AgentRun`, commits, and refreshes the row after commit so
  `created_at` is loaded.
- `app = FastAPI()`, then `app.include_router(api)`.
- Only if `settings.frontend_dist` is set: after the router,
  `app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="spa")`.
  `StaticFiles` raises at startup if the directory is missing, which is intended.

### Checks, part A

1. `uv run ruff check . && uv run pyright` passes.
2. `uv run alembic revision --autogenerate -m "create agent_runs"`.
3. Print the generated `upgrade()` function.
4. Copy `.env.example` to `.env`.

**STOP.** Ask me to review the migration and to fill in `OPENAI_API_KEY` and `OPENAI_MODEL` in `backend/.env`.

### Checks, part B (after I reply "continue")

1. `uv run alembic upgrade head`.
2. Start `uv run fastapi dev app/main.py` in the background.
3. `curl -s http://127.0.0.1:8000/api/health` returns ok for both fields.
4. The following returns an answer whose steps include `count_agent_runs`:
   `curl -s -X POST http://127.0.0.1:8000/api/agent/run -H 'Content-Type: application/json' -d '{"message":"How many agent runs are stored?"}'`
5. Report both outputs. Leave the backend running for phase 3.

**STOP.**

---

## Phase 3: Frontend

### Setup

- Scaffold `frontend/` with `npm create vite@latest frontend -- --template react-ts`, run non-interactively
  (check `npm create vite@latest -- --help` for the flag).
- `npm install @tanstack/react-query openapi-fetch tailwindcss @tailwindcss/vite`
- `npm install -D openapi-typescript`
- Tailwind v4: add the `@tailwindcss/vite` plugin; replace `src/index.css` with `@import "tailwindcss";`.
- shadcn/ui: follow its current Vite installation steps. That includes the `@/` path alias in
  `tsconfig.json`, `tsconfig.app.json` and `vite.config.ts`, plus `@types/node`. Run `npx shadcn@latest init`
  non-interactively (check `--help`), then add these components: button, card, textarea, badge.
- Delete the Vite template's demo content: `App.css`, template assets, counter demo.

### Files

**`vite.config.ts`**: plugins `react()` and `tailwindcss()`, the `@` alias, and
`server.proxy: { "/api": "http://127.0.0.1:8000" }`. Add a comment explaining 127.0.0.1: Node may resolve
`localhost` to IPv6 `::1`, but uvicorn binds IPv4 only.

**`package.json` script**:
`"gen:api": "openapi-typescript http://127.0.0.1:8000/openapi.json -o src/api/schema.d.ts"`

**`src/api/client.ts`**: `export const api = createClient<paths>({ baseUrl: "" });` with `paths` imported
from `./schema`. The relative base URL means the Vite proxy handles calls in dev and the same origin
handles them in prod.

**`src/main.tsx`**: wrap `<App />` in `QueryClientProvider` inside `StrictMode`.

**`src/App.tsx`**: a single page, no router.
- Header: product name placeholder, plus a backend status badge from `useQuery` on `GET /api/health`
  (connected / unreachable).
- A textarea labelled "What should the agent do?" and a button "Run agent" (`useMutation` on
  `POST /api/agent/run`). While pending, the button reads "Running…" and is disabled.
- Result area:
  - the answer text;
  - a "Steps" section listing every tool call in order, showing tool name, arguments and result
    (formatted JSON in a scrollable block).
- openapi-fetch returns errors instead of throwing. Inside every `queryFn`/`mutationFn`, throw when `error`
  is present so TanStack Query enters its error state. Error messages must say what failed and what to check.
- Design: a restrained internal-tool look. One typeface, neutral palette, clear hierarchy. The step log
  is the one visually prominent element, because it shows judges the agent working. Sentence case, active-voice
  button labels, no landing page, no decorative gradients. Responsive down to mobile, visible keyboard focus.

### Checks

1. With the backend running: `npm run gen:api` produces `src/api/schema.d.ts`.
2. `npm run build` passes with no type errors.
3. Start `npm run dev`.

**STOP.** Ask me to test the page at http://localhost:5173: run the agent and confirm the answer and steps render.

---

## Phase 4: Production build and README

**`Dockerfile`** (repo root, multi-stage):
- Stage `frontend`, from `node:24-alpine`:
  - copy `frontend/package.json` and `frontend/package-lock.json`;
  - `npm ci`;
  - copy `frontend/`;
  - `npm run build`.
- Runtime stage, from `python:<X.Y>-slim` where X.Y matches `backend/.python-version`:
  - copy `/uv` from `ghcr.io/astral-sh/uv:latest` to `/bin/uv`;
  - set `WORKDIR /app`;
  - copy `backend/pyproject.toml` and `backend/uv.lock`, then run `uv sync --locked --no-dev --no-install-project`;
  - copy `backend/`, then copy the frontend stage's `dist` to `/app/static`;
  - `ENV PATH="/app/.venv/bin:$PATH" FRONTEND_DIST=/app/static`;
  - `CMD ["sh", "-c", "python -m app.seed && fastapi run app/main.py --port ${PORT:-8000}"]`.
    `sh -c` is needed so `${PORT}` expands (Railway injects PORT). `&&` means the app starts only if seeding succeeded.

**`.dockerignore`**:

```
**/node_modules
**/.venv
**/.env
frontend/dist
```

**`README.md`** sections:
- **Project**: one-line placeholder.
- **Run locally**: the commands from AGENTS.md, in order.
- **Deploy (Railway)**, as manual steps:
  1. Push the repo to GitHub.
  2. Railway → New Project → Deploy from GitHub repo. Connect GitHub for the Full Trial.
  3. Add PostgreSQL to the project.
  4. App service → Variables: `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `OPENAI_API_KEY`, `OPENAI_MODEL`.
  5. Settings → Deploy → Pre-deploy command: `alembic upgrade head`.
  6. Settings → Networking → Generate Domain.
  7. Verify: open `<domain>/api/health`.
- **How we used AI**:
  - Codex wrote all application code, driven by AGENTS.md and docs/plan.md.
  - A chat assistant handled idea scoring, plan drafts and pitch text.
  - Humans did problem framing, schema design, migration review, verification of every feature,
    and eval labeling.

### Checks

1. `docker build -t hackathon-app .` succeeds.
2. `docker run --rm --network host --env-file backend/.env hackathon-app`.
   `--network host` lets the container reach the compose DB on 127.0.0.1:5433 (Linux).
3. `curl -s http://127.0.0.1:8000/api/health` returns ok, and `curl -s http://127.0.0.1:8000/` returns the
   built index.html.
4. Stop the container.

**STOP.** Summarize what was built and list the remaining manual Railway steps.
