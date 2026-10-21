# Frontend

React + TypeScript + Vite. Node.js 22.12+.

```powershell
cd frontend
npm ci
Copy-Item .env.example .env.local
npm run dev
```

Открыть http://localhost:5173. Backend должен быть доступен по http://localhost:8000.
Используйте один hostname для обоих приложений: `localhost`, а не смесь `localhost` и `127.0.0.1`.

## Настройки

- `VITE_API_BASE_URL` в `.env.local` — origin backend без пути. По умолчанию `http://localhost:8000`.
- `CORS_ALLOW_ORIGINS` в окружении backend — JSON-массив точных origins, например `["http://localhost:5173"]`.
- Порт Vite фиксирован: 5173. Если он занят, запуск завершится ошибкой.
- Переменные `VITE_*` доступны браузеру. При изменении адреса API перезапустите Vite; для production пересоберите приложение.

## Запросы

```typescript
import { apiRequest } from './api/client'

const user = await apiRequest<{ user_id: string }>('/api/auth/me')
```

Клиент всегда использует `credentials: 'include'`. Для JSON-запросов передавайте
`Content-Type: application/json` и `JSON.stringify(...)` в `body`.
Для загрузки передавайте `FormData`: браузер сам установит `Content-Type` с boundary.

## Проверки

```powershell
npm test
npm run typecheck
npm run build
npm run format:check
```

`npm run preview` показывает собранное приложение на http://localhost:5173.

## Страницы

- `/login`: вход и регистрация. Сессия восстанавливается через `/api/auth/me`.
- `/upload`: выбор фото, preview и загрузка. JPEG, PNG, WebP до 10 МБ.
- `/receipts`: список чеков с поиском, фильтром статуса и пагинацией.
- `/receipts/:id`: фото, статусы, данные чека, товары и подтверждение.
- `/analytics`: период, категории, динамика, товары, магазины и сравнение месяцев.
- `/reports`: создание отчёта и история; `/reports/:id`: сохранённый отчёт.

Даты покупки отображаются и редактируются по времени Омска (`Asia/Omsk`).
Правки снимают подтверждение чека; после сохранения подтвердите его снова.
Суммы отправляются строками. Проверка арифметики при подтверждении выполняется backend.
Тема следует системной настройке. Сессия и данные чеков не сохраняются в localStorage.

## Браузерные regression-тесты

Из корня репозитория, при установленном `uv`:

```powershell
uv run --no-project --with-requirements frontend/tests/requirements.txt python -m playwright install chromium
node frontend/node_modules/vite/bin/vite.js frontend --host 127.0.0.1 --port 5183 --strictPort
```

Во втором терминале из корня репозитория:

```powershell
uv run --no-project --with-requirements frontend/tests/requirements.txt python frontend/tests/e2e.py
```

Тесты запускают headless Chromium с изолированными API-ответами, без обращения к рабочей БД,
OCR или LLM. Проверяются вход, cookie, восстановление и истечение сессии, ручные правки,
подтверждение, загрузка и статусы, аналитика, отчёты и ошибки. Viewports: 1440, 390 и 320 px.
Скриншоты находятся в игнорируемой папке `frontend/test-results/`.
Для production-сервера требуется перенаправление неизвестных путей frontend на `index.html`.

## Docker Compose

Из корня репозитория:

```powershell
docker compose up -d --build
docker compose ps
```

Остановите локальные Vite и backend перед запуском, чтобы освободить порты.
Сайт: http://localhost:5173. API и Swagger: http://localhost:8000/docs.
После первой сборки для обычного запуска достаточно `docker compose up -d`.
Frontend, backend, worker, PostgreSQL, Redis и MinIO запускаются в Compose.
Backend применяет миграции перед запуском API; worker и frontend ждут его readiness.

Для первоначальной настройки подготовьте `infra/postgres/postgres.env`,
`infra/minio/minio.env` и `backend/.env.docker` по соответствующим `.example`.
Пароли PostgreSQL и MinIO в backend должны совпадать с настройками сервисов.
PostgreSQL внутри Docker доступен как `postgres:5432`, Redis как `redis:6379`,
MinIO как `http://minio:9000`. `MINIO_PUBLIC_URL` должен быть доступен браузеру.

Frontend использует Nginx на порту 8080 внутри контейнера, без Node.js в runtime.
Адрес API при сборке пустой: браузер отправляет `/api/...` на origin сайта,
а Nginx проксирует запросы к `backend:8000`, сохраняя cookie и API-пути.
SPA-маршруты возвращают `index.html`; неизвестные API и assets сохраняют 404.
HTML не кэшируется, assets с хешем кэшируются на год.
Nginx допускает тело запроса до 32 MiB, но прикладной лимит фотографии пока 10 MiB.

Порты можно изменить переменными `FRONTEND_PORT` и `BACKEND_PORT`.
В dev-режиме Vite продолжает использовать `VITE_API_BASE_URL=http://localhost:8000`.

### Локальная Ollama для контейнера backend

Ollama остаётся на Windows. Compose задаёт backend адрес
`http://host.docker.internal:11434`, который можно переопределить переменной `LLM_BASE_URL`.
Ollama должна быть запущена и доступна из Docker. Для временного запуска в PowerShell:

```powershell
$env:OLLAMA_HOST="0.0.0.0:11434"
ollama serve
```

Если приложение Ollama уже запущено, сначала завершите его, чтобы освободить порт.
Этот bind разрешает подключения не только с loopback: ограничьте доступ к 11434
в Windows Firewall локальной машиной/Docker, не публикуйте Ollama в интернете.
Проверка из backend-контейнера:

```powershell
docker compose exec backend python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:11434/api/version', timeout=3).status)"
```

Модель `qwen3.5:4b` должна быть заранее скачана в Ollama. Readiness приложения не зависит от Ollama:
при её недоступности чеки и аналитика работают, генерация отчёта возвращает понятную ошибку.

### Изолированный Docker smoke

Требуется Docker Compose с поддержкой `!override` (2.24.4+).
Стенд использует отдельные тома, тестовую БД и порты 5184/8001/55434/46381/19000.
Команды из корня репозитория:

```powershell
docker compose -p ai-shopping-frontend-smoke -f docker-compose.yaml -f frontend/tests/compose.smoke.yaml up -d --build --wait --wait-timeout 180
uv run --no-project --with-requirements frontend/tests/requirements.txt python frontend/tests/docker_smoke.py
uv run --no-project --with-requirements frontend/tests/requirements.txt python frontend/tests/e2e.py --base-url http://localhost:5184
docker compose -p ai-shopping-frontend-smoke -f docker-compose.yaml -f frontend/tests/compose.smoke.yaml down -v
```

`docker_smoke.py` проверяет настоящую регистрацию, cookie-сессию и аналитику через Nginx,
создавая пользователя только в БД smoke-стенда. `e2e.py` проверяет полный интерфейс
с изолированными API-ответами уже на собранном Docker frontend.
Последняя команда удаляет контейнеры и тестовые данные только этого стенда.
