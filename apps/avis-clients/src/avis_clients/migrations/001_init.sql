-- Schéma initial d'Avis Clients. Dates en ISO 8601 UTC (texte).

CREATE TABLE accounts (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  plan TEXT NOT NULL DEFAULT 'none' CHECK (plan IN ('none', 'solo', 'pro', 'reseau')),
  stripe_customer_id TEXT,
  stripe_subscription_id TEXT,
  subscription_status TEXT,
  trial_ends_at TEXT NOT NULL,
  last_login_at TEXT
);

CREATE TABLE magic_links (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT
);

CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  user_agent TEXT
);
CREATE INDEX idx_sessions_account ON sessions(account_id);

CREATE TABLE establishments (
  id INTEGER PRIMARY KEY,
  account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  google_place_id TEXT,
  google_location_name TEXT,
  review_url TEXT NOT NULL,
  tone_profile_json TEXT NOT NULL DEFAULT '{}',
  request_template TEXT NOT NULL,
  notification_email TEXT,
  auto_publish_positive INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_establishments_account ON establishments(account_id);

CREATE TABLE review_requests (
  id INTEGER PRIMARY KEY,
  establishment_id INTEGER NOT NULL REFERENCES establishments(id) ON DELETE CASCADE,
  channel TEXT NOT NULL CHECK (channel IN ('sms', 'whatsapp', 'email')),
  recipient TEXT NOT NULL,
  first_name TEXT,
  message TEXT NOT NULL,
  sent_at TEXT,
  status TEXT NOT NULL CHECK (status IN ('sent', 'dry-run', 'failed', 'blocked_optout', 'blocked_quota')),
  provider TEXT,
  provider_message_id TEXT,
  error TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_review_requests_establishment ON review_requests(establishment_id, created_at);

CREATE TABLE optouts (
  id INTEGER PRIMARY KEY,
  account_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
  phone TEXT NOT NULL,
  source TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_optouts_phone ON optouts(phone);

CREATE TABLE reviews (
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
    CHECK (reply_status IN ('none', 'draft', 'approved', 'published', 'skipped')),
  reply_draft TEXT,
  reply_published_at TEXT,
  alerted_at TEXT,
  UNIQUE (establishment_id, platform, external_id)
);
CREATE INDEX idx_reviews_status ON reviews(establishment_id, reply_status);

CREATE TABLE private_messages (
  id INTEGER PRIMARY KEY,
  establishment_id INTEGER NOT NULL REFERENCES establishments(id) ON DELETE CASCADE,
  sender_name TEXT,
  sender_contact TEXT,
  message TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE events (
  id INTEGER PRIMARY KEY,
  account_id INTEGER,
  establishment_id INTEGER,
  kind TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX idx_events_created ON events(created_at);

CREATE TABLE stripe_events (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  received_at TEXT NOT NULL
);
