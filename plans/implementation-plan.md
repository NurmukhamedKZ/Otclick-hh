# Otclick-hh — план реализации персонального приложения откликов

Обновлено: 2026-09-07

## Текущий статус

Ветка: `feature/persistent-vacancy-funnel`  
Draft PR: `#1`  
Реальная отправка HH: **выключена** (`ALLOW_REAL_APPLY=false`).  
`persistent_sender` реализован, но **не импортируется и не запускается `worker_main`**.

Целевой поток:

`HH web-session -> Search Sources -> persistent vacancy_pipeline -> enrichment -> hard filter -> LLM score -> mobile review -> cover draft -> exact-text approval -> persistent send queue -> controlled HH submit/reconcile`

Главный принцип: discovery/scoring и send физически разделены. Старый сценарий `нашёл -> ApplyJob -> сразу отправил` не является целевым runtime.

---

# 0. Safety и validation baseline

- [x] Feature branch + draft PR.
- [x] `ALLOW_REAL_APPLY=false` по умолчанию.
- [x] Kill-switch стоит в `form_filler.submit_response` до HH session/network submit.
- [x] `submit_prepared_form` проходит через тот же gate.
- [x] `worker_main` не запускает legacy apply runner (`want_apply=False`).
- [x] Persistent sender при disabled flag завершается до sender-control, queue, cookies и HH access.
- [x] Exact-text approval связан SHA-256 с сохранённым draft.
- [x] Edit after approval сбрасывает approval/hash.
- [x] Активный send-job блокирует редактирование письма.
- [x] Safety tests: disabled flag / snapshot mismatch / exact text / already responded / manual form / lease denied.
- [ ] Полный выполняющийся CI baseline.

## GitHub Actions blocker

- [x] Workflow содержит `workflow_dispatch`, `push: main`, `push: feature/**`, `pull_request`.
- [x] В workflow есть backend pytest/ruff, frontend/ext typecheck/tests/build, installer static checks.
- [x] Проверен feature push — `0 workflow_runs`.
- [x] Проверен `pull_request: reopened` — `0 workflow_runs`.
- [x] Workflow присутствует в `main`.
- [x] Через текущий GitHub connector можно fetch/rerun существующие runs, но нельзя создать первый dispatch или включить Actions.
- [x] Локальный clone в доступной среде упирается в `Could not resolve host: github.com`.
- [ ] Включить/проверить Actions в настройках репозитория либо выполнить первый run другим credential/tool.
- [ ] После появления run исправить все реальные pytest/tsc/build ошибки до green.

**До закрытия CI baseline ветку не считать production-ready.**

---

# 1. Данные кандидата

Источник истины:
- `01_Карьерное_позиционирование_CIO_CDTO(1).md`;
- `02_RFL_банк_достижений_и_фактов(1).md`.

- [x] `candidate_profile.json` с актуальным карьерным позиционированием.
- [x] `confirmed_facts.json`: ровно 22 подтверждённых facts/cases.
- [x] Claim guardrails отделены от достижений.
- [x] Не подтверждённые пункты не импортируются как facts.
- [x] `035_candidate_context.sql`: `candidate_profiles` + `candidate_facts`.
- [x] Deterministic loader без универсального Markdown parser.
- [x] Удалённые prepared facts при reload деактивируются.
- [x] Profile/facts/guardrails реально используются scorer.
- [x] Relevant facts/guardrails используются cover writer; `fact_key` сохраняются.
- [x] Read-only `/api/candidate-context`.
- [x] Mobile `/vacancies/profile`: roles, positioning, scale, industries, compensation, guardrails, active facts.
- [ ] Редактирование candidate context из UI — только после первой калибровки, если будет полезно.

---

# 2. Persistent vacancy funnel

- [x] `034_vacancy_pipeline.sql`.
- [x] `vacancy_pipeline`, unique `(user_id, hh_vacancy_id)`.
- [x] `vacancy_pipeline_sources` many-to-many.
- [x] Lifecycle: discovered/scoring/scored/review/selected/letter_draft/approved/queued_to_send/sending/sent/rejected_by_user/hold/archived/score_error/send_error.
- [x] Discovery обновляет snapshot без сброса ручного решения.
- [x] Conditional lifecycle transitions защищают concurrent update.
- [x] Discovery пишет напрямую в PostgreSQL, а не in-memory ApplyJob queue.
- [x] Full vacancy enrichment через authenticated HH cookies.
- [x] Enrichment выполняется перед scoring.
- [x] Removed/archived HH vacancy -> archived.
- [ ] Restart/recovery integration test с реальной PostgreSQL/Supabase stack.
- [ ] После live-калибровки удалить/заархивировать неиспользуемый legacy `vacancy_producer.py` / старую in-memory queue.

---

# 3. Источники вакансий

## 3.1 HH Search URL

- [x] Parser hh.ru / regional `*.hh.ru` / hh.kz.
- [x] Query params хранятся ordered pairs; повторные параметры не теряются.
- [x] Неизвестные параметры сохраняются.
- [x] Backend preview + CRUD `/api/search-sources`.
- [x] URL change сбрасывает cursor.
- [x] Mobile `/vacancies/sources`: preview/save/enable-disable/delete/status/error.
- [x] Manual `/api/search-sources/run-now`: discovery + scoring без sender.
- [x] Mobile `/vacancies/run`: ручной запуск и summary discovery/scoring.
- [x] Повторный manual click во время активного manual run -> 409.

## 3.2 Incremental discovery

- [x] Первый run: максимум 3 страницы.
- [x] Принудительный `publication_time`.
- [x] Cursor хранит previous head vacancy IDs.
- [x] Следующий run идёт до overlap.
- [x] Emergency cap 20 pages.
- [x] DB dedup между источниками.
- [x] Старые `applications` не возвращаются в новый backlog.
- [x] Cadence discovery = 5 минут.
- [ ] Cumulative source statistics: new / duplicate / hard-filtered / score-error.

## 3.3 HH автопоиски — web-session, без Bearer

Решение пользователя: реализовать, live contract проверить после нескольких циклов разработки.

- [x] Applicant cookies открывают `GET /applicant/autosearch.xml`.
- [x] Applicant Bearer/API не является зависимостью новой архитектуры.
- [x] `api.hh.ru/saved_searches/vacancies` не используется как основа MVP.
- [ ] На заполненном аккаунте снять read-only DOM/data-qa + inline state contract.
- [ ] Если данные client-side — снять фактический read-only internal XHR/fetch.
- [ ] Подтвердить минимум `name + search criteria`, желательно stable id/new_count.
- [ ] Импортировать как `hh_autosearch` Search Source.
- [ ] Unchanged criteria сохраняют cursor, changed criteria сбрасывают cursor.
- [ ] Исчезнувший HH autosearch не удаляет локальный source автоматически.
- [ ] Runtime после импорта использует наш cursor, HH `new_count` только справочный.

Manual Search URL остаётся гарантированным fallback.

## 3.4 Recommendations

- [ ] Опционально исследовать authenticated recommendations web flow после основного MVP.
- [ ] Нестабильный источник не включать.

**Не реализуем:** subscriptions отдельных компаний.

---

# 4. Hard filter + LLM scoring

- [x] Conservative hard-filter только явных role mismatches.
- [x] Mixed/ambiguous strategic roles проходят в LLM.
- [x] Unknown industry/revenue/salary != reject.
- [x] Structured score 0–100.
- [x] Components: role fit / scale / transformation mandate / industry-business context.
- [x] pros / risks / unknowns / confidence.
- [x] CIO transformation vs operations IT head.
- [x] CTO platform/product vs lead developer.
- [x] standalone business vs diversified holding logic.
- [x] LLM failure -> `score_error`, never fail-open.
- [x] Approved user rules участвуют в hard filter/scoring.
- [x] Pending/rejected proposals scorer не видит.

---

# 5. Mobile review

- [x] `/api/vacancies`: list/get/filter/pagination.
- [x] Source attribution.
- [x] Select / reject with reason / hold / return to review.
- [x] Terminal/send states защищены от обычного review click.
- [x] `/vacancies` mobile cards + responsive desktop view.
- [x] Company / title / salary / score / source / status.
- [x] Full vacancy + score explanation + pros/risks/unknowns/confidence.
- [x] Lifecycle tabs.
- [x] Candidate context page в том же разделе.
- [ ] Bulk select из review — после первого ручного прогона.
- [ ] Desktop table mode — только если card mode окажется неудобным.

---

# 6. Сопроводительные письма

- [x] Draft создаётся после user selection, не на discovery.
- [x] Письмо создаётся для каждой selected vacancy.
- [x] Контекст: selected resume + full vacancy + confirmed facts + guardrails + score anchors.
- [x] Numeric score не используется как аргумент в письме.
- [x] 500–750 символов, язык вакансии, 1–2 релевантных evidence.
- [x] Только подтверждённые facts; неизвестные `fact_key` блокируют draft.
- [x] Нет generic/template fallback.
- [x] Mobile edit/regenerate.
- [x] Exact-text approval SHA-256.
- [x] Edit after approval -> `letter_draft` + approval cleared.

---

# 7. Persistent send queue и runtime control

- [x] `037_send_queue.sql`: durable queue, не `asyncio.Queue`.
- [x] Queue принимает только approved exact-text snapshot.
- [x] Idempotency per pipeline vacancy; cancelled job можно requeue.
- [x] Mobile approve -> queue -> cancel.
- [x] Sender проверяет hash/resume/vacancy snapshot перед HH.
- [x] Pre-submit alive/archived/already-responded reconciliation.
- [x] `already_responded` -> sent без duplicate submit.
- [x] HH tests/forms -> manual_required, без auto-answer submit.
- [x] Uncertain submit -> HH reconciliation before failure.
- [x] Нет blind retry.
- [x] `039_send_runtime_control.sql`: durable batches + per-user control + DB lease.
- [x] Resume создаёт snapshot batch только из уже queued jobs.
- [x] Jobs, queued после Resume, ждут следующий batch.
- [x] DB lease ограничивает sender одним процессом на user/HH account.
- [x] Sender выбирает job только текущего active batch.
- [x] Lease освобождается после каждого outcome; stale lease после expiry не считается active.
- [x] Pause сохраняет batch.
- [x] Stop-after-current ждёт только реально `sending` job, иначе сразу pause.
- [x] Progress: N/M/current + queued/sent/failed/manual/cancelled.
- [x] Safety interval 0–300 sec, default 10.
- [x] Mobile `/vacancies/send`: state/progress/interval/Resume/Pause/Stop-after-current.
- [x] `runtime_wired=false` явно виден в UI.
- [x] Failed/manual_required reset: job -> cancelled, vacancy -> approved; автоматического retry нет.
- [x] Mobile список failed/manual jobs + `вернуть в approved`.
- [x] Bulk `/api/send-queue/bulk` только для уже individually approved vacancies.
- [x] Mobile `/vacancies/bulk`: checkboxes + bulk queue; batch operation не делает approval.
- [x] Unit tests: kill-switch/lease/batch/progress/pause/resume/stop/reset/bulk.
- [x] Engine **не подключён к `worker_main`**.

Перед реальной активацией:
- [ ] Full integration/restart test на PostgreSQL/Supabase stack.
- [ ] Bulk select из review + последующий индивидуальный cover approval.
- [ ] Ограниченный live send test на явно выбранной вакансии.
- [ ] Отдельное решение пользователя на включение sender в `worker_main`.

---

# 8. Накопление правил

- [x] `user_decision_reason` сохраняется.
- [x] LLM предлагает `rule` / `change` / `no_generalization`.
- [x] LLM не активирует правило сам.
- [x] До approval показывается deterministic impact preview.
- [x] Approved rule получает version.
- [x] Active rule можно disable/enable.
- [x] Selective rescore — отдельное действие пользователя.
- [x] Старые selected/approved/queued/hold/rejected/sent решения автоматически не меняются.
- [x] Employer response/rejection не считается preference signal пользователя.
- [x] Mobile `/vacancies/rules` + `/vacancies/rules/manage`.

---

# 9. Context/version fingerprints

- [x] Candidate hash.
- [x] Active-rules hash.
- [x] Vacancy content hash.
- [x] Resume hash.
- [x] Score-anchor hash.
- [x] Scorer model + prompt version входят в score fingerprint.
- [x] Writer model + prompt version входят в cover fingerprint.
- [x] `score_stale` / `cover_stale` advisory, lifecycle не меняют.
- [x] Missing context не ломает backlog — stale state unknown.
- [ ] После калибровки: bulk `пересчитать устаревшие` / `перегенерировать устаревшие`.

---

# 10. HH authentication: web-session first

- [x] Playwright login сохраняет encrypted HH cookies.
- [x] Если OAuth token exchange не сработал, cookies-only connection сохраняется как successful.
- [x] `connected=true` определяется valid web-session, не Bearer.
- [x] Status API возвращает `has_api_token`.
- [x] `/api/hh/refresh` для cookies-only = `not_applicable`.
- [x] Account UI показывает `web-session / cookies`; refresh token доступен только при реальном token.
- [x] Discovery/enrichment/send используют web-session path.

---

# 11. Single-user install / update

- [x] Root `install.sh` для Ubuntu 24.04.
- [x] Docker/Compose prerequisites.
- [x] Clone/update публичного `gest0r1/Otclick-hh`.
- [x] Secrets создаются только при отсутствии `.env`; update не использует `--force`.
- [x] Existing `.env` сохраняется.
- [x] `DISABLE_SIGNUP=true` по умолчанию и принудительно installer’ом.
- [x] First user создаётся GoTrue admin endpoint; public signup не нужен.
- [x] Installer сохраняет UUID/email, но не сгенерированный пароль.
- [x] После first user грузятся candidate profile + 22 facts.
- [x] Backend image включает prepared data/scripts.
- [x] Caddy — единая browser origin.
- [x] API/Kong/frontend host ports bind только `127.0.0.1`; наружу 80/443 Caddy.
- [x] `OTCLICK_DOMAIN` -> Caddy automatic HTTPS.
- [x] Без domain возможен временный HTTP/IP с warning.
- [x] Migrations — отдельный one-shot service.
- [x] Health checks backend/frontend/Auth.
- [x] Update: PostgreSQL backup до git fetch/pull.
- [x] Update: timestamped `.env` backup.
- [x] Install/update log `/var/log/otclick-hh`.
- [x] Rollback procedure `infra/ROLLBACK.md`.
- [x] Static installer safety regression tests.
- [x] Login UI single-user; регистрации нет.
- [ ] Live clean Ubuntu 24.04 install test.
- [ ] Live update test на заполненной БД.
- [ ] После merge проверить one-command installer из `main`.

Production-команда после merge:

```bash
curl -fsSL https://raw.githubusercontent.com/gest0r1/Otclick-hh/main/install.sh -o /tmp/otclick-install.sh && sudo bash /tmp/otclick-install.sh
```

С доменом:

```bash
OTCLICK_DOMAIN=jobs.example.com sudo -E bash /tmp/otclick-install.sh
```

---

# 12. Калибровка 20–30 вакансий

- [ ] Проверить реальные Search URL sources через `/vacancies/run`.
- [ ] Снять filled `/applicant/autosearch.xml` contract и закончить autosearch import.
- [ ] Hard-filter precision.
- [ ] Score vs фактические решения пользователя.
- [ ] Rejection reason -> rule proposals.
- [ ] 20–30 cover drafts.
- [ ] Mobile UX.
- [ ] Restart/recovery/idempotency.
- [ ] Только после отдельного решения — ограниченный real-send test.

---

# 13. Auto mode — отдельным решением после калибровки

Не входит в обязательный MVP.

- [ ] minimum score;
- [ ] allowed hard conditions;
- [ ] daily limit;
- [ ] max consecutive errors;
- [ ] kill switch;
- [ ] forms/unknown fields manual;
- [ ] explicit enable/disable UI.

---

## Ближайший порядок работ

1. Получить выполняющийся CI или эквивалентный full local build/test baseline.
2. Проверить installer на чистой Ubuntu 24.04 и повторный update с backup/migrations.
3. Начать первую ручную калибровку через Search URL + `/vacancies/run`, без real sends.
4. Когда пользователь сможет проверить HH аккаунт — снять filled `/applicant/autosearch.xml` contract и закончить web-session autosearch import.
5. После 20–30 вакансий откалибровать rules/scorer/cover prompts и решить, нужен ли bulk select из review.
6. Sender activation и auto mode — только по отдельному решению пользователя.
