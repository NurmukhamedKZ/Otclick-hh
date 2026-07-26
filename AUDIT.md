# Otclick — аудит production-readiness

Дата: 2026-07-27 · Ветка: `nureke` · Коммит: `1ecd013`

Что проверено: весь `backend/app` (API, worker, services, hh-клиент, AI), `infra/supabase/migrations/*`,
`docker-compose.yml` + Dockerfile'ы, `frontend/src` (роутинг, auth, хуки, страницы), `.env.example`, README/CLAUDE.md.

Базовое состояние на момент аудита: `pytest` — 275 passed, `ruff check backend` — чисто,
`tsc --noEmit` — чисто. То есть проблемы ниже — это не «сломанная сборка», а дыры, которые тесты не покрывают.

> **Статус:** блокеры 1, 3, 4 и весь раздел «Высокий приоритет» — **исправлены** (помечены ✅ ниже),
> регрессии закрыты в `backend/tests/test_hardening.py`. После правок: **294 passed**, ruff и tsc чисты.
> Миграция `024_profiles_column_grants.sql` применена к локальному стенду и проверена вручную
> (эскалация плана из роли `authenticated` → `permission denied`, запись `onboarded` работает).
> Контейнеры `api`/`worker` крутят запечённый код — нужен `docker compose build api && docker compose up -d api worker`.
> Не тронуты: блокеры **2** (TestMode/сумма в вебхуке) и **5** (отмена подписки у CloudPayments),
> средний приоритет и раздел с расхождениями документации.

---

## 🔴 Блокеры (нельзя пускать в прод)

### 1. ✅ RLS-политика `profiles` позволяет пользователю выдать себе платный план
`infra/supabase/migrations/001_init.sql:155-157`

```sql
CREATE POLICY "profiles_update_own" ON profiles
  FOR UPDATE USING (auth.uid() = id);
```

Нет `WITH CHECK`, нет ограничения по колонкам. PostgREST проброшен в браузер через Kong (`/rest/v1`,
`infra/supabase/kong.yml:56-66`), а `frontend` уже ходит в таблицы напрямую с anon-ключом.
Любой залогиненный пользователь может выполнить:

```
PATCH /rest/v1/profiles?id=eq.<свой uuid>
{"plan":"active","plan_expires_at":"2099-01-01T00:00:00Z"}
```

и получить бессрочный доступ. `plan.has_access` читает ровно эти поля, `require_active_plan` и
`worker_main.filter_accessible` пропустят. Биллинг обходится полностью. Туда же —
`worker_enabled` / `agent_enabled` / `timezone` (обход лимитов через подмену таймзоны).

**Фикс:** отдельная политика только на разрешённые колонки (`onboarded`, `timezone`) либо
`WITH CHECK` + триггер, запрещающий менять `plan`, `trial_ends`, `plan_expires_at`,
`cp_subscription_id`, `worker_enabled`, `agent_enabled` из роли `authenticated`. Все биллинг-поля
должен писать только `service_role`.

### 2. Вебхук CloudPayments активирует план на тестовых платежах и на неизвестных суммах
`backend/app/services/billing.py:70-118`

- Не проверяется `TestMode` — тестовый платёж (сумма может быть любой) активирует реальный план.
- Не проверяется `Status`/`Currency`.
- `_period_end` при неизвестной сумме молча выдаёт **дефолтный месячный план на 30 дней**
  (`_plan_for_amount(amount) or PLANS[DEFAULT_PLAN_ID]`). Оплата 1 ₽ → месяц доступа.

**Фикс:** отклонять (`{"code": 0}` без активации) при `TestMode=1`, при `Currency != PLAN_CURRENCY`
и при сумме, не совпадающей ни с одним планом; логировать как аномалию.

### 3. ✅ `/health` всегда 200 — контейнер «здоров» при мёртвой БД
`backend/app/main.py:35-43`

`db_ok=False` возвращается в теле, но статус остаётся 200. Healthcheck в
`docker-compose.yml` (`curl -fsS /health`) считает контейнер живым, `worker` стартует по
`depends_on: api: service_healthy`, оркестратор никогда не перезапустит API.

**Фикс:** `raise HTTPException(503)` при `db_ok=False`.

### 4. ✅ Нет никакого rate-limit; `/api/hh/connect` поднимает Chromium по запросу
`backend/app/api/auth.py:160-179`, `backend/app/services/hh_auth.py:63-81`

Каждый POST `/api/hh/connect` создаёт headless Chromium (`shm_size` у `api` не задан, только у
`worker`). Ограничений на количество параллельных задач на пользователя нет, глобальных — тоже нет.
Один авторизованный аккаунт кладёт API-контейнер десятком запросов. Плюс:

- `_jobs` — модульный dict, **никогда не чистится** (утечка памяти) и живёт в памяти одного процесса:
  при 2+ репликах/воркерах uvicorn поллинг `GET /api/hh/connect/{job_id}` будет ловить случайные 404.
- `asyncio.create_task(...)` без сохранения ссылки (`hh_auth.py:66,81`) — задача может быть собрана
  GC на середине OAuth-флоу (известная ловушка asyncio).

**Фикс:** семафор на конкурентные connect-джобы + TTL-очистка `_jobs`, хранить ссылки на таски,
задокументировать, что API должен работать в один процесс (или вынести джобы в БД/Redis).

### 5. Отмена подписки ничего не отменяет у провайдера
`backend/app/services/billing.py:170-188`

`cancel()` только ставит `plan='cancelled'` локально. Виджет запущен в **recurrent**-режиме
(`subscribe_params` → `interval`/`period`), значит CloudPayments продолжит списывать деньги.
Пользователь нажал «Отменить», доступ кончился, списания идут. Это чарджбэки и претензии,
а не техдолг. В коде это честно помечено как «MVP, вручную через саппорт» — но так нельзя
открывать публичный биллинг.

**Фикс:** дернуть CP Subscriptions API (`/subscriptions/cancel`) по `profiles.cp_subscription_id`;
пока не сделано — отключить recurrent у виджета и продавать разовые периоды.

---

## 🟠 Высокий приоритет

### 6. ✅ Producer крутит поиск hh каждые 10 секунд в холостую
`backend/app/worker/runner.py:39,234-253`, `backend/app/services/vacancy_producer.py:20`

В установившемся режиме (все вакансии уже отработаны) `produce_jobs` возвращает `pushed=0`,
раннер спит `IDLE_REFILL_SLEEP_S = 10` и идёт снова. Каждый прогон — до
`MAX_PAGES_PER_FILTER=20` страниц **на каждый включённый фильтр**. Это непрерывный шквал
`GET /vacancies` в hh на каждого активного пользователя. Прямая дорога к бану аккаунта и
к тому самому анти-фроду, ради обхода которого сделан Playwright.

**Фикс:** экспоненциальный backoff при `pushed==0` (10s → 1 мин → 5 мин → 15 мин), сбрасывать
при непустом результате. Заодно ограничить глубину пагинации при пустом урожае.

### 7. ✅ Recruiter-агент дублирует историю в каждом опросе — растущий контекст и утечка памяти
`backend/app/ai/agent.py:132-139,202-217`, `backend/app/worker/recruiter_poll.py:137-146`

Агент создаётся с `InMemorySaver()` (чекпойнтер держит состояние по `thread_id = negotiation_id`),
но `_run_recruiter` при каждом вызове передаёт **всю историю чата заново**. LangGraph дописывает
входящие сообщения к уже сохранённому состоянию → на каждом цикле опроса история удваивается.
Последствия: рост стоимости токенов на каждый цикл и `InMemorySaver`, который никогда не
очищается за всё время жизни процесса-воркера (то есть недели).

**Фикс:** либо передавать только новое сообщение (чекпойнтер уже хранит контекст), либо убрать
чекпойнтер и всегда передавать историю. Сейчас включены оба механизма сразу.

### 8. ✅ Веб-сессия hh (куки) никогда не обновляется и её протухание не детектится
`backend/app/services/form_filler.py:39-70`, `backend/app/services/chatik.py:128-140`

Куки снимаются один раз при OAuth-логине (`hh/authorize.py`) и хранятся вечно. Когда они протухнут:
- `chatik.recent_chats` вернёт `None` → в лог `warning`, агент молча перестаёт отвечать рекрутёрам;
- `prepare_form_answers` вернёт `form_required` → тесты вакансий перестают решаться.

Пользователю никто ничего не сообщает, в UI всё «работает». Это тихая деградация двух ключевых фич.

**Фикс:** различать «нет сессии» и «сессия отвергнута hh» (редирект на логин / 403), при втором —
`notify(user_id, "token_dead"/"reconnect_required")` и баннер в UI.

### 9. ✅ Опрос состояний переговоров — до 1500 записей каждые 2 минуты на пользователя
`backend/app/worker/recruiter_poll.py:32-60`, `runner.py:45`

`_negotiation_states` каждые `RECRUITER_POLL_INTERVAL_S=120` секунд тянет до 15 страниц по 100
переговоров — и всё это только чтобы узнать, какие чаты в статусе «отказ». Плюс `chatik._chat_items`
до 15 страниц. Плюс `chatik.chat_messages` **заново расшифровывает куки и строит новую
`requests.Session` на каждый чат** (`chatik.py:143-157`) — N+1 по Fernet + TCP.

**Фикс:** кэшировать состояния переговоров (TTL ~30 мин), передавать одну `Session` через все
чаты одного опроса, поднять интервал.

### 10. ✅ Новый `ApiClient` (и новое TCP-соединение) на каждый вызов hh
`backend/app/services/hh_credentials.py:91-95`

`load_api_client` на каждый вызов: SELECT в Supabase + 2 Fernet-decrypt + новая `requests.Session`.
Вызывается в `apply_one`, `produce_jobs`, `form_filler`, `chatik`, `recruiter`, `_probe_me`,
`negotiation_sync`, во всех API-ручках `/api/chats`. Никакого пула, никакого keep-alive.

**Фикс:** кэш клиентов на пользователя внутри раннера (у раннера уже есть `HHAgent` с таким же
жизненным циклом).

### 11. ✅ `assert` в HTTP-клиенте — падение на валидных данных и отключаемая валидация
`backend/app/hh/client.py:81,129,243`

```python
assert method in AllowedMethods.__args__
assert 300 > response.status_code >= 200
assert self.access_token.startswith("USER")
```

- `assert` вырезается под `python -O` → «валидация» исчезает молча.
- `access_token.startswith("USER")` — жёсткое предположение о формате токена hh. Если hh поменяет
  префикс (или вернёт токен другого типа), весь апплай упадёт с голым `AssertionError`, который
  наверху превратится в `status="failed"` без внятной диагностики.

**Фикс:** заменить на явные `raise ValueError/ApiError`; проверку префикса — убрать или свести к
`logger.warning`.

### 12. ✅ `deps.get_current_user` ходит в сеть на каждом запросе и течёт деталями наружу
`backend/app/api/deps.py:12-31`

`anon_client.auth.get_user(token)` — HTTP-запрос в GoTrue на **каждый** вызов любого эндпоинта.
`worker-bar` фронта опрашивает `/api/worker/status` каждые 5 секунд, дашборд — ещё три запроса
каждые 15 с. При 100 активных вкладках это сотни запросов в GoTrue в минуту только на аутентификацию.
Плюс `detail=f"invalid token: {ex}"` возвращает внутреннее сообщение исключения клиенту.

**Фикс:** локально валидировать JWT (HS256 по `JWT_SECRET`) или закэшировать результат на TTL токена;
в `detail` отдавать статичное «invalid token».

---

## 🟡 Средний приоритет — логика и корректность

### 13. `_already_applied` для `form_required` — мёртвый код
`backend/app/services/apply.py:98-111` vs `vacancy_producer.py:37-47`

`apply._already_applied` специально пропускает строки со статусом `form_required`, «чтобы дать
переоценить позже». Но producer (`_existing_vacancy_ids`) отсекает вакансию по **самому факту**
наличия строки в `applications`, без учёта статуса. Вакансия никогда не вернётся в очередь.
Либо чинить producer, либо убрать ветку в `apply`.

### 14. Опечатка в `State` — `"runningы"` (кириллическая «ы»)
`backend/app/worker/runner.py:36`

```python
State = Literal["runningы", "paused_captcha", "paused_limit", "stopped"]
```

Присваивается везде `"running"` — то есть тип-аннотация не описывает ни одно реальное значение.
Для рантайма безвредно (Literal не проверяется), но mypy/pyright это молча пропускает,
потому что типизация здесь и так не гоняется в CI. Симптом отсутствия статической проверки.

### 15. `resume_sync` удаляет резюме → фильтры молча обнуляются, воркер перестаёт работать
`backend/app/services/resume_sync.py:37-66` + миграция `021_filters_resume_set_null.sql`

При реконнекте другого hh-аккаунта старые резюме удаляются, `filters.resume_id` становится `NULL`
(`ON DELETE SET NULL`), а `_load_enabled_filters` отбрасывает фильтры без `resume_id`. Воркер
формально «запущен», но не делает ничего. В логе только `warning`, пользователю — ничего.

**Фикс:** при обнулении `resume_id` выключать фильтр (`enabled=false`) и слать уведомление.

### 16. Гонка в счётчике лимитов (read-modify-write)
`backend/app/worker/limiter.py:68-75`

`_increment_sync` = SELECT count → +1 → UPSERT. Сейчас раннер на пользователя один, поэтому
не стреляет, но любая горизонтальная масштабируемость воркера сломает дневной лимит.

**Фикс:** атомарный инкремент через RPC/`ON CONFLICT DO UPDATE SET count = apply_counters.count + 1`.

### 17. Heartbeat не обновляется во время долгого сна
`backend/app/worker/runner.py:294-308`

При `status == "limit_day"` состояние ставится `paused_limit`, но `_hb()` не вызывается перед
`asyncio.sleep(sleep_s)` (может быть до 24 часов), и после пробуждения `handle.state = "running"`
тоже не отправляется в БД. UI до следующего события показывает устаревшее состояние.

### 18. `form_drafts.approve` сохраняет Q&A ещё до успешной отправки
`backend/app/services/form_drafts.py:110-125`

`qa_memory.save_edited` вызывается до `submit_prepared_form`. Если отправка провалилась, правки
всё равно ушли в «подтверждённые ответы кандидата» и будут подставляться во все будущие промпты.
Мелочь, но эта таблица объявлена «приоритетным источником правды».

### 19. `_mirror_application` теряет атрибуцию аналитики
`backend/app/services/form_drafts.py:156-168`

Upsert по `(user_id, vacancy_id)` не выставляет `filter_id` / `employer_name`. Отклики, ушедшие
через одобрение формы, попадают в аналитику как «без фильтра». Данные в
`analytics_summary.by_filter` перекошены.

### 20. Сравнение internal-токена не константное по времени
`backend/app/api/internal.py:18-24`

`x_internal_token != expected` — обычное сравнение строк. `hmac.compare_digest` стоит одну строчку.

### 21. `notifications` растут без ограничений
`backend/app/services/notifications.py` + миграция 001

Каждый успешный отклик, каждое написанное письмо — строка в `notifications` (до 100/день/пользователь).
Ни TTL, ни архивации, ни партиционирования. Таблица в Realtime-публикации, `REPLICA IDENTITY`
у неё дефолтный, но у `applications` — `FULL` (миграция 005), то есть каждый UPDATE прокачивает
через WAL всю строку целиком вместе с `cover_letter` и `form_answers`.

---

## 🟡 Инфраструктура и эксплуатация

### 22. Нет CI
Каталога `.github/` нет. 275 тестов, ruff и tsc проходят локально — но ничто не мешает
влить PR, который их ломает. Для публичного репозитория с внешними контрибьюторами это первое,
что нужно завести.

### 23. Миграции применяются руками, без таблицы версий
`infra/supabase/init/zz2-run-app-migrations.sh` прогоняет весь каталог **только на пустом томе**.
На существующей БД новую миграцию надо применять `psql` вручную (описано в CLAUDE.md).
Нет `schema_migrations`, нет проверки «что уже применено», нет отката. `007_trial_plan.sql`
содержит `UPDATE ... SET trial_ends = created_at + interval '7 days'` — при повторном прогоне
переоткроет триалы. Для self-hosted-проекта, который позиционируется как «одна команда развернул»,
это главная эксплуатационная мина.

**Фикс:** любой минимальный раннер миграций (`sqlx`/`dbmate`/самописный на 20 строк с таблицей
`applied_migrations`), запускаемый на старте `api`.

### 24. `handle_new_user` — `SECURITY DEFINER` без `SET search_path`
`001_init.sql:6-14`, переопределяется в `007`. Классическая рекомендация Supabase-адвайзора:
добавить `SET search_path = public, pg_temp`.

### 25. `.env.example` рассинхронизирован с `config.py`
`backend/.env.example`

- `OPENAI_BASE_URL=https://api.openai.com/v1/chat/completions` — **неверно**. `langchain_openai`
  ждёт базовый URL (`/v1`), с этим значением все AI-вызовы отвалятся 404. В `config.py` дефолт
  правильный, но копирующий пример контрибьютор получит сломанный AI.
- `PLAN_PRICE` / `PLAN_NAME` / `PLAN_INTERVAL` / `PLAN_PERIOD` — мертвы, цены захардкожены в
  `config.PLANS`. Правка `.env` не даст ничего.
- `OPENAI_MODEL=gpt-4o-mini` против `gpt-5.4-nano` в коде.
- `LANGSMITH_TRACING=true` **по умолчанию** — то есть при копировании примера резюме, переписка
  с рекрутёрами и ответы на тесты уходят в LangSmith. Для проекта с заявленным «privacy-first»
  это должно быть `false` с явным комментарием.
- Нет `SUPABASE_PUBLIC_URL` пояснения для не-локальных деплоев, нет `LOG_LEVEL`, `DEBUG_ENDPOINTS`,
  `OPENAI_RATE_LIMIT` описан, а `CORS_ORIGINS` для прода — нет.
- `HH_LOGIN` / `HH_PASSWORD` в примере — приглашение положить реальный пароль в файл.

### 26. Два разных `.env` без объяснения
`docker-compose.yml` для `api`/`worker` читает `backend/.env`, а `${...}`-подстановки
(`POSTGRES_PASSWORD`, `JWT_SECRET`, `ANON_KEY`, `NEXT_PUBLIC_*`) compose берёт из **корневого** `.env`.
Пример один — `backend/.env.example`. Развернуть с первого раза по README не получится.

### 27. Публичный репозиторий содержит извлечённые ключи Android-приложения hh
`backend/app/hh/client_keys.py` — `ANDROID_CLIENT_ID` / `ANDROID_CLIENT_SECRET` официального
клиента hh.ru. Это не наша уязвимость (наследие `hh-applicant-tool`), но для публичного MIT-репо
это юридический риск и повод для блокировки: hh может отозвать ключи в любой момент, и продукт
перестанет работать у всех пользователей сразу. Как минимум — вынести в конфиг с явным
дисклеймером, чтобы не быть точкой отказа.

### 28. Мусор в репозитории
- `frontend/Otclick/` — дизайн-макет на JSX (`app.jsx`, `screens.jsx`, `uploads/*.jpg`), закоммичен,
  не собирается, не используется.
- `backend/recon_chat.py`, `backend/scripts/smoke_cover_letter.py` — исследовательские скрипты.
- `worker_control.enabled_active_user_ids()` (`services/worker_control.py:66`) — мёртвая функция,
  `worker_main` использует `active_user_flags`. При этом на неё до сих пор ссылается CLAUDE.md.

---

## 🔵 Документация расходится с кодом

CLAUDE.md — основной онбординг-документ, и он врёт в нескольких местах:

1. **«Producer пре-записывает `has_test` вакансии как `form_required`»** — этого кода нет.
   `vacancy_producer.py:178-181` прямо говорит обратное: has_test-вакансии идут в очередь.
2. **«Tools: `send_message_recruiter` (reply on hh — POSTed via legacy messages API)»** — такого
   инструмента нет. В `ai/recruiter_tools.py` три тула, и `answer_recruiter_question` → `do_answer`
   **никогда не отправляет в hh**, всегда пишет черновик (`recruiter_tools.py:58-78`).
   То есть заявленная фича «AI сам отвечает рекрутёрам» на деле — «AI готовит черновик».
   Это либо баг (регрессия), либо осознанное решение, которое не отражено в документации и README.
3. **«worker_main polls `worker_control.enabled_active_user_ids`»** — использует `active_user_flags`.
4. Список ручек в CLAUDE.md не содержит `api/qa.py`.

Разберитесь, что из этого — устаревший текст, а что — потерянная функциональность (пункт 2
выглядит именно как второе).

---

## 🔵 Мелочи и полировка

- `frontend/src/lib/supabase/middleware.ts` содержит редиректы для `/login`, `/signup`, `/filters`
  и список «защищённых» путей, в котором **нет** `/chats`, `/todo`, `/analytics`. Дыры нет —
  `(app)/layout.tsx` делает серверную проверку `getUser()` и редиректит, — но список надо
  либо дополнить, либо выкинуть как дублирующий.
- `api/captcha.py`: `{request_id}` в пути принимается и полностью игнорируется, сервис работает
  «на пользователя». Ручка `/dismiss` вдобавок останавливает воркер целиком — неочевидно из названия.
- `api/worker.py:/start` возвращает `state="running"` немедленно, хотя реальный раннер поднимется
  только на следующем цикле `worker_main` (до 15 с). UI показывает «работает» раньше времени.
- `services/analytics.py`: при падении RPC возвращается пустая структура — на графике будут нули,
  неотличимые от «нет данных». Стоит отдавать флаг ошибки.
- `hh/client.py:114` — `response.json() if response.text else {}`: пустой ответ и валидный `null`
  неразличимы.
- `services/recruiter.list_drafts` делает последовательный бэкфилл `question_text` через hh API
  **на каждый запрос списка** — при 20 старых черновиках это 20 последовательных вызовов hh
  внутри HTTP-запроса пользователя. Разовая миграция была бы честнее.
- `worker/throttle.py`: `SessionCluster` перерыв 1–2 часа срабатывает **после** проверки лимитов
  и **до** взятия задачи — во время перерыва heartbeat не пишется, UI показывает «работает».
- `services/form_filler.py:283-294` — фолбэк свободного ответа на вопрос теста — строка `"Да"`.
  На вопрос «Укажите желаемый доход» уйдёт «Да». Лучше не отправлять форму вообще.
- Нет обработки `429` от hh нигде в `hh/errors.py`-маппинге раннера (`_is_transient` ловит только
  5xx и сетевые).
- `docker-compose.yml`: у `api` нет `shm_size`, хотя Playwright запускается именно там.
- Нет структурного логирования и request-id; в проде разбирать инцидент по этим логам тяжело.

---

## Что сделано

| # | Проблема | Как закрыто |
|---|----------|-------------|
| 1 | Самовыдача платного плана через RLS | `024_profiles_column_grants.sql`: `REVOKE UPDATE/INSERT/DELETE ON profiles` у `anon`/`authenticated`, `GRANT UPDATE (onboarded, timezone)` обратно. Плюс `SET search_path` у `handle_new_user`. |
| 3 | `/health` врёт при мёртвой БД | `main.py` → `HTTPException(503)`. |
| 4 | Chromium по запросу, вечный `_jobs` | `hh_auth._admit` — 1 джоба на пользователя + `MAX_CONCURRENT_JOBS=4`, иначе 429; `_finish`/`_purge_finished` с TTL 10 мин; таск держится в `JobState.task`. |
| 6 | Producer долбит hh каждые 10 с | Экспоненциальный backoff 10 с → 15 мин, сброс при непустом урожае. |
| 7 | Дублирование истории у агента | Убран `InMemorySaver` — историю передаёт вызывающий, состояние не копится. |
| 8 | Тихая смерть веб-сессии hh | `WebSessionExpired` + `session_looks_dead` в `form_filler`/`chatik`, `report_dead_session` → `notify_once("web_session_expired")` + баннер в UI; реконнект/disconnect сбрасывают кэш и «взводят» уведомление обратно. |
| 9 | 1500 переговоров каждые 2 мин | Кэш состояний на 30 мин (`recruiter_poll._states_cache`). |
| 10 | Новый `ApiClient` на каждый вызов | Кэш на 60 с + `drop_cached_client` из `mark_invalid`/`disconnect`/реконнекта. Веб-сессия кэшируется на 30 мин — это же убрало N+1 в chatik. |
| 11 | `assert` в HTTP-клиенте | Заменены на `ValueError`/`BadResponse`; префикс токена — `warning`, а не падение. |
| 12 | Проверка JWT по сети на каждый запрос | Кэш проверенных токенов на 60 с по SHA-256 ключу; `detail` больше не отдаёт внутренности исключения. |

Регрессии: `backend/tests/test_hardening.py` (19 тестов) + `backend/tests/conftest.py` чистит
process-local кэши между тестами.

## Что осталось (по порядку)

1. Блокер **2** — проверки `TestMode`/`Currency`/суммы в вебхуке CloudPayments.
2. Блокер **5** — реальная отмена подписки через CP Subscriptions API (или отказ от recurrent).
3. CI (#22) и раннер миграций (#23) — без них всё остальное будет отъезжать обратно.
4. Разобраться с пунктом «AI отвечает рекрутёрам» (раздел расхождений, п. 2) — понять,
   фича потеряна или намеренно переведена в режим черновиков, и привести README в соответствие.
