-- To-Do List feature.
--
-- This table is INTENTIONALLY standalone: it has no foreign keys to any other
-- table (not even auth.users). Assignee/creator are stored as plain UUIDs plus
-- a denormalized first name so the feature is fully decoupled from the rest of
-- the platform and can be dropped without affecting anything else.
CREATE TABLE IF NOT EXISTS todos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    description TEXT,
    assigned_to_id UUID,
    assigned_to_name TEXT,
    assigned_by_id UUID NOT NULL,
    assigned_by_name TEXT,
    due_date DATE,
    is_done BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Sorting/filtering: closest due dates first, with open work surfaced.
CREATE INDEX IF NOT EXISTS idx_todos_due_date ON todos(is_done, due_date);
CREATE INDEX IF NOT EXISTS idx_todos_assigned_to ON todos(assigned_to_id);

-- Row-level security: any authenticated user can read/write through the
-- shared-workspace policy (per-task permissions are enforced in the API layer,
-- where the backend uses the service role key).
ALTER TABLE todos ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Authenticated users have full access to todos"
  ON todos FOR ALL
  USING (auth.role() = 'authenticated')
  WITH CHECK (auth.role() = 'authenticated');

CREATE TRIGGER todos_updated_at
  BEFORE UPDATE ON todos
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();
