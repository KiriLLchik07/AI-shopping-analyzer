@a_default:
    just --list

@lint:
    uv run --project backend ruff check . --fix

@format: 
    uv run --project backend ruff format .

@start:
    docker compose up -d

@backend:
    uv run --project backend uvicorn backend.app.main:app --reload

[working-directory: 'backend']
@migration_revision message:
    uv run alembic revision -m "{{message}}"

[working-directory: 'backend']
@migration_upgrade:
    uv run alembic upgrade head
