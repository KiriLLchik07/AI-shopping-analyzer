# Запуск приложения

Локальные настройки каждого сервиса хранятся отдельно:

```text
backend/.env.backend
infra/postgres.env
infra/minio.env
```

Примеры настроек находятся в соответствующих файлах `*.env.example`. Реальные
env-файлы не добавляются в Git.

**Запуск PostgreSQL, Redis и MinIO в фоне:**

```bash
docker compose up -d --wait
```

**Запуск backend из корня проекта:**

```bash
uv run --project backend uvicorn backend.app.main:app --reload
```

Swagger будет доступен по адресу `http://127.0.0.1:8000/docs`, а консоль MinIO —
по адресу `http://127.0.0.1:9001`.

**Остановка инфраструктуры:**

```bash
docker compose down
```

Если нужно удалить данные вместе с остановкой контейнеров:

```bash
docker compose down -v
```
