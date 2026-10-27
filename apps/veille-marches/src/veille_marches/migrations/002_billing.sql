-- Inscription publique et paiement Stripe (P2-3b).
-- Les abonnés existants (créés par la CLI) gardent leur état : status = 'active' s'ils sont actifs, 'disabled' sinon.
ALTER TABLE subscribers ADD COLUMN company TEXT;
ALTER TABLE subscribers ADD COLUMN status TEXT NOT NULL DEFAULT 'active';
  -- pending_payment | active | past_due | unpaid | canceled | paused | disabled
ALTER TABLE subscribers ADD COLUMN billing_period TEXT NOT NULL DEFAULT 'monthly';   -- monthly | yearly
ALTER TABLE subscribers ADD COLUMN stripe_customer_id TEXT;
ALTER TABLE subscribers ADD COLUMN stripe_subscription_id TEXT;
ALTER TABLE subscribers ADD COLUMN checkout_session_id TEXT;
ALTER TABLE subscribers ADD COLUMN updated_at TEXT;
UPDATE subscribers SET status = CASE WHEN active = 1 THEN 'active' ELSE 'disabled' END;
CREATE INDEX IF NOT EXISTS idx_subscribers_stripe_customer ON subscribers (stripe_customer_id);
CREATE INDEX IF NOT EXISTS idx_subscribers_stripe_subscription ON subscribers (stripe_subscription_id);

-- Idempotence des webhooks : un événement Stripe n'est appliqué qu'une fois
CREATE TABLE IF NOT EXISTS stripe_events (
  id          TEXT PRIMARY KEY,
  type        TEXT NOT NULL,
  received_at TEXT NOT NULL,
  result      TEXT
);
