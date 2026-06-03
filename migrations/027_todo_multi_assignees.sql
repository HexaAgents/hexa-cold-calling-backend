-- Allow a task to be assigned to multiple people.
--
-- The original todos.assigned_to_* columns are kept as a compatibility mirror
-- of the first assignee while the API and UI move to the canonical join table.
CREATE TABLE IF NOT EXISTS todo_assignees (
    todo_id UUID NOT NULL REFERENCES todos(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    first_name TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (todo_id, user_id)
);

INSERT INTO todo_assignees (todo_id, user_id, first_name)
SELECT id, assigned_to_id, assigned_to_name
FROM todos
WHERE assigned_to_id IS NOT NULL
ON CONFLICT (todo_id, user_id) DO UPDATE
SET first_name = EXCLUDED.first_name;

CREATE INDEX IF NOT EXISTS idx_todo_assignees_user_id ON todo_assignees(user_id);

ALTER TABLE todo_assignees ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Authenticated users have full access to todo assignees"
  ON todo_assignees FOR ALL
  USING (auth.role() = 'authenticated')
  WITH CHECK (auth.role() = 'authenticated');
