# Otclick Autofill (Firefox)

Расширение заполняет анкеты в Google Forms, Yandex Forms и Microsoft Forms
данными вашего резюме с hh.ru. **Отправляете форму вы сами** — расширение
никогда не нажимает «Отправить».

## Запуск локально

1. Поднять стек Otclick-HH: `docker compose up -d` в корне репозитория.
2. `cp .env.example .env` и вписать `VITE_SUPABASE_ANON_KEY` — это значение
   `SUPABASE_ANON_KEY` из корневого `.env` (оба ключа подписаны одним `JWT_SECRET`).
3. `npm install && npm run build`
4. Firefox → `about:debugging#/runtime/this-firefox` → «Load Temporary Add-on» →
   выбрать `.output/firefox-mv2/manifest.json`
5. Войти на `http://localhost:3000` — расширение подхватит сессию само.

Backend должен быть запущен с новым кодом: контейнер `api` собирает код внутрь
образа, поэтому после правок в `backend/` нужен `docker compose build api && docker compose up -d api`.

## Команды

| Команда | Что делает |
|---|---|
| `npm run dev` | сборка с автоперезагрузкой |
| `npm run build` | production-сборка в `.output/firefox-mv2` |
| `npm test` | vitest |
| `npm run typecheck` | `tsc --noEmit` |

## Как это устроено

```
content.ts   snapshot() собирает поля страницы (lib/snapshot.ts)
             → факты и PDF резюме проставляются сразу (lib/deterministic-fill.ts)
             → остальное уходит в фон
background.ts → POST /api/extension/fill (JWT из storage)
content.ts   ← значения → FormFiller проставляет, marks.ts подсвечивает
             пользователь правит и жмёт «Сохранить правки» → POST /api/extension/qa
```

Панель (`lib/panel.ts`) живёт в shadow DOM верхнего фрейма, три вкладки:
заполнение, чат, настройки. Чат ходит в `POST /api/extension/chat`, история — в
`browser.storage.local` (на сервере ничего не хранится).

Вход: content-script на домене Otclick читает cookie Supabase-сессии и передаёт
её в фон (`lib/session-sync.ts`). В Firefox нет `externally_connectable`, поэтому
это единственный путь передачи сессии.

## Manifest V2

Сборка идёт в MV2 — это дефолт WXT для Firefox и здесь он уместнее MV3: в
Firefox MV3 все хост-разрешения опциональные и пользователю пришлось бы выдавать
доступ вручную на каждом сайте. В MV2 они выдаются при установке. Подробности —
в `wxt.config.ts`.

## Известные ограничения v1

- Заполняется только верхний фрейм. Конверт `frames[]` готов с обеих сторон,
  но фан-аут по iframe ещё не включён.
- Ответ приходит целиком, без стриминга.
- Чат всегда видит текст открытой страницы (переключателя пока нет).
