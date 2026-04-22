-- Add times_called column to contacts
-- Tracks total number of call outcomes logged (increments every time, unlike call_occasion_count which is once per day)

ALTER TABLE contacts ADD COLUMN IF NOT EXISTS times_called INTEGER DEFAULT 0;

-- Backfill from existing call_logs
UPDATE contacts
SET times_called = sub.cnt
FROM (
  SELECT contact_id, COUNT(*) AS cnt
  FROM call_logs
  GROUP BY contact_id
) sub
WHERE contacts.id = sub.contact_id;
