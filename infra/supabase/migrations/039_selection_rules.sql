-- ============================================================
-- 038_selection_rules.sql — user-approved rules learned from review decisions.
-- LLM may propose a rule, but only explicit approval can create an active rule.
-- ============================================================

CREATE TABLE IF NOT EXISTS vacancy_rule_proposals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  source_vacancy_id uuid REFERENCES vacancy_pipeline(id) ON DELETE SET NULL,
  source_reason text NOT NULL,
  decision text NOT NULL CHECK (decision IN ('rule', 'change', 'no_generalization')),
  proposed_rule jsonb,
  explanation text,
  impact_preview jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
  created_at timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (proposed_rule IS NULL OR jsonb_typeof(proposed_rule) = 'object'),
  CHECK (jsonb_typeof(impact_preview) = 'object'),
  CHECK ((decision = 'no_generalization' AND proposed_rule IS NULL) OR decision <> 'no_generalization')
);

CREATE INDEX IF NOT EXISTS idx_vacancy_rule_proposals_user_status
  ON vacancy_rule_proposals (user_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS vacancy_selection_rules (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  proposal_id uuid REFERENCES vacancy_rule_proposals(id) ON DELETE SET NULL,
  version integer NOT NULL CHECK (version > 0),
  name text NOT NULL,
  action text NOT NULL CHECK (action IN ('hard_reject', 'scoring_preference')),
  match jsonb NOT NULL,
  instruction text NOT NULL,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (jsonb_typeof(match) = 'object'),
  UNIQUE (user_id, version)
);

CREATE INDEX IF NOT EXISTS idx_vacancy_selection_rules_user_active
  ON vacancy_selection_rules (user_id, active, version);

ALTER TABLE vacancy_rule_proposals ENABLE ROW LEVEL SECURITY;
ALTER TABLE vacancy_selection_rules ENABLE ROW LEVEL SECURITY;
