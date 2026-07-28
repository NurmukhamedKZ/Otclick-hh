-- Search precision + hh param migration.
--   search_field — where `text` is matched. Default `name`: matching the
--     description too is what made "AI" pull in every vacancy that merely
--     mentions AI.
--   period — days of publication depth. Default 30: without it every producer
--     run re-scans the whole archive (up to 20 pages per filter).
--   work_format / employment_form — hh deprecated `schedule` / `employment`.
-- Existing rows are backfilled, not left on the old wide-open behaviour.

alter table filters add column if not exists search_field text default 'name';
alter table filters add column if not exists period int default 30;
alter table filters add column if not exists work_format text;
alter table filters add column if not exists employment_form text;

update filters set search_field = 'name' where search_field is null;
update filters set period = 30 where period is null;

update filters set work_format = case schedule
  when 'remote' then 'REMOTE'
  when 'fullDay' then 'ON_SITE'
  when 'flyInFlyOut' then 'FIELD_WORK'
  else null
end where schedule is not null and work_format is null;

update filters set employment_form = case employment
  when 'full' then 'FULL'
  when 'part' then 'PART'
  when 'project' then 'PROJECT'
  else null
end where employment is not null and employment_form is null;

alter table filters drop column if exists schedule;
alter table filters drop column if exists employment;
