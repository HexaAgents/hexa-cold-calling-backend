-- Search & filter performance indexes.
--
-- 1. pg_trgm trigram indexes make leading-wildcard ILIKE ('%term%') searches
--    use bitmap index scans instead of sequential scans. The contacts list
--    search previously OR'd ILIKE across 6 columns, none of which could use
--    an index. We concatenate the searched fields into a single generated
--    `search_text` column with ONE trigram GIN index (cheaper to maintain
--    than 6 separate GIN indexes).
-- 2. B-tree indexes on hot filter columns used by the contacts list,
--    claim_next_contact, location filters, and productivity queries.
-- 3. A partial composite index matching the claim_next_contact eligibility
--    predicate and primary sort key.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================
-- 1. Combined search column + trigram index
-- ============================================================

ALTER TABLE contacts
  ADD COLUMN IF NOT EXISTS search_text TEXT GENERATED ALWAYS AS (
    COALESCE(first_name, '') || ' ' ||
    COALESCE(last_name, '') || ' ' ||
    COALESCE(company_name, '') || ' ' ||
    COALESCE(mobile_phone, '') || ' ' ||
    COALESCE(work_direct_phone, '') || ' ' ||
    COALESCE(corporate_phone, '')
  ) STORED;

CREATE INDEX IF NOT EXISTS idx_contacts_search_text_trgm
  ON contacts USING gin (search_text gin_trgm_ops);

-- Company search ("/companies?search=") and exact-name detail lookups.
CREATE INDEX IF NOT EXISTS idx_contacts_company_name_trgm
  ON contacts USING gin (company_name gin_trgm_ops);

-- ============================================================
-- 2. Missing B-tree indexes on hot filter columns
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_contacts_call_outcome ON contacts(call_outcome);
CREATE INDEX IF NOT EXISTS idx_contacts_company_type ON contacts(company_type);
CREATE INDEX IF NOT EXISTS idx_contacts_city ON contacts(city);
CREATE INDEX IF NOT EXISTS idx_contacts_country ON contacts(country);
CREATE INDEX IF NOT EXISTS idx_call_logs_user ON call_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_call_logs_created_at ON call_logs(created_at);

-- ============================================================
-- 3. Partial composite index for claim_next_contact
-- ============================================================
-- Matches the static eligibility predicate (hidden / rejected / has-phone)
-- and the leading ORDER BY keys (times_called, score, created_at) so the
-- claim scan touches only callable rows.

CREATE INDEX IF NOT EXISTS idx_contacts_claim_eligibility
  ON contacts ((COALESCE(times_called, 0)), score DESC NULLS LAST, created_at)
  WHERE hidden IS NOT TRUE
    AND company_type IS DISTINCT FROM 'rejected'
    AND (mobile_phone IS NOT NULL OR work_direct_phone IS NOT NULL OR corporate_phone IS NOT NULL);
