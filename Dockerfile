FROM node:24-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend/ ./
COPY --from=frontend /frontend/dist /app/static
ENV PATH="/app/.venv/bin:$PATH" \
    FRONTEND_DIST=/app/static
# sh -c so ${PORT} expands (Railway injects it); && means the app starts only if seeding succeeded
CMD ["sh", "-c", "python -m app.seed && fastapi run app/main.py --port ${PORT:-8000}"]
