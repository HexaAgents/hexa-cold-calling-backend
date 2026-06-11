-- Store the original ("input") copy of each upload on the import batch so it
-- can be re-downloaded later, alongside the existing filtered_csv and
-- discarded_csv copies. Only populated for uploads made after this migration.
ALTER TABLE import_batches ADD COLUMN IF NOT EXISTS input_csv TEXT;
