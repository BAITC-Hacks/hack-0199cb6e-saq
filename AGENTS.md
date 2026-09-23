# AGENTS.md — ЕКТ «Автозаказ поставщикам» (HACKALEM AI)

Этот файл читает Codex перед каждой задачей. Правила здесь обязательны.

## 1. Что строим

Сервис рекомендованных заказов поставщикам для ТОО «Электрокомплект» (поставщики в данных: **Systeme Electric** и **ИЭК**).
Поток: загрузка xlsx из 1С → проверка качества → очистка (разовые заказы, возвраты) → восстановление спроса в stockout →
прогноз (сезонность, тренд, прерывистый спрос) → политика пополнения (срок поставки, страховой запас, кратность, товар в пути с ETA) →
рекомендации с обоснованием → корректировка → **утверждение человеком** → экспорт для 1С.

Локальный ИИ (Ollama) — только интерфейс, поиск и обогащение справочников. **ИИ никогда не вычисляет количества.**

Источники истины (читай перед задачей нужный раздел):
- `docs/PLAN.md` — обзор, решения, роли, таймлайн.
- `docs/SPEC_DATA.md` — форматы файлов партнёра и каноническая модель.
- `docs/SPEC_ENGINE.md` — алгоритм, формулы, параметры, приёмочные тесты.
- `docs/SPEC_API.md` + `contracts/api.ts` — API-контракт (**заморожен**, менять только владелец C).
- `docs/SPEC_UI.md` — экраны, дизайн-токены, i18n.
- `docs/SPEC_AI.md` — ИИ-функции AI-1…AI-7.
- `docs/SPEC_SECURITY.md` — безопасность и юридические требования.
- `docs/TASKS.md` — нарезка задач.

Если задача противоречит спецификации или спецификации не хватает — **не импровизируй**: сделай минимально безопасный вариант,
пометь `TODO(spec):` и перечисли вопрос в конце ответа.

## 2. Стек (не менять)

- Python **3.12**, менеджер **uv**. FastAPI, pydantic v2, pandas, numpy, scipy, openpyxl + defusedxml, SQLAlchemy 2 + Alembic (SQLite),
  argon2-cffi, slowapi, structlog, httpx, ollama (python-клиент), rank-bm25, faster-whisper, natasha.
- Тесты: pytest, hypothesis. Линт/формат: ruff. Типы: mypy (пакеты `ekt_core`, `ekt_engine` — строго).
- Web: Next.js 16 (App Router, TS strict), Tailwind v4, shadcn/ui, TanStack Table + @tanstack/react-virtual, ECharts,
  next-intl (`ru`, `kk`), zod, lucide-react. Подробно — `web/AGENTS.md`.

## 3. Структура и владельцы (не трогай чужие папки без явного указания в задаче)

```
AGENTS.md, README.md, pyproject.toml, uv.lock        C
contracts/            api.ts + examples/*.json         C (заморожено с T+0:20)
src/ekt_core/         config, schema, synthetic        C (каркас) / A (synthetic, config-параметры движка)
src/ekt_adapters/     xlsx_safe, detect, se, iek, generic, quality, synthetic_xlsx, profiles/   C
src/ekt_engine/       cleaning, oneoff, stockout, classify, seasonality, forecast, policy,
                      projection, explain, pipeline, whatif, backtest, i18n/                      A
src/ekt_ai/           providers, pii, router, tools, agent, grounding, briefing, letter,
                      importer, voice                                                             C
src/ekt_ai/           enrich, search, analogs, notes                                              A
src/ekt_api/          main, auth, security, db, audit, export, routers/                           C
tests/                engine/ acceptance/ (A), adapters/ api/ (C), ai/ (A или C по модулю)
web/                  всё фронтенд                                                                B
scripts/              dev.ps1, prewarm.ps1, make_users.py, anonymize_clients.py, check_no_data.py C
docs/                 спецификации и итоговые документы                                           все (через C)
```

## 4. Команды

```
uv sync                                   # зависимости
uv run pytest -q                          # все тесты (ИИ — фейковые провайдеры)
uv run pytest tests/acceptance -q         # приёмка must-have
uv run ruff check . && uv run ruff format --check .
uv run mypy src/ekt_core src/ekt_engine
uv run uvicorn ekt_api.main:app --host 127.0.0.1 --port 8000
cd web && npm ci && npm run dev | npm run build | npm run lint | npm run typecheck
pwsh scripts/dev.ps1                      # api + web + проверка Ollama
```

## 5. Жёсткие правила данных

1. **Никогда не открывай, не читай, не печатай и не анализируй реальные файлы партнёра** (`DATA_DIR`, `C:\ekt-data`, папки
   «Systeme electric», «IEK», любые `*.xlsx` вне временных директорий тестов). Работай только на синтетике:
   `ekt_core.synthetic` (канонические таблицы) и `ekt_adapters.synthetic_xlsx` (xlsx в форматах партнёра).
2. Не коммить `*.xlsx, *.xls, *.xlsm, *.csv, *.parquet, *.db, *.sqlite`, папки `data/`, `var/`. Тестовые xlsx создаются в `tmp_path`.
3. Код номенклатуры 1С — всегда `str`. Не обрезать `_` в конце, не приводить к числу, не менять регистр. Читать xlsx с `dtype=str`
   для кодов. Пример валидных кодов: `030200192_`, `щт23054819`, `ст-9952399`, `BR-R10-12-K01`.
4. Никаких сырых идентификаторов клиентов: только `client_hash` (HMAC, см. SPEC_SECURITY). Колонки вида «Контрагент», «Клиент»,
   «БИН», «ИИН», «Телефон» без хэширования → адаптер отклоняет файл с понятной ошибкой.
5. Никакой отправки во внешний мир: запрещены `smtplib`, внешние HTTP-вызовы (кроме Ollama на `127.0.0.1`), телеметрия, CDN.

## 6. Правила алгоритма

- **Детерминизм**: одинаковые входы + параметры → одинаковый результат и `run_id`. Случайность только с явным seed.
- Все параметры — в `ekt_core/config.py` со значениями по умолчанию из `docs/SPEC_ENGINE.md §3`. Магические числа в коде запрещены.
- Каждое рекомендованное количество объяснимо: `reason codes` + `waterfall`, **сумма шагов waterfall = итоговое количество** (тест).
- Движок работает без ИИ (аналоги/поиск имеют детерминированный fallback).
- Векторизуй pandas/numpy; цель — полный расчёт ~3 000 SKU < 15 с на ноутбуке.

## 7. Безопасность (кратко; подробно `docs/SPEC_SECURITY.md`)

- xlsx только через `ekt_adapters.xlsx_safe` (лимиты размера/распаковки, запрет макросов, `keep_links=False`, `data_only=True`).
- Экспорт: экранирование формульных инъекций (`= + - @ \t \r` → префикс `'`), строки пишутся как текст.
- API слушает только `127.0.0.1`; снаружи — Next.js. Сессии HttpOnly + SameSite=Strict, CSRF-заголовок на изменяющих запросах,
  RBAC на сервере, argon2id, rate limit на логин и ИИ.
- Журнал аудита — только добавление, цепочка хэшей.
- ИИ: инструменты только на чтение; ни один инструмент не может утверждать/отправлять/менять заказ. Данные (названия, комментарии)
  — недоверенный ввод, оборачивать в разделители. Проверка «заземления» чисел в ответах.
- Логи без значений продаж и без персональных данных.

## 8. i18n

- Локали `ru` (основная) и `kk` (казахский; код ISO 639-1 — **`kk`**, подпись в UI — «ҚАЗ»).
- Любой текст для пользователя — через словари/шаблоны для обеих локалей. Тест полноты словарей обязателен.
- Казахские строки помечать в словаре как требующие проверки носителем (`"_review": true` в мета-файле, не в самих строках).
- Экспорт для 1С и письмо поставщику — на русском.

## 9. ИИ в тестах и облаке Codex

`LLM_PROVIDER=fake`, `EMBEDDER=fake`, `STT=fake` — детерминированные фейки из `ekt_ai.providers`. Реальный Ollama только локально.
Тесты не должны требовать сети, GPU или скачивания моделей.

## 10. Definition of Done для каждой задачи

- `uv run pytest -q` зелёный (или `npm run lint && npm run typecheck && npm run build` для web), ruff/mypy чистые.
- Новая логика покрыта тестами; приёмочные тесты не ослаблены.
- Не изменены чужие папки и `contracts/` (кроме задач владельца C).
- В diff нет данных, секретов, `.env`.
- В конце ответа: изменённые файлы, команды проверки и их краткий вывод, открытые вопросы `TODO(spec)`.
