-- Free-text relevance criteria the user attaches to a filter; injected into
-- the AI relevance prompt (both stages) so the LLM can drop vacancies the
-- snippets/description match poorly per the user's own rules.

alter table filters add column if not exists relevance_criteria text;
