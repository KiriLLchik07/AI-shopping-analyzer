@a_default:
    just --list

@lint:
    uv run --project backend ruff check . --fix

@format: 
    uv run --project backend ruff format .

@start:
    docker compose up -d
