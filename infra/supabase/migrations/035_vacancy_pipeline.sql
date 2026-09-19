-- ============================================================
-- 034_vacancy_pipeline.sql — persistent discovery/review funnel.
-- Search/scoring must persist here; asyncio.Queue is no longer allowed to be
-- the source of truth. One HH vacancy is stored once per user and can be linked
-- to multiple search sources.
-- ============================================================

CREATE TABLE IF NOT EXISTS vacancy_search_sources (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  resume_id uuid REFERENCES resumes(id) ON DELETE SET NULL,
  name text NOT NULL,
  source_type text NOT NULL CHECK (
    source_type IN ('search_url', 'hh_autosearch', 'recommendations')
  ),
  raw_url text,
  -- Array of {"key": ..., "value": ...}. An object is intentionally NOT used:
  -- HH search URLs may repeat area/search_field/professional_role parameters.
  query_pairs jsonb NOT NULL DEFAULT '[]'::jsonb,
  -- Opaque ingestion cursor. Current implementation may keep publication time,
  -- last vacancy id, or source-specific state without another migration.
  cursor jsonb NOT NULL DEFAULT '{}'::jsonb,
  enabled boolean NOT NULL DEFAULT true,
  last_checked_at timestamptz,
  last_success_at timestamptz,
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (jsonb_typeof(query_pairs) = 'array'),
  CHECK (jsonb_typeof(cursor) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_vacancy_search_sources_user_enabled
  ON vacancy_search_sources (user_id, enabled);

CREATE TABLE IF NOT EXISTS vacancy_pipeline (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  resume_id uuid REFERENCES resumes(id) ON DELETE SET NULL,
  hh_vacancy_id text NOT NULL,
  vacancy_url text,
  title text NOT NULL DEFAULT '',
  employer_id text,
  employer_name text,
  area_name text,
  salary jsonb,
  published_at timestamptz,
  discovered_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  description text,
  raw_vacancy jsonb,

  status text NOT NULL DEFAULT 'discovered' CHECK (
    status IN (
      'discovered', 'scoring', 'scored', 'review', 'selected',
      'letter_draft', 'approved', 'queued_to_send', 'sending', 'sent',
      'rejected_by_user', 'hold', 'archived', 'score_error', 'send_error'
    )
  ),
  score smallint CHECK (score BETWEEN 0 AND 100),
  score_details jsonb,
  score_explanation text,
  hard_filter_reason text,
  user_decision_reason text,

  -- Added now so later letter approval can bind to the exact text without a
  -- destructive schema change. No send worker consumes these fields yet.
  cover_letter_draft text,
  approved_letter_hash text,
  approved_at timestamptz,

  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, hh_vacancy_id)
);

CREATE INDEX IF NOT EXISTS idx_vacancy_pipeline_user_status
  ON vacancy_pipeline (user_id, status, discovered_at DESC);
CREATE INDEX IF NOT EXISTS idx_vacancy_pipeline_user_score
  ON vacancy_pipeline (user_id, score DESC NULLS LAST, discovered_at DESC);
CREATE INDEX IF NOT EXISTS idx_vacancy_pipeline_hh_id
  ON vacancy_pipeline (hh_vacancy_id);

CREATE TABLE IF NOT EXISTS vacancy_pipeline_sources (
  vacancy_id uuid NOT NULL REFERENCES vacancy_pipeline(id) ON DELETE CASCADE,
  source_id uuid NOT NULL REFERENCES vacancy_search_sources(id) ON DELETE CASCADE,
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (vacancy_id, source_id)
);

CREATE INDEX IF NOT EXISTS idx_vacancy_pipeline_sources_source
  ON vacancy_pipeline_sources (source_id, last_seen_at DESC);

-- Backend uses service_role; browser clients must go through the API so state
-- transitions and later approval rules cannot be bypassed with direct REST.
ALTER TABLE vacancy_search_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE vacancy_pipeline ENABLE ROW LEVEL SECURITY;
ALTER TABLE vacancy_pipeline_sources ENABLE ROW LEVEL SECURITY;
