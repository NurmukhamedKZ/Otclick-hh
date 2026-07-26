-- ============================================================
-- 025_atomic_counters_and_retention.sql
--   increment_apply_counter(): the daily cap was a read-modify-write in Python
--     (SELECT count → +1 → UPSERT). One runner per user hides it today, but any
--     second writer silently loses increments and the 100/day cap stops holding.
--   prune_notifications(): every successful apply writes a notifications row
--     (up to 100/user/day) and nothing ever deleted them.
-- Run AFTER 024_profiles_column_grants.sql
-- ============================================================

CREATE OR REPLACE FUNCTION increment_apply_counter(p_user_id uuid, p_date date)
RETURNS int
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  INSERT INTO apply_counters (user_id, date, count)
  VALUES (p_user_id, p_date, 1)
  ON CONFLICT (user_id, date)
  DO UPDATE SET count = apply_counters.count + 1
  RETURNING count;
$$;

REVOKE ALL ON FUNCTION increment_apply_counter(uuid, date) FROM PUBLIC;
REVOKE ALL ON FUNCTION increment_apply_counter(uuid, date) FROM anon, authenticated;

-- Read notifications are dropped sooner than unread ones; the UI never paginates
-- past a couple of weeks anyway.
CREATE OR REPLACE FUNCTION prune_notifications(p_read_days int DEFAULT 14,
                                               p_keep_days int DEFAULT 90)
RETURNS int
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  removed int;
BEGIN
  DELETE FROM notifications
  WHERE created_at < now() - make_interval(days => p_keep_days)
     OR (read AND created_at < now() - make_interval(days => p_read_days));
  GET DIAGNOSTICS removed = ROW_COUNT;
  RETURN removed;
END;
$$;

REVOKE ALL ON FUNCTION prune_notifications(int, int) FROM PUBLIC;
REVOKE ALL ON FUNCTION prune_notifications(int, int) FROM anon, authenticated;

CREATE INDEX IF NOT EXISTS idx_notifications_created
  ON notifications (created_at);
