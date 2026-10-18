# syntax=docker/dockerfile:1
# The API reads its data from a Cloud Run bucket mount; no dataset is baked into the image.
FROM python:3.12.10-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /uvx /bin/
WORKDIR /app
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /app/.venv --python /usr/local/bin/python && \
    uv sync --locked --no-dev --no-install-project

FROM python:3.12.10-slim-bookworm
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src \
    DATA_DIR=/mnt/tank/export TH_MARKUP=1.0 PORT=8080 PATH=/app/.venv/bin:$PATH
COPY --from=builder /app/.venv ./.venv
COPY pyproject.toml ./
COPY src ./src
COPY api ./api
RUN useradd --system --uid 10001 --no-create-home appuser
USER 10001
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn api.app:app --host 0.0.0.0 --port ${PORT}"]
