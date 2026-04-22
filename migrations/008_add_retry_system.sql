-- Add retry system for "didn't pick up" contacts.
ALTER TABLE settings ADD COLUMN IF NOT EXISTS retry_days INTEGER NOT NULL DEFAULT 3;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS retry_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_contacts_retry_at ON contacts(retry_at);

-- Rebuild claim function with retry support.
-- Retry contacts (didnt_pick_up with retry_at in the past) are returned to the
-- same caller with priority over fresh leads.
CREATE OR REPLACE FUNCTION claim_next_contact(
  p_user_id UUID,
  p_expire_minutes INT DEFAULT 30,
  p_cities TEXT[] DEFAULT NULL,
  p_states TEXT[] DEFAULT NULL,
  p_countries TEXT[] DEFAULT NULL
)
RETURNS SETOF contacts
LANGUAGE plpgsql
AS $$
DECLARE
  v_id UUID;
BEGIN
  SELECT c.id INTO v_id
  FROM contacts c
  WHERE (
      -- Fresh contacts
      (c.call_outcome IS NULL
       AND (c.assigned_to IS NULL
            OR c.assigned_at < NOW() - (p_expire_minutes || ' minutes')::INTERVAL))
      OR
      -- Retry contacts due for this specific user
      (c.call_outcome = 'didnt_pick_up'
       AND c.retry_at IS NOT NULL
       AND c.retry_at <= NOW()
       AND c.assigned_to = p_user_id)
    )
    AND (c.mobile_phone IS NOT NULL OR c.work_direct_phone IS NOT NULL OR c.corporate_phone IS NOT NULL)
    AND (p_cities IS NULL     OR c.city IS NULL    OR c.city = ''    OR c.city = ANY(p_cities))
    AND (p_states IS NULL     OR c.state IS NULL   OR c.state = ''   OR c.state = ANY(p_states))
    AND (p_countries IS NULL  OR c.country IS NULL OR c.country = '' OR c.country = ANY(p_countries))
  ORDER BY
    CASE WHEN c.call_outcome = 'didnt_pick_up' THEN 0 ELSE 1 END,
    c.score DESC NULLS LAST,
    c.created_at ASC
  LIMIT 1
  FOR UPDATE SKIP LOCKED;

  IF v_id IS NULL THEN
    RETURN;
  END IF;

  UPDATE contacts
  SET assigned_to = p_user_id,
      assigned_at = NOW(),
      call_outcome = NULL,
      retry_at = NULL
  WHERE id = v_id;

  RETURN QUERY SELECT * FROM contacts WHERE id = v_id;
END;
$$;
