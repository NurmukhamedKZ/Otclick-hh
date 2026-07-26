-- ============================================================
-- 023_analytics.sql — funnel analytics.
--   applications.hh_state / hh_state_at / hh_viewed: negotiation state pulled
--     from hh (response|invitation|discard) — the only honest source for
--     "invited to interview". hh_state_at = when WE noticed the change.
--   applications.filter_id / employer_name: attribution for the breakdowns.
--   profiles.negotiations_synced_at: throttle for the on-demand state sync.
--   analytics_summary(user_id, days): one round trip, all metrics as jsonb.
-- Run AFTER 022_qa_memory.sql
-- ============================================================

ALTER TABLE applications
  ADD COLUMN IF NOT EXISTS hh_state text,
  ADD COLUMN IF NOT EXISTS hh_state_at timestamptz,
  ADD COLUMN IF NOT EXISTS hh_viewed bool,
  ADD COLUMN IF NOT EXISTS employer_name text,
  ADD COLUMN IF NOT EXISTS filter_id uuid REFERENCES filters(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_applications_user_hh_state
  ON applications (user_id, hh_state);
CREATE INDEX IF NOT EXISTS idx_applications_user_filter
  ON applications (user_id, filter_id);

ALTER TABLE profiles
  ADD COLUMN IF NOT EXISTS negotiations_synced_at timestamptz;

-- ─── analytics_summary ────────────────────────────────────────
-- Everything the /analytics page needs. Rates are 0..1 numerics, null when
-- the denominator is 0 (the UI renders "—" rather than a fake 0%).
CREATE OR REPLACE FUNCTION analytics_summary(p_user_id uuid, p_days int DEFAULT 30)
RETURNS jsonb
LANGUAGE sql
STABLE
AS $$
WITH win AS (
  SELECT a.*
  FROM applications a
  WHERE a.user_id = p_user_id
    AND a.created_at >= now() - make_interval(days => p_days)
),
-- a real apply attempt (form_required/failed/captcha never reached hh)
att AS (
  SELECT w.*,
         (w.hh_state = 'invitation')                       AS invited,
         (w.hh_state = 'discard')                           AS discarded,
         (w.hh_state IN ('invitation', 'discard')
          OR EXISTS (SELECT 1 FROM recruiter_chats rc
                     WHERE rc.user_id = p_user_id
                       AND rc.vacancy_id = w.vacancy_id
                       AND rc.last_handled_message_id IS NOT NULL)) AS replied,
         (w.cover_letter IS NOT NULL AND w.cover_letter <> '')      AS with_letter
  FROM win w
  WHERE w.status IN ('sent', 'form_sent')
),
tot AS (
  SELECT count(*)::int                                          AS sent,
         count(*) FILTER (WHERE hh_viewed)::int                 AS viewed,
         count(*) FILTER (WHERE replied)::int                   AS replied,
         count(*) FILTER (WHERE invited)::int                   AS invited,
         count(*) FILTER (WHERE discarded)::int                 AS discarded
  FROM att
),
rel AS (
  SELECT count(*)::int                                    AS checked,
         count(*) FILTER (WHERE relevant)::int            AS kept
  FROM relevance_cache
  WHERE user_id = p_user_id
    AND created_at >= now() - make_interval(days => p_days)
),
react AS (
  SELECT percentile_cont(0.5) WITHIN GROUP (
           ORDER BY extract(epoch FROM (hh_state_at - applied_at)) / 3600.0
         ) AS median_hours
  FROM att
  WHERE applied_at IS NOT NULL
    AND hh_state_at IS NOT NULL
    AND hh_state IN ('invitation', 'discard')
    AND hh_state_at > applied_at
),
stuck AS (
  SELECT (SELECT count(*) FROM form_drafts
          WHERE user_id = p_user_id AND status = 'pending')::int      AS forms,
         (SELECT count(*) FROM captcha_requests
          WHERE user_id = p_user_id AND NOT solved)::int              AS captchas,
         (SELECT count(*) FROM recruiter_drafts
          WHERE user_id = p_user_id AND status = 'pending')::int      AS drafts
),
by_filter AS (
  SELECT a.filter_id,
         coalesce(f.name, f.text, 'без фильтра')            AS name,
         count(*)::int                                      AS sent,
         count(*) FILTER (WHERE a.replied)::int             AS replied,
         count(*) FILTER (WHERE a.invited)::int             AS invited
  FROM att a
  LEFT JOIN filters f ON f.id = a.filter_id
  GROUP BY a.filter_id, coalesce(f.name, f.text, 'без фильтра')
),
by_resume AS (
  SELECT a.resume_id,
         coalesce(r.title, 'без резюме')                    AS title,
         count(*)::int                                      AS sent,
         count(*) FILTER (WHERE a.replied)::int             AS replied,
         count(*) FILTER (WHERE a.invited)::int             AS invited
  FROM att a
  LEFT JOIN resumes r ON r.id = a.resume_id
  GROUP BY a.resume_id, coalesce(r.title, 'без резюме')
),
by_letter AS (
  SELECT with_letter,
         count(*)::int                                      AS sent,
         count(*) FILTER (WHERE replied)::int               AS replied,
         count(*) FILTER (WHERE invited)::int               AS invited
  FROM att
  GROUP BY with_letter
),
failures AS (
  SELECT status, count(*)::int AS count
  FROM win
  WHERE status NOT IN ('sent', 'form_sent')
  GROUP BY status
),
silent AS (
  SELECT employer_id,
         max(employer_name)   AS employer_name,
         count(*)::int        AS sent
  FROM att
  WHERE NOT replied AND employer_id IS NOT NULL
  GROUP BY employer_id
  HAVING count(*) >= 3
),
daily AS (
  SELECT (coalesce(applied_at, created_at))::date          AS day,
         count(*)::int                                     AS sent,
         count(*) FILTER (WHERE invited)::int              AS invited
  FROM att
  GROUP BY 1
)
SELECT jsonb_build_object(
  'days', p_days,
  'funnel', jsonb_build_object(
    'ai_checked',  (SELECT checked FROM rel),
    'ai_kept',     (SELECT kept FROM rel),
    'sent',        (SELECT sent FROM tot),
    'viewed',      (SELECT viewed FROM tot),
    'replied',     (SELECT replied FROM tot),
    'invited',     (SELECT invited FROM tot),
    'discarded',   (SELECT discarded FROM tot),
    'waiting',     (SELECT sent - replied FROM tot)
  ),
  'kpi', jsonb_build_object(
    'view_rate',    (SELECT CASE WHEN sent > 0 THEN round(viewed::numeric / sent, 4) END FROM tot),
    'reply_rate',   (SELECT CASE WHEN sent > 0 THEN round(replied::numeric / sent, 4) END FROM tot),
    'invite_rate',  (SELECT CASE WHEN sent > 0 THEN round(invited::numeric / sent, 4) END FROM tot),
    'discard_rate', (SELECT CASE WHEN sent > 0 THEN round(discarded::numeric / sent, 4) END FROM tot),
    'median_reaction_hours', (SELECT round(median_hours::numeric, 1) FROM react),
    'stuck_forms',   (SELECT forms FROM stuck),
    'stuck_captcha', (SELECT captchas FROM stuck),
    'stuck_drafts',  (SELECT drafts FROM stuck)
  ),
  'ai_filter', jsonb_build_object(
    'checked',   (SELECT checked FROM rel),
    'kept',      (SELECT kept FROM rel),
    'dropped',   (SELECT checked - kept FROM rel),
    'drop_rate', (SELECT CASE WHEN checked > 0 THEN round((checked - kept)::numeric / checked, 4) END FROM rel)
  ),
  'by_filter', coalesce((
    SELECT jsonb_agg(jsonb_build_object(
      'filter_id', filter_id, 'name', name, 'sent', sent,
      'replied', replied, 'invited', invited,
      'reply_rate', CASE WHEN sent > 0 THEN round(replied::numeric / sent, 4) END,
      'invite_rate', CASE WHEN sent > 0 THEN round(invited::numeric / sent, 4) END
    ) ORDER BY sent DESC) FROM by_filter), '[]'::jsonb),
  'by_resume', coalesce((
    SELECT jsonb_agg(jsonb_build_object(
      'resume_id', resume_id, 'title', title, 'sent', sent,
      'replied', replied, 'invited', invited,
      'reply_rate', CASE WHEN sent > 0 THEN round(replied::numeric / sent, 4) END,
      'invite_rate', CASE WHEN sent > 0 THEN round(invited::numeric / sent, 4) END
    ) ORDER BY sent DESC) FROM by_resume), '[]'::jsonb),
  'by_letter', coalesce((
    SELECT jsonb_agg(jsonb_build_object(
      'with_letter', with_letter, 'sent', sent,
      'replied', replied, 'invited', invited,
      'reply_rate', CASE WHEN sent > 0 THEN round(replied::numeric / sent, 4) END,
      'invite_rate', CASE WHEN sent > 0 THEN round(invited::numeric / sent, 4) END
    ) ORDER BY with_letter DESC) FROM by_letter), '[]'::jsonb),
  'failures', coalesce((
    SELECT jsonb_agg(jsonb_build_object('status', status, 'count', count)
                     ORDER BY count DESC) FROM failures), '[]'::jsonb),
  'silent_employers', coalesce((
    SELECT jsonb_agg(jsonb_build_object(
      'employer_id', employer_id, 'employer_name', employer_name, 'sent', sent
    ) ORDER BY sent DESC) FROM (SELECT * FROM silent ORDER BY sent DESC LIMIT 8) s), '[]'::jsonb),
  'daily', coalesce((
    SELECT jsonb_agg(jsonb_build_object('date', day, 'sent', sent, 'invited', invited)
                     ORDER BY day) FROM daily), '[]'::jsonb)
);
$$;

-- Called with the service_role key only (the API resolves user_id from the JWT).
REVOKE ALL ON FUNCTION analytics_summary(uuid, int) FROM PUBLIC;
REVOKE ALL ON FUNCTION analytics_summary(uuid, int) FROM anon, authenticated;
