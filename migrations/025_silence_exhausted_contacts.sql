-- Reverses the policy in 023: instead of DELETING contacts that have hit
-- the sms_call_threshold of "didn't pick up" occasions, we now SILENCE
-- them by clearing their `retry_at`. They stay in the database and the
-- contacts list, but drop out of the call tracker queue because
-- `claim_next_contact` only picks didnt_pick_up contacts when
-- `retry_at IS NOT NULL`.
--
-- 023 ran once before this policy change and already deleted any matching
-- contacts in production. This migration retroactively quiets any new
-- offenders that have built up under the current sms_call_threshold value
-- so the new code's behavior is consistent across history.

UPDATE contacts c
SET retry_at = NULL
FROM settings s
WHERE c.call_outcome = 'didnt_pick_up'
  AND c.call_occasion_count >= s.sms_call_threshold
  AND c.retry_at IS NOT NULL;
