-- Track Apollo enrichment attempts so we can auto-retry transient failures
-- without looping forever, and distinguish "out of credits" (don't retry until
-- user clears) from "retriable HTTP error" (retry on next sweep).

ALTER TABLE contacts
  ADD COLUMN IF NOT EXISTS enrichment_attempts INT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_enrichment_error TEXT,
  ADD COLUMN IF NOT EXISTS enrichment_last_attempt_at TIMESTAMPTZ;

-- Index used by the stale enriching sweep to cheaply find contacts stuck in
-- 'enriching' past the webhook timeout.
CREATE INDEX IF NOT EXISTS idx_contacts_enrichment_status_attempt_at
  ON contacts (enrichment_status, enrichment_last_attempt_at)
  WHERE enrichment_status IN ('enriching', 'enrichment_failed');
