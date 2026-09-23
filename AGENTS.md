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
