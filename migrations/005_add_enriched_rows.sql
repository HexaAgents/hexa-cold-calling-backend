-- Track how many contacts have been sent to Apollo for enrichment during import
ALTER TABLE import_batches ADD COLUMN IF NOT EXISTS enriched_rows INTEGER DEFAULT 0;
