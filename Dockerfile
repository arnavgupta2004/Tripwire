# Tripwire public demo: the FastAPI backend serving the built frontend.
# No secrets are baked in; NEBIUS_API_KEY and friends come from the host's secret store.

FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ backend/
COPY config/ config/
COPY demo/private/ demo/private/
COPY demo/injection/ demo/injection/
COPY --from=frontend /app/frontend/dist frontend/dist

RUN useradd --create-home tripwire && mkdir -p /app/data && chown tripwire /app/data
USER tripwire
ENV PATH=/opt/venv/bin:$PATH PYTHONPATH=/app/backend PYTHONUNBUFFERED=1 \
    PUBLIC_DEMO=true DATA_DIR=/app/data PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/healthz', timeout=4)"
CMD ["sh", "-c", "exec uvicorn api.serve:build --factory --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
