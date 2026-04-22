-- Add state column for Apollo CSV import
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS state TEXT;
CREATE INDEX IF NOT EXISTS idx_contacts_state ON contacts(state);

-- Rebuild claim function with optional location filters.
-- Contacts with NULL/empty location always pass through filters.
CREATE OR REPLACE FUNCTION claim_next_contact(
  p_user_id UUID,
  p_expire_minutes INT DEFAULT 30,
  p_city TEXT DEFAULT NULL,
  p_state TEXT DEFAULT NULL,
  p_country TEXT DEFAULT NULL
)
RETURNS SETOF contacts
LANGUAGE plpgsql
AS $$
DECLARE
  v_id UUID;
BEGIN
  SELECT c.id INTO v_id
  FROM contacts c
  WHERE c.call_outcome IS NULL
    AND (
      c.assigned_to IS NULL
      OR c.assigned_at < NOW() - (p_expire_minutes || ' minutes')::INTERVAL
    )
    AND (c.mobile_phone IS NOT NULL OR c.work_direct_phone IS NOT NULL OR c.corporate_phone IS NOT NULL)
    AND (p_city IS NULL    OR c.city IS NULL    OR c.city = ''    OR c.city = p_city)
    AND (p_state IS NULL   OR c.state IS NULL   OR c.state = ''   OR c.state = p_state)
    AND (p_country IS NULL OR c.country IS NULL OR c.country = '' OR c.country = p_country)
  ORDER BY c.score DESC NULLS LAST, c.created_at ASC
  LIMIT 1
  FOR UPDATE SKIP LOCKED;

  IF v_id IS NULL THEN
    RETURN;
  END IF;

  UPDATE contacts
  SET assigned_to = p_user_id, assigned_at = NOW()
  WHERE id = v_id;

  RETURN QUERY SELECT * FROM contacts WHERE id = v_id;
END;
$$;
