-- P4-4 : historique daté des relevés (API), identifiant public TikTok, statut des angles.
-- `measured_at` : date du relevé (ISO UTC). Un relevé par contenu, par source et par jour : relancer
-- `ce metrics --pull` le même jour met à jour le relevé du jour, les jours précédents sont conservés.
ALTER TABLE metrics ADD COLUMN measured_at TEXT;
ALTER TABLE metrics ADD COLUMN source TEXT NOT NULL DEFAULT 'csv';   -- csv | api
ALTER TABLE metrics ADD COLUMN clicks INTEGER;                        -- clics sortants (Pinterest)
ALTER TABLE metrics ADD COLUMN extra_json TEXT;                       -- champs bruts de l'API
UPDATE metrics SET measured_at = imported_at WHERE measured_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_metrics_draft_measured ON metrics(platform, draft_id, measured_at);

-- TikTok : `remote_id` est le publish_id ; l'identifiant public de la vidéo est résolu plus tard
-- (post/publish/status/fetch) et conservé ici pour interroger video/query.
ALTER TABLE publications ADD COLUMN post_id TEXT;

-- Angles mis en pause (automatiquement par `ce run-daily`, ou à la main avec `ce angles --pause`),
-- réactivables avec `ce angles --reactivate`.
CREATE TABLE IF NOT EXISTS angle_status (
  product TEXT NOT NULL,
  angle TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('active', 'paused')),
  decided_by TEXT NOT NULL DEFAULT 'auto' CHECK (decided_by IN ('auto', 'manual')),
  reason TEXT,
  score REAL,
  n_contents INTEGER NOT NULL DEFAULT 0,   -- contenus mesurés au moment de la décision
  updated_at TEXT NOT NULL,
  PRIMARY KEY (product, angle)
);
