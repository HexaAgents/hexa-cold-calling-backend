-- The sms_call_threshold setting now doubles as a "give up after N failed
-- pickups" threshold: contacts whose last outcome is didnt_pick_up and
-- whose call_occasion_count has hit the threshold are removed from the
-- database so they stop reappearing in the call tracker.
--
-- This migration retroactively removes existing contacts that already meet
-- those conditions under the current sms_call_threshold value.

DELETE FROM contacts c
USING settings s
WHERE c.call_outcome = 'didnt_pick_up'
  AND c.call_occasion_count >= s.sms_call_threshold;
