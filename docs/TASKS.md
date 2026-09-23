# TASKS — задачи для Codex (копировать промпты дословно)

Общий префикс каждого промпта (Codex и так читает AGENTS.md, но повторяем ключевое):

```
Прочитай AGENTS.md и указанные разделы docs/. Работай только в перечисленных папках/файлах.
Не открывай и не запускай ничего с реальными данными (DATA_DIR, C:\ekt-data, *.xlsx вне tmp). Используй синтетику и fake-провайдеры ИИ.
Не меняй contracts/ (если ты не в задаче владельца C). Параметры — только из ekt_core/config.py.
В конце: прогони указанные проверки, выведи список изменённых файлов, результаты проверок и TODO(spec).
```

Легенда: **[поток] время · зависит от** → промпт → «Готово, когда».

---

## Поток C1 / C2 (данные, API, безопасность, ИИ-бэкенд)

### C-0 · каркас репозитория — [C1] 0:00–0:12 · нет
```
Задача C-0. Создай каркас Python-монорепо по AGENTS.md §3–4 и docs/SPEC_DATA.md §2, docs/SPEC_ENGINE.md §3, docs/SPEC_AI.md §3.
1) pyproject.toml (uv, Python 3.12, пакеты в src/: ekt_core, ekt_adapters, ekt_engine, ekt_ai, ekt_api), зависимости из AGENTS.md §2,
   dev: pytest, hypothesis, ruff, mypy, pip-audit, pip-licenses. Конфиги ruff (line-length 120), mypy (strict для ekt_core, ekt_engine), pytest.
2) src/ekt_core/config.py: EngineParams (pydantic, ВСЕ параметры и значения по умолчанию из SPEC_ENGINE §3) и Settings (env: ENV, DATA_DIR,
   VAR_DIR=var, LLM_PROVIDER, LLM_MODEL, LLM_MODEL_KK, EMBEDDER, EMBED_MODEL, STT, WHISPER_MODEL, AI_LOG_PROMPTS, FOUR_EYES, CLIENT_HASH_KEY не нужен).
3) src/ekt_core/schema.py: описания канонических таблиц (SPEC_DATA §2) — имена/типы колонок, функция validate_frame(df, spec) с понятными ошибками;
   dataclass CanonicalDataset (все таблицы + dataset_meta) с методом hash().
4) src/ekt_core/runview.py: Protocol RunView (summary(), lines(filters), sku_detail(sku_id), whatif(req), inbound(...), excess(...), at_risk(...))
   — типы по contracts/api.ts (pydantic-модели в src/ekt_api/schemas.py, сгенерируй их вручную 1:1 из contracts/api.ts).
   Плюс ExampleRunView, который отдаёт данные из contracts/examples/*.json (для тестов ИИ и API до готовности движка).
5) src/ekt_ai/providers.py: Protocol LLMProvider/Embedder/STT + детерминированные FakeLLM (таблица «шаблон вопроса → вызов инструмента/ответ»),
   FakeEmbedder (хэш-мешок слов, L2-нормировка), FakeSTT; фабрика по Settings. Ollama-реализации — заглушки NotImplemented (сделает C-2).
6) src/ekt_api/main.py: FastAPI с /api/v1/health, problem+json обработчик ошибок, структурный лог (structlog) без тел запросов.
7) tests/conftest.py (фикстура settings с fake-провайдерами), tests/test_smoke.py.
8) .pre-commit-config.yaml (ruff, gitleaks, scripts/check_no_data.py), scripts/check_no_data.py (SPEC_SECURITY §2.1), .github/workflows/ci.yml
   (uv sync, ruff, mypy, pytest, pip-audit, check_no_data; job web: npm ci, lint, typecheck, build — в папке web, если она есть),
   scripts/dev.ps1 (uvicorn 127.0.0.1:8000 + npm run dev в web + проверка http://127.0.0.1:11434/api/tags), scripts/prewarm.ps1 (заглушка),
   .env.example, LICENSE ("All rights reserved"), .gitattributes (eol).
.gitignore уже есть — не ослабляй его.
Проверки: uv sync; uv run pytest -q; uv run ruff check .; uv run mypy src/ekt_core.
```
Готово, когда: CI локально зелёный, `uvicorn` отвечает на `/api/v1/health`.

### C-1 · безопасная загрузка и адаптеры SE/ИЭК — [C1] 0:12–1:00 · C-0
```
Задача C-1. Реализуй src/ekt_adapters по docs/SPEC_DATA.md §1, §3, §4, §5, §6 и docs/SPEC_SECURITY.md §2.1–2.2.
- xlsx_safe.py: open_workbook(path, need_comments) с проверками сигнатуры, запретом макросов, лимитами zip (≤10000 записей, ≤200 МБ распаковано,
  ratio ≤200, файл ≤50 МБ), data_only=True, keep_links=False; разбор в отдельном процессе с таймаутом 60 с.
- months.py: парсер месячных заголовков (оба формата) и дат транзакций.
- detect.py: fingerprint по первым 5 строкам каждого листа → профиль (таблица SPEC_DATA §5).
- se.py, iek.py: разбор всех 12 профилей в канонические таблицы, включая: комментарии ячеек с ETA (SE-6), заголовки поставок с \xa0 и
  регэкспом (IEK-6), секции/волны ввода, суффиксы единиц, маркеры, цвет заливки (сырой), дубликаты, строки «Итого»/подзаголовки,
  типы документов, doc_key=год-номер, карантин неизвестных SKU, lead time каналов из документов, оценку текущего остатка ИЭК (D5).
  Комментарии и свободный текст — через ekt_ai.pii.scrub (если модуля ещё нет — вызов через интерфейс с no-op fallback и TODO).
- generic.py: чтение по YAML-профилю (для AI-4).
- quality.py: все коды SPEC_DATA §6 + сверка транзакции/месяц (Reconciliation).
- loader.py: load_dataset(paths) -> (CanonicalDataset, QualityReport, list[DetectedFile]); cli.py: `python -m ekt_adapters.cli load <dir>`
  печатает ТОЛЬКО агрегаты (кол-во строк/SKU/проблем), без значений.
- tests/adapters/builders.py: функции, создающие маленькие xlsx КАЖДОГО профиля точно по SPEC_DATA (листы, строка заголовка, подзаголовки,
  «Итого», скрытый лист, объединённые ячейки, комментарии с автором «Ivan.P:\n», \xa0, секции, дубликаты). Тесты на каждый профиль и на
  отказ xlsm/zip-бомбы/неизвестного файла/колонки «Контрагент».
Проверки: uv run pytest tests/adapters -q; ruff.
```
Готово, когда: тесты зелёные; человек C локально: `uv run python -m ekt_adapters.cli load C:\ekt-data` → агрегаты совпадают с SPEC_DATA §7.

### C-2 · провайдеры Ollama и страж приватности — [C2] 0:15–0:50 · C-0
```
Задача C-2. По docs/SPEC_AI.md §2, §3, §10:
- ekt_ai/providers.py: OllamaLLM (/api/chat, tools, format=JSON Schema, think=false, keep_alive, таймауты, 1 повтор при невалидном JSON),
  OllamaEmbedder (bge-m3, батчи по 32), WhisperSTT (faster-whisper, язык ru|kk, vad_filter, лимит 30 с), health() → AiHealth.
  Только 127.0.0.1; URL из Settings; при недоступности — понятная ошибка, без падения приложения.
- ekt_ai/pii.py: scrub(text) по правилам §10 (авторы комментариев, ИИН/БИН, телефоны, e-mail, латинские подписи, Natasha PER с белым
  списком брендов; если natasha не импортируется — только regex и флаг ner=false).
- tests/ai/test_pii.py (синтетические примеры, бренды не трогаются), tests/ai/test_providers_fake.py.
Проверки: uv run pytest tests/ai -q.
```

### C-3 · ИИ-аналитик: роутер, инструменты, агент, заземление — [C2] 0:50–1:40 · C-0, C-2
```
Задача C-3. По docs/SPEC_AI.md §4 реализуй:
- ekt_ai/router.py: интенты §4.3 для RU и KZ (месяцы в обоих языках, «дд.мм», «через N дней / N күннен кейін», каналы РФ/ПП/УТ, поставщики).
- ekt_ai/tools.py: 8 инструментов §4.2 поверх Protocol RunView (ekt_core/runview.py), pydantic-валидация аргументов, компактные результаты.
- ekt_ai/prompts/agent_system.ru.md и .kk.md (§4.4, глоссарий из SPEC_UI §6).
- ekt_ai/grounding.py (§4.5).
- ekt_ai/agent.py: async-генератор событий ChatEvent (intent/tool_call/tool_result/token/final/error): роутер → инструменты → LLM-формулировка;
  иначе цикл LLM с tools (≤4 вызова); PII-guard на вопрос; лимиты §11; опциональный LLM_MODEL_KK для финальной KZ-формулировки + повторное заземление.
- Тесты tests/ai/test_router.py (20 фраз RU/KZ), test_agent.py (FakeLLM + ExampleRunView: ожидаемые вызовы, нет изменяющих инструментов,
  ответ «утверди заказ» → отказ-шаблон), test_grounding.py.
Проверки: uv run pytest tests/ai -q.
```

### C-4 · синтетика в форматах партнёра — [C1] 1:00–1:30 · A-1 (synthetic), C-1
```
Задача C-4. По docs/SPEC_DATA.md §8.2 реализуй ekt_adapters/synthetic_xlsx.py: render(dataset, out_dir) пишет 12 xlsx в форматах партнёра,
переиспользуя tests/adapters/builders.py (перенеси общие билдеры в src/ekt_adapters/xlsx_builders.py), + файл «нового поставщика» для AI-4.
Тест tests/adapters/test_roundtrip.py: load_dataset(render(make_dataset(seed=42))) == канонические таблицы (с учётом PII-очистки, допуск по float).
Добавь фикстуру synthetic_xlsx_dir в tests/conftest.py.
Проверки: uv run pytest tests/adapters -q.
```

### C-5 · API: ядро, авторизация, аудит — [C1] 1:30–2:20 · C-0, C-1, A-5 (можно начать на ExampleRunView)
```
Задача C-5. По docs/SPEC_API.md §1, §2 (кроме заказов и ИИ), §4, §5 и docs/SPEC_SECURITY.md §2.3, §2.5, §2.7:
- ekt_api/db.py (SQLAlchemy 2, SQLite var/app.db), Alembic с одной начальной миграцией всех таблиц SPEC_API §4.
- auth.py: argon2id, серверные сессии, cookie, CSRF, require_role, slowapi-лимиты; scripts/make_users.py (создаёт var/users.json).
- audit.py: запись с цепочкой хэшей, verify().
- routers: auth, datasets (upload multipart + local для ENV=dev|demo), runs (вызов ekt_engine.pipeline.run; реализация RunView поверх RunResult в
  ekt_api/runview_impl.py; кэш LRU и parquet в var/runs), lines, skus, whatif, audit.
- Все ошибки — Problem. Лог без значений.
- Тесты tests/api/*: логин/лимит/CSRF/RBAC, загрузка синтетических xlsx (фикстура synthetic_xlsx_dir), run детерминирован, lines/sku соответствуют
  схемам, whatif, аудит verify=ok и ломается при подмене записи.
Проверки: uv run pytest tests/api -q; ruff; uvicorn стартует.
```

### C-6 · ИИ-эндпоинты — [C2] 1:40–2:20 · C-3, C-5 (роуты можно писать параллельно, подключить в main в конце)
```
Задача C-6. По docs/SPEC_API.md §2 (строки /ai/*), §3 и docs/SPEC_AI.md §5–§9:
- routers/ai.py: /ai/chat (SSE), /ai/briefing, /ai/search, /ai/suggestions (+accept/reject → overrides), /ai/import/propose|confirm, /ai/voice,
  /ai/letter, /ai/health. Лимиты, роли, аудит (accept/reject/confirm).
- ekt_ai/briefing.py (факты кодом + LLM + шаблон + кэш), ekt_ai/letter.py, ekt_ai/importer.py (§7), ekt_ai/voice.py (§9).
- Фоновая генерация брифинга при создании run (BackgroundTasks).
- Тесты tests/api/test_ai_*.py на fake-провайдерах (SSE-поток разбирается, briefing fallback на шаблон при ошибке LLM, импорт синтетического
  «нового поставщика» ≥80% колонок, voice лимиты размера/типа).
Проверки: uv run pytest -q.
```

### C-7 · заказы и экспорт — [C1] 2:20–2:45 · C-5
```
Задача C-7. По docs/SPEC_API.md §2 (orders), §6 и docs/SPEC_SECURITY.md §2.6:
- services/orders.py: создание из run, правка с правилом причины (>20%), пересчёт в ед. закупки с округлением, submit/approve/reject со статусами,
  «четыре глаза» (Settings.FOUR_EYES), аудит каждого действия.
- export.py: 1c_xlsx, manager_xlsx (SE и ИЭК варианты), csv (BOM, ;), экранирование формул, имена файлов, Content-Disposition.
- routers/orders.py. Тесты: полный цикл buyer→approver, 403 FOUR_EYES, 422 EDIT_REASON_REQUIRED, экспорт неутверждённого 1c_xlsx → 409,
  ячейка "=HYPERLINK(...)" в названии экранирована, кратность соблюдена.
Проверки: uv run pytest tests/api -q.
```

### C-8 · усиление безопасности и CI — [C2] 2:20–2:45 · C-5
```
Задача C-8. По docs/SPEC_SECURITY.md §2 и §3:
- tests/security/test_no_egress.py (запрещённые импорты smtplib/requests к внешним хостам/URL-схемы в src/, кроме 127.0.0.1), test_upload_limits.py,
  test_session_cookie_flags.py, test_rate_limits.py.
- CI: pip-audit, npm audit --omit=dev (в web), проверка лицензий (pip-licenses, npx license-checker) с запретом GPL/AGPL, gitleaks.
- scripts/gen_licenses.py → THIRD_PARTY_LICENSES.md (+ таблица моделей ИИ и шрифтов из SPEC_SECURITY §4).
- scripts/prewarm.ps1 (SPEC_AI §2): определить VRAM через nvidia-smi и предупредить, если LLM_MODEL/WHISPER_MODEL не подходят по таблице;
  прогрев LLM/эмбеддера (bge-m3 с num_gpu=0 при VRAM ≤ 8 ГБ)/whisper, построение индекса поиска для последнего датасета, замер ток/с.
Проверки: uv run pytest -q; CI локально (act не нужен — просто команды из workflow).
```

### C-9 · документы — [C2] 2:45–3:15 · всё
```
Задача C-9. Сгенерируй итоговые документы по коду и спекам (не выдумывай возможностей, которых нет в коде; проверяй по src/):
- README.md: что это (1 абзац), ключевые возможности, скриншоты (плейсхолдеры docs/img/*.png), быстрый старт Windows (uv, npm, Ollama, модели,
  scripts/make_users.py, scripts/dev.ps1, загрузка данных), методология кратко, **алгоритм исключения разовых заказов** (SPEC_ENGINE §2.3 человеческим языком
  + пример), восстановление stockout, ИИ (локально, что умеет и чего не делает), безопасность и приватность кратко, ограничения и вопросы к партнёру
  (docs/QUESTIONS.md), структура репо, тесты (как доказываются must-have 1–5).
- docs/METHODOLOGY.md (для менеджера закупа, RU, с формулами в приложении) + раздел «Қысқаша (KZ)».
- docs/SECURITY.md, docs/PRIVACY.md по SPEC_SECURITY §3–§4.
Проверки: ссылки на файлы существуют; команды из README выполняются на чистом клоне (на синтетике).
```

---

## Поток A1 / A2 (движок и ИИ-данные)

### A-1 · синтетика, история, очистка, разовые заказы — [A1] 0:12–0:45 · C-0
```
Задача A-1. По docs/SPEC_DATA.md §8.1 и docs/SPEC_ENGINE.md §2.1–2.3:
- src/ekt_core/synthetic.py: make_dataset(seed=42, n_se=60, n_iek=140) → CanonicalDataset + truth; все паттерны, инъекции и специальные SKU из §8.1.
- src/ekt_engine/history.py, cleaning.py, oneoff.py: как в спеке, включая правило вычитания D3, REGULAR_LARGE_BUYER, Hampel, таблицу oneoff_lines.
- Тесты tests/engine/test_synthetic.py (детерминизм, наличие спец-SKU), test_oneoff.py (разовая строка ловится, регулярный крупный — нет,
  строка только в транзакциях → ONE_OFF_NOT_IN_MONTHLY и месяц не уменьшается), test_cleaning.py.
Проверки: uv run pytest tests/engine -q; mypy src/ekt_engine src/ekt_core.
```

### A-3 · stockout, классы, сезонность, прогноз — [A1] 0:45–1:20 · A-1
```
Задача A-3. По docs/SPEC_ENGINE.md §2.4–2.7: stockout.py (явный, частичный по транзакциям, неявный, восстановление с cap, NaN-импутация),
classify.py (SB-классы, dead/new, ABC вычисляемый), seasonality.py (априор 0.5/0.5, группа, SKU, сжатие, клип, нормировка),
forecast.py (уровень EW, TSB, Theil–Sen тренд с затуханием, ручной прирост, новинки через AnalogsProvider (Protocol) с fallback по токенам,
σ и интервалы). Интерфейс AnalogsProvider объяви в ekt_engine/interfaces.py.
Тесты: восстановление частичного месяца ±25% от truth; сезонный профиль corr>0.8; TSB для прерывистого; тренд клипуется; новинка по аналогам.
Проверки: uv run pytest tests/engine -q; mypy.
```

### A-5 · политика, проекция, объяснения, конвейер, what-if — [A1] 1:20–2:00 · A-3
```
Задача A-5. По docs/SPEC_ENGINE.md §1, §2.8–2.11:
- policy.py, projection.py (матрично SKU×180 дней), explain.py (waterfall с точной суммой, контрфакты, reason codes, reason_short RU/KZ, plural_ru),
  src/ekt_engine/i18n/reasons.ru.yaml и reasons.kk.yaml (ВСЕ коды из §2.10; KZ помечены для вычитки в reasons.meta.yaml).
- pipeline.py: prepare(dataset, params, overrides, analogs_provider) (кэш), plan(...), run(...) → RunResult с полями, достаточными для
  Line/SkuDetail/RunSummary из contracts/api.ts (маппинг в ekt_engine/to_contract.py), run_id по §1. overrides: successor/lifecycle/uom/launch/growth/stock.
- whatif.py (§2.11) с целями производительности.
Тесты: сумма waterfall = Q; блокировки EOL/MTO/dead/N; округление по кратности и единицам; CHANNEL_SPLIT; determinism; производительность на 3 000
синтетических SKU (prepare ≤ 12 с, plan ≤ 2 с — пометь тест @pytest.mark.slow).
Проверки: uv run pytest tests/engine -q; mypy.
```

### A-6 · приёмочные тесты MH1–MH5 — [A1] 2:00–2:30 · A-5
```
Задача A-6. Реализуй tests/acceptance/* строго по таблице docs/SPEC_ENGINE.md §5 (все 11 файлов). Если тест падает — исправляй движок,
НЕ ослабляя проверки и не меняя пороги тестов. Сформируй tests/acceptance/README.md: какой must-have доказывает каждый тест и как запустить.
Проверки: uv run pytest tests/acceptance -q.
```

### A-8 · калибровка на реальных данных — [A, человек] 2:20–2:40 · C-1, A-5
Без Codex. В своём терминале: загрузить `C:\ekt-data`, прогнать расчёт, пройти чек-лист PLAN §7. Изменения — только значения в
`ekt_core/config.py` (с комментарием «калибровка на данных 22.09.2026») и вопросы в `docs/QUESTIONS.md`.

### A-2 · обогащение названий и поиск — [A2] 0:20–1:00 · C-0
```
Задача A-2. По docs/SPEC_AI.md §5.1–5.2: ekt_ai/abbrev.py (словарь сокращений + нормализация запроса), ekt_ai/enrich.py (словарь + LLM-батчи по 20 с
JSON-схемой, кэш var/ai_cache.sqlite по sha1 имени, повтор 1 раз), ekt_ai/search.py (код/артикул → BM25 → эмбеддинги → RRF k=60, работа без эмбеддера).
Тесты на FakeLLM/FakeEmbedder: «двойная розетка с заземлением белая атлас» находит синтетический «Роз. 2-ная с/у 16А с з/к з/ш "ATLAS" белый»;
KZ-запрос; точный код наверху; < 150 мс на 3 000 SKU.
Проверки: uv run pytest tests/ai -q.
```

### A-4 · аналоги и разбор пометок — [A2] 1:00–1:40 · A-2, C-2
```
Задача A-4. По docs/SPEC_AI.md §5.3 и §6: ekt_ai/analogs.py (реализует ekt_engine.interfaces.AnalogsProvider), ekt_ai/notes.py (правила + LLM
structured output, направление замены по датам продаж, confidence-правила, PII-guard перед LLM) → список Suggestion (contracts/api.ts).
Тесты: синтетические пометки «замена X», «EOL», «под заказ», суффиксы, секции, «!!!» → ожидаемые подсказки и confidence; аналоги новинки из той же серии.
Проверки: uv run pytest tests/ai -q.
```

### A-7 · бэктест — [A2] 1:40–2:20 · A-5
```
Задача A-7. По docs/SPEC_ENGINE.md §4: ekt_engine/backtest.py (происхождения, методы наш/наивный/прокси менеджера с формулами SPEC_DATA SE-6,
метрики, упрощённая симуляция), CLI `python -m ekt_engine.backtest --dataset <id>` → var/backtest.json и docs/BACKTEST.md (шаблон с честными
выводами: где лучше/хуже, допущения). Тест на синтетике: наш WAPE ≤ наивного на сезонных и stockout-SKU.
Проверки: uv run pytest tests/engine -q.
```

### A-9 · подключение подсказок и аналогов в расчёт — [A2] 2:20–2:45 · A-4, C-5, C-6
```
Задача A-9. Свяжи: принятые подсказки (таблица overrides в SQLite) → overrides движка; ekt_ai.analogs → analogs_provider в ekt_api при run;
после accept подсказки UI может перезапустить run (новый run_id, т.к. overrides входят в хэш). Тест API: accept successor → у нового SKU появилась
история и reason SUCCESSOR_HISTORY; accept EOL → Q=0.
Проверки: uv run pytest -q.
```

---

## Поток B1 / B2 (интерфейс)

### B-0 · каркас web — [B1] 0:00–0:25 · нет
```
Задача B-0. Прочитай web/AGENTS.md, docs/SPEC_UI.md §1, §2, §6, §7 и docs/SPEC_SECURITY.md §2.4. Создай Next.js 16 приложение в web/
(TS strict, App Router, Tailwind v4, ESLint), shadcn/ui, lucide-react, next-intl (ru, kk; messages/ru.json и kk.json с одинаковыми ключами +
скрипт npm run i18n:check), echarts + echarts-for-react, @tanstack/react-table + react-virtual, zod.
- globals.css: токены SPEC_UI §1 (светлая и тёмная), шрифты PT Sans / PT Mono через next/font/google.
- Каркас: левое меню (8 разделов), шапка (поиск-заглушка, кнопка ИИ, RU|ҚАЗ, пользователь, индикатор ИИ, бейдж офлайн), страницы-заглушки всех маршрутов SPEC_UI §3.
- lib/format.ts, lib/api.ts (CSRF, Problem, zod), lib/mock.ts (NEXT_PUBLIC_MOCK=1: contracts/examples/*.json + сгенерируй моки для остальных типов
  из contracts/api.ts в lib/mock-data/*.ts), tsconfig alias @contracts → ../contracts.
- next.config.ts: rewrites /api/v1/* → http://127.0.0.1:8000; proxy.ts: CSP с nonce и заголовки.
- scripts: dev, build, start, lint, typecheck, i18n:check.
Проверки: npm run lint && npm run typecheck && npm run build && npm run i18n:check.
```

### B-1 · таблица рекомендаций — [B1] 0:25–1:05 · B-0
```
Задача B-1. docs/SPEC_UI.md §3 п.7: страница /runs/[id]: KPI-полоса (RunSummary), вкладки поставщиков → каналы, чипы-фильтры, поиск,
виртуализированная TanStack-таблица со всеми колонками, форматированием, бейджами срочности (цвет+иконка+текст), «оценка» остатка,
единицы продажи/закупки («9 бухт = 2 745 м»), подсветка покрытия <1 и >4, выбор строк, клавиатура ↑↓/Enter, баннер оценки остатка ИЭК.
Данные — lib/api (в mock-режиме из contracts/examples). Все строки через next-intl.
Проверки: lint, typecheck, build; вручную: NEXT_PUBLIC_MOCK=1 — таблица, вкладки, фильтры работают.
```

### B-3 · карточка SKU — [B1] 1:05–1:50 · B-1
```
Задача B-3. docs/SPEC_UI.md §3 п.8: Sheet-карточка SKU: шапка, график ECharts (факт, очищенный, восстановленный пунктир, заливка месяцев с
доступностью <0.95, ✕ разовых заказов с подсказкой, прогноз + коридор, маркеры ETA, «сегодня»), вкладка «Проекция», waterfall, причины, чипы
контрфактов, таблицы разовых строк/поставок/аналогов/пометок, what-if слайдеры → POST whatif (debounce 300 мс) с показом дельты.
Доступность: текстовая сводка под графиком. Мок — contracts/examples/sku_detail.json (+ мок whatif).
Проверки: lint, typecheck, build.
```

### B-5 · заказы, параметры расчёта, аналитика — [B1] 1:50–2:40 · B-1
```
Задача B-5. docs/SPEC_UI.md §3 п.6, 9, 10: /runs/new (форма RunParams с таблицей плана прироста), /orders и /orders/[id] (создание из выбранных
строк, правка количества с обязательной причиной при |Δ|>20%, статус-лента, действия по роли, сообщение «четыре глаза», экспорт трёх форматов,
блок «Сводка для утверждающего (ИИ)», кнопка «Черновик письма (ИИ)» — модалку делает B-6), /analytics (тренды, сезонность наша vs партнёра,
избыток топ-20, тепловая карта срочность×ABC, бэктест). Моки для всех ответов.
Проверки: lint, typecheck, build.
```

### B-7 · переключение на реальный API и полировка — [B1] 2:45–3:15 · C-5, C-6, C-7
Людьми + Codex точечно: `NEXT_PUBLIC_MOCK=0`, пройти DEMO.md, исправить расхождения, пустые/ошибочные состояния, вычитка KZ, контраст, фокус.

### B-2 · ИИ-помощник и палитра — [B2] 0:30–1:15 · B-0
```
Задача B-2. docs/SPEC_UI.md §3 п.13–14 и docs/SPEC_AI.md §4: правая панель ИИ-помощника (Ctrl+J): SSE-клиент ChatEvent (fetch + ReadableStream,
CSRF), показ хода (intent/tool_call), стрим токенов, рендер [[sku:КОД]] → открыть карточку, бейдж заземления (✓/⚠ со списком), бейдж
«Сгенерировано ИИ · локально», быстрые вопросы RU/KZ (из DEMO.md), история ≤10, ограничение 1000 символов. Палитра Ctrl+K (shadcn Command) с
семантическим поиском (/ai/search) и навигацией. Route handler web/app/api/v1/ai/chat/route.ts — прокси SSE без буферизации.
Мок-режим: сценарий событий из lib/mock-data/chat.ts.
Проверки: lint, typecheck, build.
```

### B-4 · брифинг, данные, подсказки, импорт — [B2] 1:15–2:00 · B-0
```
Задача B-4. docs/SPEC_UI.md §3 п.2–5: главная с карточкой брифинга (Briefing, стрим/скелетон, ссылки на SKU) и KPI; /data (загрузка multipart,
кнопка демо-данных для admin, таблица DetectedFile, отчёт качества с группами и графиком сверки, счётчик PII); /data/suggestions (карточки по типам,
подсветка исходного фрагмента, принять/отклонить, массовое принятие ≥0.9, тост + «Пересчитать»); /data/import (мастер сопоставления колонок).
Проверки: lint, typecheck, build.
```

### B-6 · голос, письмо, методология, аудит, логин — [B2] 2:00–2:40 · B-2
```
Задача B-6. Кнопка микрофона в панели ИИ (удержание, MediaRecorder webm/opus, ≤30 с, индикатор записи, POST /ai/voice, текст в поле ввода,
ошибки доступа к микрофону), модалка «Черновик письма поставщику» (LetterDraft, копировать, надпись про ручную отправку), /methodology (рендер
docs/METHODOLOGY.md, импорт как строки на этапе сборки), /audit (таблица + «Проверить целостность»), /login, меню пользователя с ролью,
индикатор ИИ по /ai/health, переключатель темы.
Проверки: lint, typecheck, build.
```

---

## Интеграция (все) — 2:40–3:00
1. `main` содержит все PR; `uv run pytest -q` и `npm run build` зелёные.
2. `scripts/make_users.py` → buyer / approver / admin; `pwsh scripts/prewarm.ps1`; `pwsh scripts/dev.ps1`.
3. Сквозной сценарий `docs/DEMO.md §1` на реальных данных (локально) и на синтетике (для видео, если публичное).
4. Баги → владельцу зоны; фиксы только маленькие; после 3:30 — только блокеры.
