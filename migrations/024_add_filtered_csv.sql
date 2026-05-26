-- Store a "filtered" copy of each new import: the original CSV minus
-- discarded / rejected rows, with the original headers and column order
-- preserved so it can be re-imported or audited.
ALTER TABLE import_batches ADD COLUMN IF NOT EXISTS filtered_csv TEXT;
