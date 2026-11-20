FROM node:24-bookworm-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.8.19 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project \
    && mkdir -p /app/data && chown 10001:10001 /app/data
COPY scopebrief/ scopebrief/
COPY --from=frontend /app/frontend/dist frontend/dist/

ENV PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
EXPOSE 8000
VOLUME ["/app/data"]
HEALTHCHECK --interval=30s --timeout=3s CMD ["/app/.venv/bin/python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/api/health', timeout=2).close()"]
CMD ["/app/.venv/bin/uvicorn", "scopebrief.app:app", "--host", "0.0.0.0", "--port", "8000"]
