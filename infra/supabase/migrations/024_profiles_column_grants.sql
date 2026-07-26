-- ============================================================
-- 024_profiles_column_grants.sql — close the plan-escalation hole.
--
-- `profiles_update_own` (001_init) is FOR UPDATE USING (auth.uid() = id) with
-- no column restriction, and PostgREST is browser-reachable through Kong. Any
-- logged-in user could PATCH /rest/v1/profiles with
-- {"plan":"active","plan_expires_at":"2099-01-01"} and grant themselves an
-- unlimited paid plan (plan.has_access reads exactly those columns). Same for
-- worker_enabled / agent_enabled / timezone (daily-limit reset by tz swap).
--
-- RLS WITH CHECK cannot see the OLD row, so the fix is column privileges:
-- drop blanket UPDATE for anon/authenticated and grant back only the two
-- columns the UI actually writes (see onboarding-modal.tsx). Everything else
-- on profiles is service_role-only, which bypasses RLS and grants alike.
-- Run AFTER 023_analytics.sql
-- ============================================================

REVOKE UPDATE ON public.profiles FROM anon, authenticated;
GRANT UPDATE (onboarded, timezone) ON public.profiles TO authenticated;

-- INSERT/DELETE on profiles is the auth trigger's job only.
REVOKE INSERT, DELETE ON public.profiles FROM anon, authenticated;

-- SECURITY DEFINER without a pinned search_path is a known privilege-escalation
-- vector (Supabase linter 0011). Same body as 007, plus the pin.
CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  INSERT INTO public.profiles (id, plan, trial_ends)
  VALUES (new.id, 'trial', now() + interval '7 days')
  ON CONFLICT (id) DO NOTHING;
  RETURN new;
END;
$$;
