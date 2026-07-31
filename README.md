# Запуск приложения

**Запуск всех сервисов в фоне с указанным env файлом:**

```bash
docker compose --env-file .имя_env_файла up -d --wait
```

**Остановка приложения:**

```bash
docker compose --env-file .имя_env_файла down
```

Если нужно удалить данные вместе с остановкой контейнеров:

```bash
docker compose --env-file .имя_env_файла down -v
```
