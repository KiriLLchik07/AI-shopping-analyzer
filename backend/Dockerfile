FROM python:3.12-slim

WORKDIR /backend

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /bin/

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic

ENV PATH="/backend/.venv/bin:$PATH"

WORKDIR /

EXPOSE 8000

CMD ["sh", "-c", "uv run python -m alembic -c /backend/alembic.ini upgrade head && exec uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000"]
