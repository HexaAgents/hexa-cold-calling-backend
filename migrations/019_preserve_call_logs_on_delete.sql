-- Preserve call_logs and email_logs when contacts are deleted so stats remain accurate.
-- Change contact_id from NOT NULL + ON DELETE CASCADE to nullable + ON DELETE SET NULL.

ALTER TABLE call_logs ALTER COLUMN contact_id DROP NOT NULL;
ALTER TABLE call_logs DROP CONSTRAINT IF EXISTS call_logs_contact_id_fkey;
ALTER TABLE call_logs
    ADD CONSTRAINT call_logs_contact_id_fkey
    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE SET NULL;

ALTER TABLE email_logs ALTER COLUMN contact_id DROP NOT NULL;
ALTER TABLE email_logs DROP CONSTRAINT IF EXISTS email_logs_contact_id_fkey;
ALTER TABLE email_logs
    ADD CONSTRAINT email_logs_contact_id_fkey
    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE SET NULL;
