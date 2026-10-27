-- Banque de sujets, brouillons, calendrier, publications, métriques.
CREATE TABLE IF NOT EXISTS topics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product TEXT NOT NULL,
  question TEXT NOT NULL,
  question_key TEXT NOT NULL,
  angle TEXT,
  status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'used', 'rejected')),
  source TEXT NOT NULL DEFAULT 'seed',
  created_at TEXT NOT NULL,
  UNIQUE (product, question_key)
);

CREATE TABLE IF NOT EXISTS drafts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic_id INTEGER NOT NULL REFERENCES topics(id),
  format TEXT NOT NULL CHECK (format IN ('short', 'long', 'linkedin', 'pin')),
  variant INTEGER NOT NULL,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'approved', 'rejected', 'rendered', 'published')),
  reject_reason TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_drafts_status ON drafts(status);

CREATE TABLE IF NOT EXISTS schedule (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  day TEXT NOT NULL,            -- AAAA-MM-JJ (heure locale)
  slot_at TEXT NOT NULL,        -- AAAA-MM-JJTHH:MM (heure locale, TIMEZONE)
  platform TEXT NOT NULL CHECK (platform IN ('youtube', 'tiktok', 'pinterest', 'linkedin')),
  format TEXT NOT NULL CHECK (format IN ('short', 'long', 'linkedin', 'pin')),
  product TEXT,
  draft_id INTEGER REFERENCES drafts(id),
  status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'published', 'skipped')),
  note TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (slot_at, platform, format)
);

CREATE TABLE IF NOT EXISTS publications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  draft_id INTEGER NOT NULL REFERENCES drafts(id),
  platform TEXT NOT NULL,
  dry_run INTEGER NOT NULL DEFAULT 1,
  request_file TEXT,
  remote_id TEXT,
  url TEXT,
  response_json TEXT,
  published_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_publications_draft ON publications(draft_id, platform);

CREATE TABLE IF NOT EXISTS metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT NOT NULL,
  remote_id TEXT,
  title TEXT,
  draft_id INTEGER REFERENCES drafts(id),
  views INTEGER NOT NULL DEFAULT 0,
  likes INTEGER NOT NULL DEFAULT 0,
  comments INTEGER NOT NULL DEFAULT 0,
  shares INTEGER NOT NULL DEFAULT 0,
  impressions INTEGER,
  ctr REAL,
  avg_view_pct REAL,
  watch_time_h REAL,
  published_at TEXT,
  imported_at TEXT NOT NULL,
  source_file TEXT
);
CREATE INDEX IF NOT EXISTS idx_metrics_platform_remote ON metrics(platform, remote_id);
