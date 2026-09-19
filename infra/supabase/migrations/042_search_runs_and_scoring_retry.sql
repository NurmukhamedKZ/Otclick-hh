-- ============================================================
-- 041_search_runs_and_scoring_retry.sql
-- Durable manual discovery/scoring runs + retry metadata for transient HH
-- failures. API requests enqueue work; the standalone worker claims it.
-- ============================================================

ALTER TABLE vacancy_pipeline
  ADD COLUMN IF NOT EXISTS score_attempts integer NOT NULL DEFAULT 0 CHECK (score_attempts >= 0),
  ADD COLUMN IF NOT EXISTS next_score_at timestamptz,
  ADD COLUMN IF NOT EXISTS last_score_error text;

CREATE INDEX IF NOT EXISTS idx_vacancy_pipeline_scoring_due
  ON vacancy_pipeline (user_id, next_score_at, discovered_at DESC)
  WHERE status = 'discovered';

CREATE TABLE IF NOT EXISTS search_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  status text NOT NULL DEFAULT 'queued' CHECK (
    status IN (
      'queued', 'discovery', 'scoring',
      'completed', 'completed_with_errors', 'failed'
    )
  ),
  discovery jsonb,
  scoring jsonb,
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  finished_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (discovery IS NULL OR jsonb_typeof(discovery) = 'object'),
  CHECK (scoring IS NULL OR jsonb_typeof(scoring) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_search_runs_user_created
  ON search_runs (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_search_runs_status_created
  ON search_runs (status, created_at);

-- A double-click or a second browser tab must not create two concurrent HH
-- discovery/scoring cycles for the same account.
CREATE UNIQUE INDEX IF NOT EXISTS uq_search_runs_user_active
  ON search_runs (user_id)
  WHERE status IN ('queued', 'discovery', 'scoring');

ALTER TABLE search_runs ENABLE ROW LEVEL SECURITY;
-- No anon/authenticated policy: backend service-role only.

CREATE OR REPLACE FUNCTION claim_next_search_run()
RETURNS SETOF search_runs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  -- A hard worker/container crash can leave a claimed run active forever and
  -- the per-user unique index would then block every future manual run. The
  -- normal batch is capped at 15 vacancies; two hours is deliberately much
  -- longer than the expected cycle and acts only as crash recovery.
  UPDATE search_runs
  SET
    status = 'failed',
    error = 'worker lease expired after 2 hours',
    finished_at = now(),
    updated_at = now()
  WHERE status IN ('discovery', 'scoring')
    AND updated_at < now() - interval '2 hours';

  RETURN QUERY
  WITH candidate AS (
    SELECT id
    FROM search_runs
    WHERE status = 'queued'
    ORDER BY created_at
    FOR UPDATE SKIP LOCKED
    LIMIT 1
  )
  UPDATE search_runs AS run
  SET
    status = 'discovery',
    started_at = COALESCE(run.started_at, now()),
    error = NULL,
    updated_at = now()
  FROM candidate
  WHERE run.id = candidate.id
  RETURNING run.*;
END;
$$;

REVOKE ALL ON FUNCTION claim_next_search_run() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION claim_next_search_run() TO service_role;
