-- Store a "discarded" copy of each import: the rows that did NOT survive
-- scoring (rejected company types and zero-score rows). It is the exact
-- complement of `filtered_csv`, with the original headers and column order
-- preserved so the dropped leads can be audited or re-scored elsewhere.
ALTER TABLE import_batches ADD COLUMN IF NOT EXISTS discarded_csv TEXT;
