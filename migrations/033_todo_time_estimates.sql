-- AI time estimates for to-do tasks.
--
-- estimated_hours_min/max: the LLM's estimated hour range, written by a
--   one-shot background task after the todo is created.
-- estimate_status: NULL (pre-feature tasks) | 'pending' | 'done' | 'failed'.
--   'failed' is terminal - the system never retries, which caps OpenAI usage
--   at exactly one estimation call per task, ever.
-- actual_hours: how long the task actually took, reported (optionally) by the
--   person who ticks the task off. Recent (title, estimate, actual) triples
--   are fed back into the estimation prompt as calibration examples.

ALTER TABLE todos ADD COLUMN IF NOT EXISTS estimated_hours_min NUMERIC(6,1);
ALTER TABLE todos ADD COLUMN IF NOT EXISTS estimated_hours_max NUMERIC(6,1);
ALTER TABLE todos ADD COLUMN IF NOT EXISTS estimate_status TEXT;
ALTER TABLE todos ADD COLUMN IF NOT EXISTS actual_hours NUMERIC(6,1);
