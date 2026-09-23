# web/AGENTS.md — правила фронтенда (дополняют корневой AGENTS.md)

- Next.js 16 App Router, TypeScript strict, Tailwind v4, shadcn/ui, lucide-react, TanStack Table + react-virtual, ECharts (echarts-for-react),
  next-intl (`ru`, `kk`), zod. Менеджер пакетов — **npm**. Владелец — B; `package.json` меняет только B.
- Спеки: `docs/SPEC_UI.md` (экраны, токены, i18n), `docs/SPEC_AI.md` (ИИ-UX), `docs/SPEC_SECURITY.md §2.4` (заголовки), типы — `@contracts/api`.
- API: только через `lib/api.ts` (добавляет `X-CSRF-Token`, разбирает `Problem`, валидирует zod). Пути `/api/v1/...` (rewrites на 127.0.0.1:8000).
  SSE чата — route handler `app/api/v1/ai/chat/route.ts`.
- Мок-режим `NEXT_PUBLIC_MOCK=1` обязателен для всех экранов: данные из `contracts/examples/*.json` и `lib/mock-data/*.ts`.
- Серверные компоненты по умолчанию; таблица, графики, панели, what-if, голос — клиентские компоненты.
- Все пользовательские строки — `next-intl` (`messages/ru.json`, `messages/kk.json`, одинаковые ключи; `npm run i18n:check`). Тексты от API — `I18nText[locale]`.
- Числа/даты/деньги — только `lib/format.ts`. Статусы — цвет + иконка + текст.
- Цвета — только CSS-переменные токенов; `--accent-500` только как заливка с тёмным текстом.
- Никаких внешних ресурсов в рантайме (CDN, Google Fonts по сети, аналитика). Шрифты — `next/font/google` (встраиваются при сборке).
- `localStorage` — только UI-настройки, всегда в try/catch. Бизнес-состояние — на сервере.
- Безопасность: `proxy.ts` (Next 16, бывший middleware) выставляет CSP с nonce и заголовки SPEC_SECURITY §2.4; `dangerouslySetInnerHTML` запрещён
  (кроме отрендеренного на сервере METHODOLOGY из доверенного файла репозитория с санитизацией); ссылки `[[sku:…]]` парсить вручную, не как HTML.
- Доступность WCAG 2.2 AA (SPEC_UI §5). Мобильная ширина: без горизонтального скролла страницы (таблица скроллится внутри).
- Проверки перед сдачей: `npm run lint && npm run typecheck && npm run build && npm run i18n:check`.
