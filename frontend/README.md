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
```

`npm run preview` показывает собранное приложение на http://localhost:5173.
