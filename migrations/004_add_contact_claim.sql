-- Contact claim system: prevents two users from calling the same person
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS assigned_to UUID REFERENCES auth.users(id);
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS assigned_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_contacts_assigned_to ON contacts(assigned_to);
CREATE INDEX IF NOT EXISTS idx_contacts_assigned_at ON contacts(assigned_at);

-- RPC function: atomically claim the next available contact for a user.
-- Uses FOR UPDATE SKIP LOCKED to guarantee no two users get the same contact.
CREATE OR REPLACE FUNCTION claim_next_contact(p_user_id UUID, p_expire_minutes INT DEFAULT 30)
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

-- RPC function: release a claimed contact (unclaim it)
CREATE OR REPLACE FUNCTION release_contact(p_contact_id UUID, p_user_id UUID)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
  UPDATE contacts
  SET assigned_to = NULL, assigned_at = NULL
  WHERE id = p_contact_id AND assigned_to = p_user_id;
END;
$$;
