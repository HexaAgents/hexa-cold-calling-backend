-- Allow a new enrichment_status value, 'enrichment_no_phone', for cases where
-- Apollo's webhook returned an empty phone_numbers list (i.e. we successfully
-- enriched but Apollo had no phone on file / we were out of phone credits).
-- Distinguishing this from 'enriched' lets backfill jobs retry these contacts
-- and lets the UI show an accurate status badge.

ALTER TABLE contacts DROP CONSTRAINT IF EXISTS contacts_enrichment_status_check;

ALTER TABLE contacts ADD CONSTRAINT contacts_enrichment_status_check
  CHECK (enrichment_status IN (
    'pending_enrichment',
    'enriching',
    'enriched',
    'enrichment_failed',
    'enrichment_no_phone'
  ));
