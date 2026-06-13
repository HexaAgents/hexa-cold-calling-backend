-- Tracks the last calendar date (Pacific) the daily overdue-task email digest
-- was sent, so a backend restart after the send time doesn't re-send it.
ALTER TABLE settings ADD COLUMN IF NOT EXISTS overdue_digest_last_sent DATE;
