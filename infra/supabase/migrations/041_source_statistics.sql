-- Cumulative per-source funnel statistics.
-- Kept separate from the discovery cursor so scoring/discovery can update
-- counters concurrently without overwriting cursor/head state.

ALTER TABLE vacancy_search_sources
  ADD COLUMN IF NOT EXISTS stats jsonb NOT NULL DEFAULT '{"new":0,"duplicate":0,"hard_filtered":0,"score_error":0}'::jsonb;

CREATE OR REPLACE FUNCTION increment_vacancy_source_stats(
  p_source_ids uuid[],
  p_new integer DEFAULT 0,
  p_duplicate integer DEFAULT 0,
  p_hard_filtered integer DEFAULT 0,
  p_score_error integer DEFAULT 0
)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  UPDATE vacancy_search_sources
  SET stats = jsonb_build_object(
        'new', GREATEST(0, COALESCE((stats->>'new')::integer, 0) + p_new),
        'duplicate', GREATEST(0, COALESCE((stats->>'duplicate')::integer, 0) + p_duplicate),
        'hard_filtered', GREATEST(0, COALESCE((stats->>'hard_filtered')::integer, 0) + p_hard_filtered),
        'score_error', GREATEST(0, COALESCE((stats->>'score_error')::integer, 0) + p_score_error)
      ),
      updated_at = now()
  WHERE id = ANY(p_source_ids);
$$;
