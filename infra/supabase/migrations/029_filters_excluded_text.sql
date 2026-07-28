-- Drop the salary filter (hh defaults `salary` to RUR, so a KZT number silently
-- searched for ~4x the money) and replace the client-side excluded_regex with
-- hh's native `excluded_text` (comma-separated words, filtered server-side).

alter table filters add column if not exists excluded_text text;
alter table filters drop column if exists excluded_regex;
alter table filters drop column if exists salary_min;
