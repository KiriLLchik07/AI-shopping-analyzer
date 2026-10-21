# AI Shopping Analyzer

Веб-приложение для анализа покупок по фотографиям чеков. Распознаёт текст,
выделяет товары и суммы, позволяет исправить результат и посмотреть статистику расходов.
Локальная LLM формирует ежемесячные отчёты с рекомендациями.

## Возможности

- Загрузка фотографии и фоновое распознавание со статусами обработки.
- Ручная проверка магазина, даты, суммы, товаров и категорий.
- Аналитика по периодам, категориям, магазинам и товарам, сравнение месяцев.
- История LLM-отчётов и рекомендации на основе подтверждённых покупок.

В аналитику попадают только подтверждённые чеки. OCR и LLM работают локально;
изображения и сырой OCR-текст не передаются в LLM.

## Стек

| Часть | Технологии |
| --- | --- |
| Интерфейс | React, TypeScript, Vite, TanStack Query, Radix UI |
| API | Python 3.12, FastAPI, Pydantic |
| База данных | PostgreSQL, SQLAlchemy, Alembic |
| Фоновые задачи и сессии | Redis, RQ, отдельный worker |
| Фотографии | MinIO (S3) |
| Распознавание | PaddleOCR / PaddlePaddle, Pillow; worker на CPU |
| LLM-отчёты | Ollama, `qwen3.5:4b` |
| Запуск | Docker Compose, Nginx |
| Проверки | pytest, Vitest, Playwright, Ruff, Prettier |

## Запуск через Docker Compose

Нужны Docker Desktop с Linux-контейнерами и Docker Compose. Для отчётов нужна
Ollama на Windows; она запускается отдельно. Команды ниже выполняются в PowerShell
из корня проекта.

### 1. Подготовить настройки

При первом запуске создайте файлы из примеров. Если настройки уже существуют,
не перезаписывайте их:

```powershell
Copy-Item infra/postgres/postgres.env.example infra/postgres/postgres.env
Copy-Item infra/minio/minio.env.example infra/minio/minio.env
Copy-Item backend/.env.docker.example backend/.env.docker
```

Укажите свои пароли вместо значений из примеров:

- `DATABASE_URL` в `backend/.env.docker` должен соответствовать пользователю,
  паролю и БД из `infra/postgres/postgres.env`. Адрес внутри Docker — `postgres:5432`.
- Настройки MinIO в `backend/.env.docker` должны совпадать с
  `infra/minio/minio.env`. Внутренний адрес — `http://minio:9000`,
  адрес для браузера — `MINIO_PUBLIC_URL=http://127.0.0.1:9000`.
- Redis внутри Docker доступен по `redis://redis:6379/0`.

Реальные env-файлы не коммитятся в Git.

### 2. Подготовить локальные OCR-модели

Worker использует заранее скачанные веса PaddleOCR. Разместите их так:

```text
backend/models/
├── doc-orientation/                  # PP-LCNet_x1_0_doc_ori
│   ├── inference.json
│   ├── inference.pdiparams
│   └── inference.yml
└── ocr/
    ├── PP-OCRv5_mobile_det/
    └── cyrillic_PP-OCRv5_mobile_rec/
```

В каждой папке OCR-модели также нужны `inference.json`, `inference.pdiparams`
и `inference.yml`. Веса не хранятся в Git и подключаются к worker как read-only тома.
Если модели уже подготовлены, повторно скачивать их не нужно.

### 3. Запустить сервисы

Остановите локальные Vite и backend, если они занимают порты 5173 и 8000.

```powershell
docker compose up -d --build
docker compose ps
```

Compose запускает frontend, backend, worker, PostgreSQL, Redis и MinIO.
Служебный контейнер `minio-init` создаёт bucket и завершается.
Backend применяет миграции автоматически; frontend и worker ждут готовности API.

| Сервис | Адрес |
| --- | --- |
| Приложение | http://localhost:5173 |
| Swagger API | http://localhost:8000/docs |
| Консоль MinIO | http://localhost:9001 |

Откройте приложение, зарегистрируйтесь и загрузите чек. Сейчас поддерживаются
JPEG, PNG и WebP до 10 MiB; HEIC нужно предварительно преобразовать.
После распознавания проверьте данные и подтвердите чек.

Для следующих запусков достаточно `docker compose up -d`.
После изменения кода пересоберите образы с `--build`.

### 4. Подключить Ollama для отчётов

Скачайте модель, если она ещё не установлена:

```powershell
ollama pull qwen3.5:4b
```

Завершите уже запущенное приложение Ollama, затем в отдельном PowerShell:

```powershell
$env:OLLAMA_HOST="0.0.0.0:11434"
ollama serve
```

Оставьте терминал работающим. Backend обращается к Ollama через
`http://host.docker.internal:11434`; этот адрес уже задан в Compose.
Ограничьте доступ к порту 11434 в Windows Firewall: Ollama не должна быть доступна
из интернета. Без Ollama чеки и аналитика работают, но создание отчёта недоступно.

## Управление

```powershell
docker compose logs -f backend worker    # Логи обработки
docker compose stop                     # Остановка сервисов
docker compose down                     # Удаление контейнеров и сети, данные в томах сохраняются
```

`docker compose down -v` также удаляет тома с БД, фотографиями и Redis.
Используйте эту команду только для намеренного полного сброса данных.

## Структура проекта

```text
backend/             API, worker, OCR, парсинг, аналитика и LLM-отчёты
frontend/            React-приложение, Nginx и браузерные тесты
infra/               Настройки PostgreSQL и MinIO
docker-compose.yaml  Запуск сервисов приложения
```

Локальный запуск frontend и браузерные проверки описаны в
[frontend/README.md](frontend/README.md).
