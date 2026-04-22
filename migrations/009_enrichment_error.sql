-- Track enrichment errors (e.g. Apollo credit exhaustion) on import batches.
ALTER TABLE import_batches ADD COLUMN IF NOT EXISTS enrichment_error TEXT;
