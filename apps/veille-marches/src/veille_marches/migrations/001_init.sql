-- Avis de marchés normalisés (BOAMP, TED, DECP n'y entre pas : voir awards)
CREATE TABLE IF NOT EXISTS notices (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  source           TEXT NOT NULL CHECK (source IN ('boamp', 'ted', 'decp')),
  source_id        TEXT NOT NULL,
  title            TEXT NOT NULL,
  buyer_name       TEXT,
  buyer_dept       TEXT,
  departments      TEXT NOT NULL DEFAULT '[]',   -- liste JSON des départements (lieu d'exécution)
  cpv_codes        TEXT NOT NULL DEFAULT '[]',   -- liste JSON de codes CPV à 8 chiffres
  description      TEXT,
  estimated_amount REAL,
  published_at     TEXT,
  deadline_at      TEXT,
  procedure_type   TEXT,
  url              TEXT,
  raw              TEXT NOT NULL,                -- enregistrement source complet (JSON)
  collected_at     TEXT NOT NULL,
  UNIQUE (source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_notices_published ON notices (published_at);
CREATE INDEX IF NOT EXISTS idx_notices_buyer ON notices (buyer_name);

-- Abonnés (un abonné = un email, un métier via préfixes CPV, des départements, une fourchette)
CREATE TABLE IF NOT EXISTS subscribers (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  email        TEXT NOT NULL UNIQUE COLLATE NOCASE,
  label        TEXT,
  cpv_prefixes TEXT NOT NULL DEFAULT '[]',       -- liste JSON, ex. ["773"]
  departments  TEXT NOT NULL DEFAULT '[]',       -- liste JSON, ex. ["69", "01"]
  amount_min   REAL,
  amount_max   REAL,
  plan         TEXT NOT NULL DEFAULT 'essentiel' CHECK (plan IN ('essentiel', 'pro')),
  active       INTEGER NOT NULL DEFAULT 1,
  created_at   TEXT NOT NULL
);

-- Résumé structuré + score de référence, calculés une fois par avis et partagés entre abonnés
CREATE TABLE IF NOT EXISTS summaries (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  notice_id    INTEGER NOT NULL UNIQUE REFERENCES notices (id) ON DELETE CASCADE,
  summary_json TEXT NOT NULL,
  score        INTEGER NOT NULL,                 -- score final de référence (meilleur abonné)
  rules_score  INTEGER NOT NULL,
  llm_verdict  TEXT,
  llm_provider TEXT,
  created_at   TEXT NOT NULL
);

-- Un avis n'est envoyé qu'une seule fois à un abonné donné
CREATE TABLE IF NOT EXISTS deliveries (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  subscriber_id INTEGER NOT NULL REFERENCES subscribers (id) ON DELETE CASCADE,
  notice_id     INTEGER NOT NULL REFERENCES notices (id) ON DELETE CASCADE,
  sent_at       TEXT NOT NULL,
  score         INTEGER,
  UNIQUE (subscriber_id, notice_id)
);

-- Attributions (DECP) pour le brief hebdo
CREATE TABLE IF NOT EXISTS awards (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  source            TEXT NOT NULL DEFAULT 'decp',
  source_id         TEXT NOT NULL,
  title             TEXT,
  buyer_name        TEXT,
  buyer_id          TEXT,
  holder_name       TEXT,
  holder_id         TEXT,
  amount            REAL,
  cpv_code          TEXT,
  dept              TEXT,
  place_code        TEXT,
  place_type        TEXT,
  procedure_type    TEXT,
  notified_at       TEXT,
  data_published_at TEXT,
  duration_months   INTEGER,
  raw               TEXT NOT NULL,
  collected_at      TEXT NOT NULL,
  UNIQUE (source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_awards_notified ON awards (notified_at);
CREATE INDEX IF NOT EXISTS idx_awards_dept ON awards (dept);

-- Journal des collectes (volume anormal = alerte à lire dans `vm stats`)
CREATE TABLE IF NOT EXISTS collect_runs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  source      TEXT NOT NULL,
  started_at  TEXT NOT NULL,
  finished_at TEXT,
  fetched     INTEGER NOT NULL DEFAULT 0,
  inserted    INTEGER NOT NULL DEFAULT 0,
  error       TEXT
);
