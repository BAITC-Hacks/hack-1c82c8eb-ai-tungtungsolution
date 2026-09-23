# Career Quest · frontend

```sh
npm ci
npm run dev
```

Запустите backend на `127.0.0.1:8000`, затем откройте адрес Vite (обычно
http://localhost:5173). Vite проксирует `/api` в FastAPI; подписанная сессия
хранится в HttpOnly cookie.

Frontend подключён к API сессий, списка сотрудников, профиля, рекомендаций,
complete/dismiss, HR-обзора, загрузки полного датасета и журнала AI. Типы в
`src/api/schema.d.ts` генерируются из OpenAPI и не редактируются вручную.

После изменения endpoint-контрактов:

```sh
npm run gen:api
npm run build
```

Проверки:

```sh
npm run build
npm run lint
npm run test:e2e
```

Для браузерных тестов один раз выполните `npx playwright install chromium`.
