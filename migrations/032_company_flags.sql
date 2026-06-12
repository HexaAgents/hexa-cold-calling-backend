-- Company flags: mark a company with a warning (e.g. "Already has an AI
-- provider", "Too large to service") that surfaces on the call tracker when
-- any contact from that company comes up. Flags do NOT remove contacts from
-- the calling pool — they are purely informational.
--
-- One flag per company, keyed by lower(trim(company_name)) to match how the
-- companies pages group contacts.

CREATE TABLE IF NOT EXISTS company_flags (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_key TEXT NOT NULL UNIQUE,
  company_name TEXT NOT NULL,
  reason TEXT NOT NULL,
  details TEXT,
  flagged_by UUID,
  flagged_by_name TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
