-- Revue QA-1 : provenance du brouillon (llm | llm-cleaned | fallback) pour ne jamais auto-publier
-- un texte générique ou nettoyé mécaniquement ; index du journal par compte.
ALTER TABLE reviews ADD COLUMN reply_draft_source TEXT;
CREATE INDEX IF NOT EXISTS idx_events_account ON events(account_id, id);
