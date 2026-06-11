-- Reactivate stale "didn't pick up" contacts into the SHARED calling pool.
--
-- Two parts:
--   1. Recreate claim_next_contact with an extra "shared retry" branch so a
--      reactivated didnt_pick_up contact (retry due, no owner) can be claimed by
--      ANY caller, not just the user who originally called it.
--   2. reactivate_stale_didnt_pickup_contacts(): re-queues silenced didnt_pick_up
--      contacts (called on >= N occasions, last call > M days ago) by setting
--      retry_at = NOW() and clearing assigned_to/assigned_at, and returns their ids.

-- 1. Recreate claim_next_contact (same as migration 018 + shared-retry branch)
CREATE OR REPLACE FUNCTION claim_next_contact(
  p_user_id UUID,
  p_expire_minutes INT DEFAULT 30,
  p_cities TEXT[] DEFAULT NULL,
  p_states TEXT[] DEFAULT NULL,
  p_countries TEXT[] DEFAULT NULL,
  p_business_hours_only BOOLEAN DEFAULT FALSE
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
      -- Fresh contacts (never called — available to anyone)
      (c.call_outcome IS NULL
       AND (c.times_called IS NULL OR c.times_called = 0)
       AND (c.assigned_to IS NULL
            OR c.assigned_at < NOW() - (p_expire_minutes || ' minutes')::INTERVAL))
      OR
      -- Retry contacts due for this specific user
      (c.call_outcome = 'didnt_pick_up'
       AND c.retry_at IS NOT NULL
       AND c.retry_at <= NOW()
       AND c.assigned_to = p_user_id)
      OR
      -- Shared retry: reactivated didnt_pick_up with no owner -> any caller can claim
      (c.call_outcome = 'didnt_pick_up'
       AND c.retry_at IS NOT NULL
       AND c.retry_at <= NOW()
       AND c.assigned_to IS NULL)
      OR
      -- Stale reclaim: same user can reclaim their previously called contacts
      (c.call_outcome IS NULL
       AND c.times_called > 0
       AND c.assigned_to = p_user_id
       AND c.assigned_at < NOW() - (p_expire_minutes || ' minutes')::INTERVAL)
    )
    AND (c.hidden IS NOT TRUE)
    AND (c.company_type IS DISTINCT FROM 'rejected')
    AND (c.mobile_phone IS NOT NULL OR c.work_direct_phone IS NOT NULL OR c.corporate_phone IS NOT NULL)
    AND (p_cities IS NULL     OR c.city IS NULL    OR c.city = ''    OR c.city = ANY(p_cities))
    AND (p_states IS NULL     OR c.state IS NULL   OR c.state = ''   OR c.state = ANY(p_states))
    AND (p_countries IS NULL  OR c.country IS NULL OR c.country = '' OR c.country = ANY(p_countries))
    AND (
      NOT p_business_hours_only
      OR c.timezone IS NULL
      OR EXTRACT(HOUR FROM (NOW() AT TIME ZONE c.timezone)) IN (8, 9, 10, 11, 14, 15, 16)
    )
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

-- 2. Reactivate stale didnt_pick_up contacts into the shared pool
CREATE OR REPLACE FUNCTION reactivate_stale_didnt_pickup_contacts(
  p_min_occasions INTEGER DEFAULT 2,
  p_stale_days INTEGER DEFAULT 7
)
RETURNS TABLE(id UUID)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  UPDATE contacts c
  SET retry_at = NOW(),
      assigned_to = NULL,
      assigned_at = NULL,
      updated_at = NOW()
  WHERE c.call_outcome = 'didnt_pick_up'
    AND c.call_occasion_count >= p_min_occasions
    AND c.retry_at IS NULL
    AND c.hidden IS NOT TRUE
    AND c.company_type IS DISTINCT FROM 'rejected'
    AND (c.mobile_phone IS NOT NULL OR c.work_direct_phone IS NOT NULL OR c.corporate_phone IS NOT NULL)
    AND EXISTS (
      SELECT 1 FROM call_logs cl
      WHERE cl.contact_id = c.id
      GROUP BY cl.contact_id
      HAVING MAX(cl.created_at) < NOW() - (p_stale_days || ' days')::INTERVAL
    )
  RETURNING c.id;
END;
$$;
