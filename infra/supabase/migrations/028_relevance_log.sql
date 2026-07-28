-- 028_relevance_log.sql
-- AI relevance filter: off by default for new filters + keep vacancy titles
-- so the UI can show what was kept and what was dropped.

alter table filters alter column ai_filter_enabled set default false;

alter table relevance_cache add column if not exists vacancy_name text;
alter table relevance_cache add column if not exists employer_name text;

create index if not exists relevance_cache_user_recent
  on relevance_cache (user_id, created_at desc);
