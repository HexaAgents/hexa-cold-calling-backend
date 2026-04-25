-- Email tracking: store synced Gmail messages (sent + received) for contacts
CREATE TABLE IF NOT EXISTS tracked_emails (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    contact_id UUID REFERENCES contacts(id) ON DELETE SET NULL,
    gmail_message_id TEXT NOT NULL,
    from_address TEXT NOT NULL,
    to_address TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    snippet TEXT NOT NULL DEFAULT '',
    direction TEXT NOT NULL CHECK (direction IN ('sent', 'received')),
    message_date TIMESTAMPTZ NOT NULL,
    synced_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, gmail_message_id)
);

CREATE INDEX IF NOT EXISTS idx_tracked_emails_user_contact ON tracked_emails(user_id, contact_id);
CREATE INDEX IF NOT EXISTS idx_tracked_emails_user_date ON tracked_emails(user_id, message_date DESC);
