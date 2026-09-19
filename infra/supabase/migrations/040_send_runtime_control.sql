-- ============================================================
-- 039_send_runtime_control.sql
-- Persistent per-user sender batches, controls and single-account DB lease.
-- This does NOT activate the sender in worker_main.
-- ============================================================

CREATE TABLE IF NOT EXISTS application_send_batches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  status text NOT NULL DEFAULT 'running' CHECK (
    status IN ('running', 'paused', 'completed')
  ),
  total_jobs integer NOT NULL DEFAULT 0 CHECK (total_jobs >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_application_send_batches_user_status
  ON application_send_batches (user_id, status, created_at DESC);

ALTER TABLE application_send_batches ENABLE ROW LEVEL SECURITY;
-- No anon/authenticated policy: backend service-role only.

ALTER TABLE application_send_queue
  ADD COLUMN IF NOT EXISTS batch_id uuid REFERENCES application_send_batches(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_application_send_queue_batch_status
  ON application_send_queue (batch_id, status, queued_at);

CREATE TABLE IF NOT EXISTS application_send_control (
  user_id uuid PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE,
  desired_state text NOT NULL DEFAULT 'paused' CHECK (
    desired_state IN ('paused', 'running', 'stop_after_current')
  ),
  active_batch_id uuid REFERENCES application_send_batches(id) ON DELETE SET NULL,
  safety_interval_seconds integer NOT NULL DEFAULT 10 CHECK (
    safety_interval_seconds BETWEEN 0 AND 300
  ),
  lease_owner text,
  lease_expires_at timestamptz,
  last_cycle_at timestamptz,
  last_outcome text,
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE application_send_control ENABLE ROW LEVEL SECURITY;
-- No anon/authenticated policy: backend service-role only.

CREATE OR REPLACE FUNCTION acquire_application_send_lease(
  p_user_id uuid,
  p_owner text,
  p_ttl_seconds integer DEFAULT 120
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  affected bigint := 0;
BEGIN
  IF p_owner IS NULL OR btrim(p_owner) = '' THEN
    RAISE EXCEPTION 'lease owner is required';
  END IF;
  IF p_ttl_seconds < 10 OR p_ttl_seconds > 900 THEN
    RAISE EXCEPTION 'lease ttl must be between 10 and 900 seconds';
  END IF;

  INSERT INTO application_send_control (user_id)
  VALUES (p_user_id)
  ON CONFLICT (user_id) DO NOTHING;

  UPDATE application_send_control
  SET
    lease_owner = p_owner,
    lease_expires_at = now() + make_interval(secs => p_ttl_seconds),
    updated_at = now()
  WHERE user_id = p_user_id
    AND desired_state = 'running'
    AND active_batch_id IS NOT NULL
    AND (
      lease_expires_at IS NULL
      OR lease_expires_at <= now()
      OR lease_owner = p_owner
    )
    AND (
      last_cycle_at IS NULL
      OR last_cycle_at + make_interval(secs => safety_interval_seconds) <= now()
    );

  GET DIAGNOSTICS affected = ROW_COUNT;
  RETURN affected > 0;
END;
$$;

CREATE OR REPLACE FUNCTION release_application_send_lease(
  p_user_id uuid,
  p_owner text,
  p_outcome text DEFAULT NULL
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  affected bigint := 0;
BEGIN
  UPDATE application_send_control
  SET
    lease_owner = NULL,
    lease_expires_at = NULL,
    last_cycle_at = now(),
    last_outcome = left(p_outcome, 200),
    desired_state = CASE
      WHEN desired_state = 'stop_after_current' THEN 'paused'
      ELSE desired_state
    END,
    updated_at = now()
  WHERE user_id = p_user_id
    AND lease_owner = p_owner;

  GET DIAGNOSTICS affected = ROW_COUNT;
  RETURN affected > 0;
END;
$$;
