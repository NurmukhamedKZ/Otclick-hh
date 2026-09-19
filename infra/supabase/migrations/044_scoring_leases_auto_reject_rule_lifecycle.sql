-- ============================================================
-- 043_scoring_leases_auto_reject_rule_lifecycle.sql
-- Recoverable vacancy scoring claims, explainable automatic rejects and
-- version-preserving selection-rule lifecycle.
-- ============================================================

ALTER TABLE vacancy_pipeline
  DROP CONSTRAINT IF EXISTS vacancy_pipeline_status_check;

ALTER TABLE vacancy_pipeline
  ADD CONSTRAINT vacancy_pipeline_status_check CHECK (
    status IN (
      'discovered', 'scoring', 'scored', 'review', 'selected',
      'letter_draft', 'approved', 'queued_to_send', 'sending', 'sent',
      'rejected_by_user', 'rejected_by_rule', 'hold', 'archived',
      'score_error', 'send_error'
    )
  );

ALTER TABLE vacancy_pipeline
  ADD COLUMN IF NOT EXISTS score_claim_token uuid,
  ADD COLUMN IF NOT EXISTS score_claimed_at timestamptz,
  ADD COLUMN IF NOT EXISTS score_lease_expires_at timestamptz,
  ADD COLUMN IF NOT EXISTS score_lease_failures integer NOT NULL DEFAULT 0
    CHECK (score_lease_failures >= 0),
  ADD COLUMN IF NOT EXISTS auto_reject_details jsonb;

ALTER TABLE vacancy_pipeline
  DROP CONSTRAINT IF EXISTS vacancy_pipeline_auto_reject_details_check;
ALTER TABLE vacancy_pipeline
  ADD CONSTRAINT vacancy_pipeline_auto_reject_details_check CHECK (
    auto_reject_details IS NULL OR jsonb_typeof(auto_reject_details) = 'array'
  );

CREATE INDEX IF NOT EXISTS idx_vacancy_pipeline_scoring_lease
  ON vacancy_pipeline (score_lease_expires_at)
  WHERE status = 'scoring';

-- Recover orphaned in-flight scoring rows. The third lease expiry becomes a
-- visible score_error instead of looping forever. Legacy stuck rows from before
-- this migration have no lease; updated_at is used as their lease clock.
CREATE OR REPLACE FUNCTION reap_expired_vacancy_scoring()
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  changed_count integer;
BEGIN
  WITH expired AS (
    SELECT id, score_lease_failures
    FROM vacancy_pipeline
    WHERE status = 'scoring'
      AND (
        score_lease_expires_at < now()
        OR (
          score_lease_expires_at IS NULL
          AND updated_at < now() - interval '10 minutes'
        )
      )
    FOR UPDATE SKIP LOCKED
  ), recovered AS (
    UPDATE vacancy_pipeline AS v
    SET
      status = CASE WHEN e.score_lease_failures >= 2 THEN 'score_error' ELSE 'discovered' END,
      score = CASE WHEN e.score_lease_failures >= 2 THEN NULL ELSE v.score END,
      score_details = CASE
        WHEN e.score_lease_failures >= 2
          THEN jsonb_build_object('error', 'scoring lease expired repeatedly', 'lease_expired', true)
        ELSE v.score_details
      END,
      score_explanation = CASE
        WHEN e.score_lease_failures >= 2 THEN 'scoring lease expired repeatedly'
        ELSE v.score_explanation
      END,
      last_score_error = 'scoring lease expired',
      next_score_at = CASE WHEN e.score_lease_failures >= 2 THEN NULL ELSE now() END,
      score_lease_failures = e.score_lease_failures + 1,
      score_claim_token = NULL,
      score_claimed_at = NULL,
      score_lease_expires_at = NULL,
      updated_at = now()
    FROM expired e
    WHERE v.id = e.id
    RETURNING v.id
  )
  SELECT count(*) INTO changed_count FROM recovered;

  RETURN changed_count;
END;
$$;

REVOKE ALL ON FUNCTION reap_expired_vacancy_scoring() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION reap_expired_vacancy_scoring() TO service_role;

ALTER TABLE vacancy_selection_rules
  ADD COLUMN IF NOT EXISTS deleted_at timestamptz,
  ADD COLUMN IF NOT EXISTS superseded_by_rule_id uuid REFERENCES vacancy_selection_rules(id) ON DELETE SET NULL;

ALTER TABLE vacancy_rule_proposals
  ADD COLUMN IF NOT EXISTS source_rule_id uuid REFERENCES vacancy_selection_rules(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_vacancy_selection_rules_user_deleted
  ON vacancy_selection_rules (user_id, deleted_at, version DESC);
