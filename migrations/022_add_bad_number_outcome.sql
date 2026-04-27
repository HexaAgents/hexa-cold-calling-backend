-- Allow bad_number on call logs and contacts (productivity reads call_logs.outcome).
-- The UI logs this outcome, but the initial schema CHECK only allowed three values.

DO $$
DECLARE r record;
BEGIN
  FOR r IN (
    SELECT con.conname
    FROM pg_constraint con
    INNER JOIN pg_class rel ON rel.oid = con.conrelid
    INNER JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
    WHERE nsp.nspname = 'public'
      AND rel.relname = 'contacts'
      AND con.contype = 'c'
      AND pg_get_constraintdef(con.oid) LIKE '%call_outcome%'
  ) LOOP
    EXECUTE format('ALTER TABLE contacts DROP CONSTRAINT %I', r.conname);
  END LOOP;
END $$;

ALTER TABLE contacts ADD CONSTRAINT contacts_call_outcome_check CHECK (
  call_outcome IS NULL
  OR call_outcome IN ('didnt_pick_up', 'not_interested', 'interested', 'bad_number')
);

DO $$
DECLARE r record;
BEGIN
  FOR r IN (
    SELECT con.conname
    FROM pg_constraint con
    INNER JOIN pg_class rel ON rel.oid = con.conrelid
    INNER JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
    WHERE nsp.nspname = 'public'
      AND rel.relname = 'call_logs'
      AND con.contype = 'c'
      AND pg_get_constraintdef(con.oid) LIKE '%outcome%'
      AND pg_get_constraintdef(con.oid) LIKE '%didnt_pick_up%'
  ) LOOP
    EXECUTE format('ALTER TABLE call_logs DROP CONSTRAINT %I', r.conname);
  END LOOP;
END $$;

ALTER TABLE call_logs ADD CONSTRAINT call_logs_outcome_check CHECK (
  outcome IS NULL
  OR outcome IN ('didnt_pick_up', 'not_interested', 'interested', 'bad_number')
);
