-- ============================================================
-- 035_candidate_context.sql — structured candidate positioning + facts.
-- Prepared data is curated from the approved source markdown files; there is
-- intentionally no generic markdown parser in the application.
-- ============================================================

CREATE TABLE IF NOT EXISTS candidate_profiles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  source_name text NOT NULL,
  data jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id),
  CHECK (jsonb_typeof(data) = 'object')
);

CREATE TABLE IF NOT EXISTS candidate_facts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  fact_key text NOT NULL,
  category text NOT NULL,
  title text NOT NULL,
  statement text NOT NULL,
  metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
  tags jsonb NOT NULL DEFAULT '[]'::jsonb,
  source_name text NOT NULL,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, fact_key),
  CHECK (jsonb_typeof(metrics) = 'object'),
  CHECK (jsonb_typeof(tags) = 'array')
);

CREATE INDEX IF NOT EXISTS idx_candidate_facts_user_active_category
  ON candidate_facts (user_id, active, category);

ALTER TABLE candidate_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE candidate_facts ENABLE ROW LEVEL SECURITY;
