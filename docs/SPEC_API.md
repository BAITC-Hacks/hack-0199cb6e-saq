# SPEC_API — FastAPI (`src/ekt_api`)

Типы — `contracts/api.ts` (источник истины), примеры — `contracts/examples/*.json`. Префикс `/api/v1`. Ошибки — `application/problem+json`
(`Problem`). Все даты ISO. API слушает **только 127.0.0.1:8000**; браузер ходит через Next.js (`/api/*` → rewrites).

## 1. Аутентификация и защита запросов

- `POST /auth/login` (`LoginRequest`) → 200 `User` + cookie `ekt_session` (случайные 32 байта, серверная сессия в SQLite, TTL 8 ч,
  `HttpOnly; SameSite=Strict; Path=/; Secure` при `ENV=prod`). Rate limit 5/мин/IP. Ошибка — одинаковое сообщение для неверного
  логина и пароля. argon2id.
- `GET /auth/me` → `User` (с `csrf_token`). `POST /auth/logout`.
- Все изменяющие запросы (POST/PATCH/DELETE, кроме login) требуют заголовок `X-CSRF-Token` = токен сессии → иначе 403.
- Пользователи — `var/users.json` (создаёт `scripts/make_users.py`, пароли из ввода/ENV, в репо не попадают). Роли: `buyer`,
  `approver`, `admin`. Локаль пользователя по умолчанию `ru`, переключение в UI (`PATCH /auth/me {locale}`).

## 2. Эндпоинты

| Метод и путь | Роль | Запрос → Ответ | Примечания |
|---|---|---|---|
| `POST /datasets` | buyer+ | multipart `files[]` (≤ 20 файлов, ≤ 50 МБ каждый) → `Dataset` | xlsx_safe, detect, адаптеры, качество, PII; сырые файлы удаляются после разбора |
| `POST /datasets/local` | admin | `{}` → `Dataset` | Только `ENV=dev|demo`: грузит `DATA_DIR`. Для демо без перетаскивания |
| `GET /datasets` / `GET /datasets/{id}` | buyer+ | → `Dataset[]` / `Dataset` | |
| `GET /datasets/{id}/quality` | buyer+ | → `QualityReport` | |
| `POST /runs` | buyer+ | `{dataset_id, params: RunParams}` → `RunSummary` | Синхронно (≤ 15 с); повтор с теми же входами → тот же `run_id` из кэша |
| `GET /runs` / `GET /runs/{run_id}` | buyer+ | → `RunSummary[]` / `RunSummary` | |
| `GET /runs/{run_id}/lines` | buyer+ | query: `supplier_id, channel_id, urgency, abc, flag, q, sort, order` → `LinesResponse` | Без пагинации (≤ 3 000 строк, gzip) |
| `GET /runs/{run_id}/skus/{sku_id}` | buyer+ | → `SkuDetail` | |
| `POST /runs/{run_id}/whatif` | buyer+ | `WhatIfRequest` → `WhatIfResponse` | Не сохраняется; rate limit 30/мин |
| `POST /orders` | buyer | `CreateOrderRequest` → `Order` | Строки = рекомендации с Q>0 (или `sku_ids`) по поставщику/каналу |
| `GET /orders` / `GET /orders/{id}` | buyer+ | → `Order[]` / `Order` | |
| `PATCH /orders/{id}/lines/{sku_id}` | buyer | `EditOrderLineRequest` → `Order` | Только `draft`. `reason` обязателен при `|final−recommended|/max(recommended,1) > 0.2` → иначе 422 `EDIT_REASON_REQUIRED`. Пересчёт в ед. закупки с округлением по кратности |
| `POST /orders/{id}/submit` | buyer | → `Order` | `draft → submitted` |
| `POST /orders/{id}/approve` | approver | → `Order` | `submitted → approved`; при `four_eyes` утверждающий ≠ отправивший → иначе 403 `FOUR_EYES` |
| `POST /orders/{id}/reject` | approver | `RejectRequest` → `Order` | `submitted → draft`, комментарий обязателен |
| `GET /orders/{id}/export?format=` | buyer+ | → файл | `1c_xlsx` и `manager_xlsx` — только `approved`/`exported`; `csv` — любой статус с водяным знаком `ЧЕРНОВИК` в первой строке для неутверждённых. Первый экспорт утверждённого → статус `exported` |
| `GET /audit?entity=&entity_id=&limit=` | approver, admin | → `AuditEntry[]` | |
| `GET /audit/verify` | approver, admin | → `AuditVerify` | Проверка цепочки хэшей |
| `POST /ai/chat` | buyer+ | `ChatRequest` → SSE `ChatEvent` | rate limit 20/мин; таймаут 90 с |
| `GET /ai/briefing?run_id=&locale=` | buyer+ | → `Briefing` | кэш по (run_id, locale) |
| `POST /ai/search` | buyer+ | `SearchRequest` → `SearchResult[]` | работает без LLM (BM25 + эмбеддинги/fallback) |
| `GET /ai/suggestions?dataset_id=&status=` | buyer+ | → `Suggestion[]` | |
| `POST /ai/suggestions/{id}/accept` / `reject` | buyer+ | → `Suggestion` | Принятые → `overrides` (влияют на следующий run) |
| `POST /ai/import/propose` | admin | multipart `file` → `ImportMappingProposal` | |
| `POST /ai/import/confirm` | admin | `ImportMappingConfirm` → `{profile_name}` | Сохраняет YAML в `var/profiles/custom/` |
| `POST /ai/voice` | buyer+ | multipart `audio` (webm/ogg/wav, ≤ 30 с, ≤ 3 МБ), `locale` → `VoiceResult` | аудио не сохраняется |
| `POST /ai/letter` | buyer+ | `{order_id, locale}` → `LetterDraft` | только черновик; отправки нет |
| `GET /ai/health` | buyer+ | → `AiHealth` | |
| `GET /health` | — | `{ok, version}` | |

## 3. SSE (`/ai/chat`)
`Content-Type: text/event-stream`; каждое событие — `data: <json ChatEvent>\n\n`; завершение — событие `final` или `error`.
Next.js: для SSE — route handler `web/app/api/v1/ai/chat/route.ts`, проксирующий поток на `127.0.0.1:8000` без буферизации
(обычные rewrites могут буферизовать).

## 4. Хранилище (SQLite `var/app.db`, SQLAlchemy 2 + Alembic, одна начальная миграция)

| Таблица | Поля |
|---|---|
| `sessions` | id (hash токена), username, csrf_token, created_at, expires_at, ip_hash |
| `datasets` | id, created_at, as_of, files_json, sku_count, quality_json, path (var/datasets/{id}) |
| `runs` | id (run_id), dataset_id, params_json, engine_version, created_at, summary_json, path (parquet) |
| `orders` | id, run_id, supplier_id, channel_id, status, created_by, created_at, submitted_by, submitted_at, approved_by, approved_at, rejected_comment |
| `order_lines` | order_id, sku_id, recommended_qty, final_qty, final_qty_purchase, edit_reason, value_kzt |
| `suggestions` | id, dataset_id, sku_id, type, payload_json, source_json, source_text, confidence, method, status, rationale_json, decided_by, decided_at |
| `overrides` | id, dataset_id, kind (successor/lifecycle/uom/launch/growth/stock), sku_id, payload_json, created_by, created_at |
| `audit_log` | id, ts, actor, action, entity, entity_id, payload_json, prev_hash, hash |

Нормализованные данные датасета — `var/datasets/{id}/*.parquet`; результаты прогона — `var/runs/{run_id}/*.parquet` + LRU-кэш в памяти.
`var/` в `.gitignore`.

## 5. Аудит
Каждое изменяющее действие (login успех/неудача, загрузка датасета, run, создание/правка/submit/approve/reject/export заказа,
accept/reject подсказки, confirm профиля импорта) → запись. `hash = sha256(prev_hash + canonical_json(entry_без_hash))`,
первая запись `prev_hash = "0"*64`. Payload без значений продаж и без ПД (только id, количества заказа, причины правок).

## 6. Экспорт (`ekt_api/export.py`)

**`1c_xlsx`** (для обработки 1С «Загрузка данных из табличного документа» в «Заказ поставщику»): лист `Заказ`, строка 1 — заголовки:
`Код | Артикул | Номенклатура | Количество | Ед. | Количество (ед. закупки) | Ед. закупки | Цена | Сумма | Поставщик | Канал | Плановая дата поступления`.
Количество — в единицах продажи (как в 1С), рядом — в единицах закупки. Без формул, все строки — текст/число.
Лист `Инфо`: номер заказа, run_id, as_of, кто утвердил и когда.

**`manager_xlsx`**: повторяет структуру рабочей таблицы менеджера SE (колонки `Артикул поставщика, Код 1с, Наименование, Категория,
СС реал, … , Свободный остаток, Запас, Заказ, в пути`) с заполненным «Заказ» + колонки `Рекомендовано, Обоснование, Срочность`.
Для ИЭК — аналог «Путь ИЭК» + колонка `Новый заказ`. Пишется новая книга (файл партнёра не модифицируется).

**`csv`**: UTF-8 с BOM, разделитель `;` (Excel ru), те же колонки, что `1c_xlsx`.

Во всех форматах: строковые значения, начинающиеся с `= + - @ \t \r`, экранируются префиксом `'`; имя файла
`order_{supplier}_{order_id}_{yyyymmdd}.{ext}` (ASCII, `Content-Disposition` с `filename*=`).
