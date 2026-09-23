# Backend integration

`src/api/client.ts` — единственная граница между сгенерированными OpenAPI-типами
и моделями отображения. Ошибки FastAPI преобразуются в читаемые сообщения и
всегда показываются в интерфейсе.

Подключённые маршруты:

- `GET/POST/DELETE /api/session`
- `GET /api/employees`
- `GET /api/employee/profile`
- `POST /api/employee/recommendations`
- `POST /api/employee/events/{event_id}/complete`
- `POST /api/employee/events/{event_id}/dismiss`
- `GET /api/hr/overview`
- `POST /api/hr/dataset`
- `GET /api/hr/agent-runs`

HR upload отправляет `FormData` с обязательными полями `employees`, `events`,
`skills`, `activity_history`. `openapi-fetch` получает FormData через
`bodySerializer`, поэтому браузер сам задаёт корректный multipart boundary.

После complete/dismiss обновляются профиль, рекомендации, HR-обзор и журнал.
После смены cookie-сессии приватные query-кэши удаляются. Backend остаётся
источником истины для роли и employee identity.

Текущий `GET /api/hr/overview` предоставляет агрегаты готовности по отделам и
разрывы навыков. В нём пока нет исходно запланированных полей участия по событиям
и списка сотрудников без подходящего шага; frontend не вычисляет и не подменяет
эти серверные показатели.
