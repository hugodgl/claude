-- P1-4 : plateformes d'avis supplémentaires (Facebook, Tripadvisor).
-- 1. `review_sources` : au plus une source par établissement et par plateforme ; un identifiant externe
--    (fiche Google, Page Facebook, fiche Tripadvisor) ne peut être relié qu'à un seul établissement, quel
--    que soit le compte. Les sources Google existantes sont reprises depuis `establishments.google_location_name`
--    (colonne conservée et maintenue en miroir par le code).
-- 2. `reviews` : statut `published_manually` (Tripadvisor, réponse copiée-collée par le commerçant) et
--    colonne `rating_note` (recommandation Facebook sans note convertie en étoiles). SQLite ne modifie pas
--    une contrainte CHECK : la table est reconstruite. Atomicité : `core.db.migrate` exécute chaque fichier
--    dans un SAVEPOINT : aucun encadrement de transaction dans ce fichier.
CREATE TABLE review_sources (
  id INTEGER PRIMARY KEY,
  establishment_id INTEGER NOT NULL REFERENCES establishments(id) ON DELETE CASCADE,
  platform TEXT NOT NULL CHECK (platform IN ('google', 'facebook', 'tripadvisor')),
  external_id TEXT NOT NULL,
  display_name TEXT,
  public_url TEXT,
  credentials_enc TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'error', 'disabled')),
  last_synced_at TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT,
  UNIQUE (establishment_id, platform),
  UNIQUE (platform, external_id)
);
CREATE INDEX idx_review_sources_platform ON review_sources(platform, status);

INSERT OR IGNORE INTO review_sources (establishment_id, platform, external_id, status, created_at)
  SELECT id, 'google', google_location_name, 'active', created_at
  FROM establishments WHERE google_location_name IS NOT NULL AND google_location_name <> ''
  ORDER BY id;

CREATE TABLE reviews_new (
  id INTEGER PRIMARY KEY,
  establishment_id INTEGER NOT NULL REFERENCES establishments(id) ON DELETE CASCADE,
  platform TEXT NOT NULL DEFAULT 'google' CHECK (platform IN ('google', 'facebook', 'tripadvisor')),
  external_id TEXT NOT NULL,
  external_name TEXT,
  author TEXT,
  rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
  text TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT,
  fetched_at TEXT NOT NULL,
  reply_text TEXT,
  reply_status TEXT NOT NULL DEFAULT 'none'
    CHECK (reply_status IN ('none', 'draft', 'approved', 'published', 'published_manually', 'skipped')),
  reply_draft TEXT,
  reply_published_at TEXT,
  alerted_at TEXT,
  reply_draft_source TEXT,
  rating_note TEXT,
  UNIQUE (establishment_id, platform, external_id)
);
INSERT INTO reviews_new (id, establishment_id, platform, external_id, external_name, author, rating, text,
                         created_at, updated_at, fetched_at, reply_text, reply_status, reply_draft,
                         reply_published_at, alerted_at, reply_draft_source)
  SELECT id, establishment_id, platform, external_id, external_name, author, rating, text, created_at,
         updated_at, fetched_at, reply_text, reply_status, reply_draft, reply_published_at, alerted_at,
         reply_draft_source
  FROM reviews;
DROP TABLE reviews;
ALTER TABLE reviews_new RENAME TO reviews;
CREATE INDEX idx_reviews_status ON reviews(establishment_id, reply_status);
CREATE INDEX idx_reviews_platform ON reviews(establishment_id, platform);
