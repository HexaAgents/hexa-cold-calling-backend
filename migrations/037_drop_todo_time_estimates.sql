-- Remove the AI time estimate feature (added in 033_todo_time_estimates.sql).
-- The estimator, background task, and all API fields are gone; drop the
-- now-unused columns.

ALTER TABLE todos DROP COLUMN IF EXISTS estimated_hours_min;
ALTER TABLE todos DROP COLUMN IF EXISTS estimated_hours_max;
ALTER TABLE todos DROP COLUMN IF EXISTS estimate_status;
ALTER TABLE todos DROP COLUMN IF EXISTS actual_hours;
