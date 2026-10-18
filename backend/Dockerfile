FROM python:3.12-slim-bookworm AS source

WORKDIR /backend

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /bin/

COPY pyproject.toml uv.lock ./

COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic

ENV PATH="/backend/.venv/bin:$PATH"

WORKDIR /

FROM source AS worker-cpu

RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 && rm -rf /var/lib/apt/lists/*
RUN --mount=type=cache,target=/root/.cache/uv uv sync --project /backend --locked --no-dev --no-install-project --extra ocr-cpu

ENV IMAGE_ORIENTATION_DEVICE=cpu
ENV IMAGE_ORIENTATION_MODEL_DIR=/models/doc-orientation
ENV PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True

CMD ["python", "-m", "backend.app.workers.worker"]

FROM source AS api

RUN --mount=type=cache,target=/root/.cache/uv uv sync --project /backend --locked --no-dev --no-install-project

EXPOSE 8000

CMD ["sh", "-c", "python -m alembic -c /backend/alembic.ini upgrade head && exec uvicorn backend.app.main:app --host 0.0.0.0 --port 8000"]
