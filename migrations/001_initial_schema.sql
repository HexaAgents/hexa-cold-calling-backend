-- Hexa Cold Calling Platform — Initial Schema
-- Run this in the Supabase SQL Editor:
-- https://supabase.com/dashboard/project/gtlvffaqwbxeczmbrhkc/sql

-- ============================================================
-- 1. CONTACTS
-- ============================================================
CREATE TABLE IF NOT EXISTS contacts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Personal info (from Apollo CSV)
  first_name TEXT,
  last_name TEXT,
  title TEXT,
  company_name TEXT NOT NULL,
  person_linkedin_url TEXT,
  website TEXT,
  company_linkedin_url TEXT,
  employees TEXT,
  city TEXT,
  country TEXT,
  email TEXT,

  -- Phone numbers (up to 3, from Apollo CSV)
  mobile_phone TEXT,
  work_direct_phone TEXT,
  corporate_phone TEXT,

  -- Scoring results (from Exa + OpenAI)
  score INTEGER,
  company_type TEXT,
  rationale TEXT,
  rejection_reason TEXT,
  exa_scrape_success BOOLEAN DEFAULT FALSE,
  scoring_failed BOOLEAN DEFAULT FALSE,

  -- Call tracking
  call_occasion_count INTEGER DEFAULT 0,
  call_outcome TEXT CHECK (call_outcome IN ('didnt_pick_up', 'not_interested', 'interested')),

  -- SMS tracking
  messaging_status TEXT CHECK (messaging_status IN ('to_be_messaged', 'message_sent')),
  sms_sent BOOLEAN DEFAULT FALSE,
  sms_sent_after_calls INTEGER,
  sms_scheduled_at TIMESTAMPTZ,

  -- Import tracking
  import_batch_id UUID,

  -- Timestamps
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_contacts_website ON contacts(website);
CREATE INDEX IF NOT EXISTS idx_contacts_score ON contacts(score);
CREATE INDEX IF NOT EXISTS idx_contacts_import_batch ON contacts(import_batch_id);
CREATE INDEX IF NOT EXISTS idx_contacts_messaging_status ON contacts(messaging_status);
CREATE INDEX IF NOT EXISTS idx_contacts_created_at ON contacts(created_at);

-- ============================================================
-- 2. CALL LOGS
-- ============================================================
CREATE TABLE IF NOT EXISTS call_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contact_id UUID NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES auth.users(id),
  call_date DATE NOT NULL DEFAULT CURRENT_DATE,
  call_method TEXT NOT NULL CHECK (call_method IN ('browser', 'bridge')),
  phone_number_called TEXT,
  outcome TEXT CHECK (outcome IN ('didnt_pick_up', 'not_interested', 'interested')),
  is_new_occasion BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_call_logs_contact ON call_logs(contact_id);
CREATE INDEX IF NOT EXISTS idx_call_logs_date ON call_logs(call_date);

-- ============================================================
-- 3. NOTES
-- ============================================================
CREATE TABLE IF NOT EXISTS notes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contact_id UUID NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES auth.users(id),
  content TEXT NOT NULL,
  note_date DATE NOT NULL DEFAULT CURRENT_DATE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notes_contact ON notes(contact_id);

-- ============================================================
-- 4. SETTINGS (single global row)
-- ============================================================
CREATE TABLE IF NOT EXISTS settings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sms_call_threshold INTEGER NOT NULL DEFAULT 3,
  sms_template TEXT NOT NULL DEFAULT 'Hi <first_name>, this is Hexa. We help companies like <company_name> automate their workflows. Would you be open to a quick chat?',
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO settings (sms_call_threshold) VALUES (3);

-- ============================================================
-- 5. IMPORT BATCHES
-- ============================================================
CREATE TABLE IF NOT EXISTS import_batches (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id),
  filename TEXT NOT NULL,
  total_rows INTEGER DEFAULT 0,
  processed_rows INTEGER DEFAULT 0,
  stored_rows INTEGER DEFAULT 0,
  discarded_rows INTEGER DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'processing' CHECK (status IN ('processing', 'completed', 'failed')),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- 6. ROW-LEVEL SECURITY
-- ============================================================

ALTER TABLE contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE call_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE import_batches ENABLE ROW LEVEL SECURITY;

-- All authenticated users can read and write everything (shared workspace)
CREATE POLICY "Authenticated users have full access to contacts"
  ON contacts FOR ALL
  USING (auth.role() = 'authenticated')
  WITH CHECK (auth.role() = 'authenticated');

CREATE POLICY "Authenticated users have full access to call_logs"
  ON call_logs FOR ALL
  USING (auth.role() = 'authenticated')
  WITH CHECK (auth.role() = 'authenticated');

CREATE POLICY "Authenticated users have full access to notes"
  ON notes FOR ALL
  USING (auth.role() = 'authenticated')
  WITH CHECK (auth.role() = 'authenticated');

CREATE POLICY "Authenticated users have full access to settings"
  ON settings FOR ALL
  USING (auth.role() = 'authenticated')
  WITH CHECK (auth.role() = 'authenticated');

CREATE POLICY "Authenticated users have full access to import_batches"
  ON import_batches FOR ALL
  USING (auth.role() = 'authenticated')
  WITH CHECK (auth.role() = 'authenticated');

-- Service role bypasses RLS (for backend operations)

-- ============================================================
-- 7. UPDATED_AT TRIGGER
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER contacts_updated_at
  BEFORE UPDATE ON contacts
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER notes_updated_at
  BEFORE UPDATE ON notes
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER settings_updated_at
  BEFORE UPDATE ON settings
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();
