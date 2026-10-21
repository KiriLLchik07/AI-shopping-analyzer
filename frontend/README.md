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
