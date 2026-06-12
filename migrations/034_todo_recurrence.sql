-- Recurring to-do tasks.
--
-- recurrence_interval/recurrence_unit: how often the task repeats, e.g.
--   (1, 'week') = weekly, (2, 'week') = every 2 weeks, (3, 'month') = quarterly.
--   Both NULL means the task does not repeat.
-- recurrence_spawned: set when this row's completion has already created the
--   next occurrence, so toggling a task done/undone/done can never spawn
--   duplicates. Each row spawns at most one successor, ever.
ALTER TABLE todos ADD COLUMN IF NOT EXISTS recurrence_interval INTEGER
    CHECK (recurrence_interval >= 1);
ALTER TABLE todos ADD COLUMN IF NOT EXISTS recurrence_unit TEXT
    CHECK (recurrence_unit IN ('day', 'week', 'month'));
ALTER TABLE todos ADD COLUMN IF NOT EXISTS recurrence_spawned BOOLEAN NOT NULL DEFAULT FALSE;
