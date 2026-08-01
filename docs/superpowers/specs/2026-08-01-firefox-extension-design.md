# Firefox-расширение: автозаполнение форм + чат с ИИ

Дата: 2026-08-01
Статус: спека утверждена, план не написан

## Задача

Расширение для Firefox, которое заполняет анкеты в Google Forms, Yandex Forms и
Microsoft Forms (forms.office.com) от имени пользователя Otclick-HH. LLM видит
контекст кандидата (профиль + резюме с hh + сохранённые вопрос-ответы) и текст
страницы (вакансия/анкета). Вторая вкладка панели — чат с ИИ, у которого тот же
контекст.

Вне объёма: ATS-проверка, генерация и «тюнинг» резюме, fit-score, LinkedIn-агент,
квоты и биллинг внутри расширения, автоотправка формы.

## Решения (зафиксированы с заказчиком)

| Вопрос | Решение |
|---|---|
| База кода | Форк расширения OtclickUS (`extension/`, gitignored) с вырезанием лишнего |
| «Teams» | Это Microsoft Forms — `forms.office.com` |
| Браузеры | Только Firefox |
| Контекст LLM | Резюме с hh.ru + `qa_memory` (+ факты профиля); PDF резюме с hh — прикрепляем |
| Чат | Без истории на сервере: история в `browser.storage.local` |
| Отправка формы | Расширение только заполняет, submit жмёт человек |
| Обучение | Правки пользователя пишутся в `qa_memory` |
| Авторизация | Автоподхват Supabase-сессии с домена Otclick (content script + cookie) |

## Архитектура

```
Firefox                                     Otclick-HH backend (FastAPI)
┌──────────────────────────────┐            ┌─────────────────────────────────┐
│ content.ts                   │            │ api/extension.py                │
│   snapshot() ─ поля страницы │            │   get_current_user (Supabase JWT)│
│   applyFill() + marks        │            │                                 │
│   sidebar (3 вкладки)        │            │ services/candidate_context.py   │
└───────┬──────────────────────┘            │   load_resume(hh) + факты +     │
        │ browser.runtime                   │   qa_memory.prompt_block        │
┌───────▼──────────────────────┐   HTTPS    │                                 │
│ background.ts (event page)   ├───────────►│ ai/agent.py  HHAgent            │
│   auth (JWT из storage)      │            │   fill_form_fields()            │
│   вызовы API                 │            │   chat()                        │
└──────────────────────────────┘            └─────────────────────────────────┘
        ▲ подхват сессии
┌───────┴──────────────────────┐
│ otclick-sync.content.ts      │  читает sb-<ref>-auth-token на домене Otclick
└──────────────────────────────┘
```

### Поток автозаполнения

1. Пользователь открывает форму, жмёт иконку (или `Alt+Shift+O`) → панель.
2. `content.ts` собирает `snapshot()` по всем фреймам (`webNavigation.getAllFrames`)
   и текст страницы.
3. `deterministic-fill.ts` сразу заполняет паспортные поля (имя, email, телефон,
   ссылки) и прикрепляет PDF резюме в `input[type=file]` — без LLM.
4. Остальное уходит `POST /api/extension/fill`.
5. Бэкенд строит контекст кандидата, вызывает LLM, «снапит» ответы на реальные
   опции (select/radio/checkbox), пустые значения выбрасывает.
6. `applyFill()` проставляет значения, `marks.ts` подсвечивает заполненное.
7. Пользователь правит что нужно и **сам** жмёт «Отправить» в форме.
8. Правки (изменённые ответы) уходят `POST /api/extension/qa` → `qa_memory`.

### Поток чата

Вкладка «Чат»: история сообщений в `browser.storage.local` (ключ на пользователя).
Каждый запрос — `POST /api/extension/chat` с полной историей и, если включён
чекбокс «видеть эту страницу», текстом активной вкладки. Бэкенд подмешивает
контекст кандидата в системный промпт. Ответы не хранятся на сервере.

## Компоненты

### `ext/` — новый каталог в git

WXT-проект, `wxt build -b firefox`. Копируется из `extension/`, затем режется.

**Переносится:**

| Файл | Роль |
|---|---|
| `lib/snapshot.ts` | сбор полей + `FormFiller`; уже содержит ветки под Google Forms (`div[role=radio]`, `aria-labelledby`), MS Forms, shadow DOM, кросс-доменные iframes |
| `lib/marks.ts` | подсветка заполненных полей в странице |
| `lib/deterministic-fill.ts` | заполнение фактов и файла резюме без LLM |
| `lib/sidebar.ts` | панель; урезается до вкладок Автозаполнение / Чат / Настройки |
| `lib/api.ts` | переписывается под наши эндпоинты |
| `lib/auth.ts`, `lib/session-sync.ts` | Supabase-сессия |
| `lib/log.ts`, `lib/perf.ts`, `lib/theme-sync.ts` | утиль |
| `entrypoints/background.ts`, `content.ts`, `otclick-sync.content.ts` | оркестрация |

**Удаляется:** `linkedin-agent.ts`, `agent-api.ts`, `agent-log.ts`, `agent-search.ts`,
`agent-types.ts`, `ats-cache.ts`, `tailor-cache.ts`, `resume-text-cache.ts`,
ATS-ветки в `detect.ts`, блоки fit-score / ATS / tailor / квот / фидбэка в
`sidebar.ts`, каталоги `benchmark*/`, `store-assets/`.

**Правки под Firefox:**

- `chrome.*` → `browser` из `wxt/browser` (≈163 вызова, механическая замена).
- `browser_specific_settings.gecko.id` вместо Chrome-`key`; `minimum_chrome_version` убрать.
- `externally_connectable` не поддерживается в Firefox — вход идёт только через
  content script на домене Otclick (этот путь уже реализован).
- `host_permissions`: `https://docs.google.com/*`, `https://forms.gle/*`,
  `https://forms.yandex.ru/*`, `https://forms.yandex.kz/*`, `https://forms.office.com/*`;
  `<all_urls>` уходит в `optional_host_permissions` (в Firefox MV3 широкие
  разрешения иначе требуют ручной выдачи после установки).
- Background — event page, не service worker; проверить, что нет SW-специфики.

**Env расширения:** `VITE_API_BASE` (backend, по умолчанию `http://localhost:8000`),
`VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_APP_BASE` (`http://localhost:3000`).

### `backend/app/api/extension.py` — новый роутер

Все эндпоинты за существующим `deps.get_current_user`.

| Метод | Путь | Тело / ответ |
|---|---|---|
| GET | `/api/extension/context` | `{facts: {...}, has_resume_file: bool}` — факты для детерминированного заполнения |
| POST | `/api/extension/fill` | `{url, page_text, frames:[{frame_id, snapshot:[...]}]}` → `{frames:[{frame_id, fields:[...]}]}` |
| POST | `/api/extension/chat` | `{messages:[{role, content}], page_text?}` → `{answer}` |
| POST | `/api/extension/qa` | `{items:[{question, answer}]}` → `{saved: n}` |
| GET | `/api/extension/resume-file` | PDF-поток резюме с hh или 404 |

Поле `fields[]` повторяет существующий формат расширения:
`{frame_id, ref, selector, field_type, value, source, filename?, required?}`.
`source` — `profile` (вербатим-факт) либо `ai`.

Без SSE в v1: один JSON-ответ, в панели спиннер. Стрим добавляем, только если
ожидание реально мешает.

### `backend/app/services/candidate_context.py` — новый

Собирает строку контекста для LLM из того, что уже есть в проекте:
`form_filler.load_resume(user_id)` (полное тело резюме с hh, живой запрос),
`form_filler._resume_summary(resume)` (готовый текстовый рендер) и
`qa_memory.prompt_block(user_id)`. Порт `CandidateContext` из OtclickUS **не
нужен** — эти две функции покрывают его целиком.

Дополнительно отдаёт `facts(resume)` — словарь вербатим-фактов (ФИО, email,
телефон, город, ссылки) из `resume["contact"]` и корневых полей. Значение с
`source=profile`, не совпавшее ни с одним фактом, понижается до `ai` (защита от
выдумок в паспортных полях). Те же факты уходят в `GET /api/extension/context`
для детерминированного заполнения без LLM.

### `backend/app/ai/agent.py` — два новых метода на `HHAgent`

- `fill_form_fields(context, page_text, snapshot) -> list[dict]` — один вызов LLM
  со structured output; промпт и «снап» значения к реальной опции портируем из
  `app/services/llm/fill.py`. Поле без уверенного ответа **не заполняется** —
  тот же принцип, что в `services/form_filler.py` («Да» на «желаемый доход» хуже
  ручного ввода).
- `chat(context, messages, page_text=None) -> str` — ответ проходит через
  `prompts.sanitize_ai_text`.

Пустой `OPENAI_API_KEY` → `fill_form_fields` возвращает `[]`, `chat` — понятную
заглушку. Никаких падений (инвариант проекта).

### Миграций нет

Хранить тело резюме в БД не требуется: `load_resume` берёт его с hh по запросу,
`HHAgent` уже кэширует результат на время жизни объекта. Ссылка на PDF
(`download.pdf.url`) лежит в том же ответе. `qa_memory` тоже существует
(миграция 022). Схема БД не меняется.

PDF отдаётся отдельным маленьким сервисом `services/extension_resume.py`:
`ApiClient.request` всегда декодирует ответ как JSON, поэтому байты качаются
прямым `requests.get(url, headers={"Authorization": f"Bearer {access_token}"})`
в executor'е — токен берётся у того же `load_api_client`.

## Обработка ошибок

| Ситуация | Поведение |
|---|---|
| Нет/просрочен JWT | 401 → панель показывает «Войдите на Otclick» + кнопка открытия сайта |
| Нет резюме на hh | 200 с `has_resume_file=false`; заполняются только детерминированные поля, в панели явное сообщение |
| LLM недоступен / пустой ответ | Поля не трогаем, в панели причина; уже заполненное детерминированно остаётся |
| hh отдал 403 на резюме | `resume-file` → 404, поле файла остаётся пустым, уведомление в панели |
| Форма не распознана | Панель: «Полей не найдено», кнопка «Собрать заново» |

## Тестирование

- vitest в `ext/tests/` — переносим существующие тесты `snapshot`/`deterministic-fill`,
  плюс тест на «снап» ответа к опции.
- pytest в `backend/tests/test_extension_api.py` — роутер и `candidate_context`
  на моках Supabase (шаблон `_fluent` из `test_filters_service.py`).
- Ручной прогон на живой Google Form, Yandex Form и forms.office.com — критерий
  приёмки: заполнено ≥80% полей, ни одного выдуманного значения в паспортных полях.
- CI: `ext/` добавляется в `.github/workflows/ci.yml` (`tsc --noEmit` + `npm test`).

## Риски

1. **Резюме с hh может быть недоступно.** В памяти проекта есть запись, что hh
   закрыл публичное API соискателя 15.12.2025. При этом на нём же стоит весь
   рабочий `form_filler`, так что скорее всего живо. Первый шаг плана — живая
   проверка `GET /resumes/{id}` и `download.pdf.url`. Если закрыто: фолбэк —
   загрузка PDF в веб-кабинете + Supabase Storage bucket и одна миграция;
   интерфейс `candidate_context` не меняется, меняется только источник.
2. **Google Forms может поменять разметку.** Смягчается тем, что `snapshot.ts`
   опирается на ARIA-роли, а не на классы Google.
3. **Подписание расширения для Firefox.** Для распространения вне
   `about:debugging` нужен подписанный XPI через AMO. В объём v1 входит только
   сборка и загрузка как temporary add-on; публикация — отдельная задача.

## Критерии готовности

1. `cd ext && npm run build -b firefox` собирается без ошибок; add-on грузится в Firefox.
2. Вход в аккаунт — открыть Otclick в соседней вкладке, панель показывает email.
3. На всех трёх типах форм: заполнение работает, поля подсвечены, submit не нажимается.
4. Вкладка «Чат» отвечает с учётом резюме пользователя.
5. Правка ответа и «Сохранить» → запись видна в `qa_memory` веб-кабинета.
6. `pytest backend/tests` и `npm test` в `ext/` зелёные.
