-- ============================================================
-- 034_captcha_solution.sql — real captcha solving, worker's web session.
-- POST /api/captcha/{id}/solve now writes the user's typed answer here
-- instead of just marking the row solved; the worker (a separate process —
-- no in-memory channel reaches it from the API) polls for it and types it
-- into the live Playwright session holding the account's cookies.
-- ============================================================

ALTER TABLE captcha_requests ADD COLUMN IF NOT EXISTS solution text;