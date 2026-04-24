-- Add industry_tag column to store the NAICS-style industry classification
-- from the scoring prompt (e.g. "Electrical Supplies", "HVAC Equipment").
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS industry_tag TEXT;
