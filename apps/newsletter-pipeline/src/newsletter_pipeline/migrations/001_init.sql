CREATE TABLE IF NOT EXISTS sources (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    url             TEXT NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('rss', 'page')),
    category        TEXT NOT NULL DEFAULT 'autre',
    lang            TEXT NOT NULL DEFAULT 'fr',
    weight          REAL NOT NULL DEFAULT 1.0,
    active          INTEGER NOT NULL DEFAULT 1,
    verify          INTEGER NOT NULL DEFAULT 0,
    include_patterns TEXT,                -- JSON : motifs (regex) de liens à suivre pour kind='page'
    last_fetched_at TEXT,
    last_error      TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id              INTEGER PRIMARY KEY,
    source_id       INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    url             TEXT NOT NULL UNIQUE,  -- URL canonique (sans utm, sans fragment)
    title           TEXT NOT NULL,
    title_hash      TEXT NOT NULL,
    published_at    TEXT,
    author          TEXT,
    summary         TEXT,
    content_text    TEXT,
    content_hash    TEXT,
    fetched_at      TEXT NOT NULL,
    score           REAL,
    score_json      TEXT,
    theme           TEXT,
    status          TEXT NOT NULL DEFAULT 'new'
                    CHECK (status IN ('new', 'selected', 'used', 'rejected')),
    used_in_issue   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_items_title_hash ON items(title_hash);
CREATE INDEX IF NOT EXISTS idx_items_status_score ON items(status, score);
CREATE INDEX IF NOT EXISTS idx_items_source ON items(source_id);

CREATE TABLE IF NOT EXISTS issues (
    number          INTEGER PRIMARY KEY,
    issue_date      TEXT NOT NULL,
    title           TEXT NOT NULL,
    case_slug       TEXT,
    md_path         TEXT NOT NULL,
    html_path       TEXT,
    txt_path        TEXT,
    item_ids        TEXT NOT NULL DEFAULT '[]',   -- JSON
    content_json    TEXT,
    status          TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'pushed', 'sent')),
    pushed_target   TEXT,
    pushed_at       TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
