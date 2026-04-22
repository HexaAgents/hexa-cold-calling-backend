-- Adds per-contact timezone derivation so we can filter the call queue by the
-- contact's current local time (e.g. business-hours-only).
--
-- Strategy:
--   1. New TEXT column `contacts.timezone` holding an IANA zone string.
--   2. `derive_timezone(state, country)` function with a big CASE mapping:
--      - US, Canada, Australia, Russia, Brazil, Mexico: resolved by state/province.
--      - Single-timezone countries: resolved by country.
--      - Unknown/blank input: returns NULL (caller falls back safely).
--   3. BEFORE INSERT OR UPDATE trigger keeps timezone in sync automatically.
--   4. claim_next_contact gains `p_business_hours_only` filtering by local hour.

-- ============================================================
-- 1. Column + index
-- ============================================================
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS timezone TEXT;
CREATE INDEX IF NOT EXISTS idx_contacts_timezone ON contacts(timezone);

-- ============================================================
-- 2. Timezone derivation function
-- ============================================================
CREATE OR REPLACE FUNCTION derive_timezone(p_state TEXT, p_country TEXT)
RETURNS TEXT
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
  s TEXT := LOWER(TRIM(COALESCE(p_state, '')));
  c TEXT := LOWER(TRIM(COALESCE(p_country, '')));
BEGIN
  -- Normalize common country synonyms up-front.
  IF c IN ('usa', 'u.s.', 'u.s.a.', 'united states', 'united states of america', 'us') THEN
    c := 'united states';
  ELSIF c IN ('uk', 'u.k.', 'united kingdom', 'great britain', 'britain', 'england', 'scotland', 'wales', 'northern ireland') THEN
    c := 'united kingdom';
  ELSIF c IN ('uae', 'u.a.e.') THEN
    c := 'united arab emirates';
  ELSIF c IN ('south korea', 'republic of korea', 'korea, republic of', 'korea') THEN
    c := 'south korea';
  ELSIF c IN ('russia', 'russian federation') THEN
    c := 'russia';
  ELSIF c IN ('czech republic', 'czechia') THEN
    c := 'czech republic';
  END IF;

  -- =========================================================
  -- United States (by state, 2-letter or full name)
  -- =========================================================
  IF c = 'united states' OR s IN (
    'alabama','alaska','arizona','arkansas','california','colorado','connecticut','delaware','florida',
    'georgia','hawaii','idaho','illinois','indiana','iowa','kansas','kentucky','louisiana','maine',
    'maryland','massachusetts','michigan','minnesota','mississippi','missouri','montana','nebraska',
    'nevada','new hampshire','new jersey','new mexico','new york','north carolina','north dakota',
    'ohio','oklahoma','oregon','pennsylvania','rhode island','south carolina','south dakota',
    'tennessee','texas','utah','vermont','virginia','washington','west virginia','wisconsin','wyoming',
    'district of columbia','washington dc','washington d.c.',
    'al','ak','az','ar','ca','co','ct','de','fl','ga','hi','id','il','in','ia','ks','ky','la','me',
    'md','ma','mi','mn','ms','mo','mt','ne','nv','nh','nj','nm','ny','nc','nd','oh','ok','or','pa',
    'ri','sc','sd','tn','tx','ut','vt','va','wa','wv','wi','wy','dc'
  ) THEN
    -- Pacific
    IF s IN ('california','ca','washington','wa','oregon','or','nevada','nv') THEN
      RETURN 'America/Los_Angeles';
    END IF;
    -- Mountain (non-DST Arizona handled separately)
    IF s IN ('arizona','az') THEN
      RETURN 'America/Phoenix';
    END IF;
    IF s IN ('colorado','co','montana','mt','new mexico','nm','utah','ut','wyoming','wy','idaho','id') THEN
      RETURN 'America/Denver';
    END IF;
    -- Central
    IF s IN (
      'texas','tx','illinois','il','minnesota','mn','iowa','ia','missouri','mo','arkansas','ar',
      'louisiana','la','mississippi','ms','alabama','al','tennessee','tn','kentucky','ky',
      'wisconsin','wi','oklahoma','ok','kansas','ks','nebraska','ne','north dakota','nd',
      'south dakota','sd'
    ) THEN
      RETURN 'America/Chicago';
    END IF;
    -- Alaska / Hawaii
    IF s IN ('alaska','ak') THEN
      RETURN 'America/Anchorage';
    END IF;
    IF s IN ('hawaii','hi') THEN
      RETURN 'Pacific/Honolulu';
    END IF;
    -- Default US state → Eastern (covers NY, FL, GA, VA, MA, PA, NJ, CT, etc.)
    RETURN 'America/New_York';
  END IF;

  -- =========================================================
  -- Canada (by province)
  -- =========================================================
  IF c = 'canada' THEN
    IF s IN ('british columbia','bc','yukon','yt') THEN RETURN 'America/Vancouver'; END IF;
    IF s IN ('alberta','ab','northwest territories','nt','nu','nunavut') THEN RETURN 'America/Edmonton'; END IF;
    IF s IN ('saskatchewan','sk') THEN RETURN 'America/Regina'; END IF;
    IF s IN ('manitoba','mb') THEN RETURN 'America/Winnipeg'; END IF;
    IF s IN ('ontario','on','quebec','qc') THEN RETURN 'America/Toronto'; END IF;
    IF s IN ('new brunswick','nb','nova scotia','ns','prince edward island','pe','pei') THEN RETURN 'America/Halifax'; END IF;
    IF s IN ('newfoundland and labrador','newfoundland','nl') THEN RETURN 'America/St_Johns'; END IF;
    RETURN 'America/Toronto';
  END IF;

  -- =========================================================
  -- Australia (by state)
  -- =========================================================
  IF c = 'australia' THEN
    IF s IN ('western australia','wa') THEN RETURN 'Australia/Perth'; END IF;
    IF s IN ('northern territory','nt') THEN RETURN 'Australia/Darwin'; END IF;
    IF s IN ('south australia','sa') THEN RETURN 'Australia/Adelaide'; END IF;
    IF s IN ('queensland','qld') THEN RETURN 'Australia/Brisbane'; END IF;
    IF s IN ('tasmania','tas') THEN RETURN 'Australia/Hobart'; END IF;
    -- NSW, VIC, ACT default
    RETURN 'Australia/Sydney';
  END IF;

  -- =========================================================
  -- Russia (by federal subject, rough mapping)
  -- =========================================================
  IF c = 'russia' THEN
    IF s IN ('kaliningrad','kaliningrad oblast') THEN RETURN 'Europe/Kaliningrad'; END IF;
    IF s IN ('samara','samara oblast','udmurtia','udmurt republic') THEN RETURN 'Europe/Samara'; END IF;
    IF s IN ('yekaterinburg','sverdlovsk','sverdlovsk oblast','chelyabinsk','chelyabinsk oblast','perm','perm krai','bashkortostan') THEN RETURN 'Asia/Yekaterinburg'; END IF;
    IF s IN ('omsk','omsk oblast') THEN RETURN 'Asia/Omsk'; END IF;
    IF s IN ('novosibirsk','novosibirsk oblast','krasnoyarsk','krasnoyarsk krai') THEN RETURN 'Asia/Krasnoyarsk'; END IF;
    IF s IN ('irkutsk','irkutsk oblast','buryatia') THEN RETURN 'Asia/Irkutsk'; END IF;
    IF s IN ('yakutsk','sakha') THEN RETURN 'Asia/Yakutsk'; END IF;
    IF s IN ('vladivostok','primorsky krai','khabarovsk','khabarovsk krai') THEN RETURN 'Asia/Vladivostok'; END IF;
    IF s IN ('magadan','magadan oblast') THEN RETURN 'Asia/Magadan'; END IF;
    IF s IN ('kamchatka','kamchatka krai') THEN RETURN 'Asia/Kamchatka'; END IF;
    -- Moscow / St Petersburg / default
    RETURN 'Europe/Moscow';
  END IF;

  -- =========================================================
  -- Brazil (by state — most business happens on BRT)
  -- =========================================================
  IF c = 'brazil' THEN
    IF s IN ('acre','ac') THEN RETURN 'America/Rio_Branco'; END IF;
    IF s IN ('amazonas','am','rondonia','rondônia','ro','roraima','rr','mato grosso','mt','mato grosso do sul','ms') THEN RETURN 'America/Manaus'; END IF;
    IF s IN ('fernando de noronha') THEN RETURN 'America/Noronha'; END IF;
    RETURN 'America/Sao_Paulo';
  END IF;

  -- =========================================================
  -- Mexico (by state)
  -- =========================================================
  IF c = 'mexico' THEN
    IF s IN ('baja california','bc') THEN RETURN 'America/Tijuana'; END IF;
    IF s IN ('baja california sur','bcs','chihuahua','nayarit','sinaloa','sonora') THEN RETURN 'America/Hermosillo'; END IF;
    IF s IN ('quintana roo') THEN RETURN 'America/Cancun'; END IF;
    RETURN 'America/Mexico_City';
  END IF;

  -- =========================================================
  -- Single-timezone countries
  -- =========================================================
  IF c = 'united kingdom' THEN RETURN 'Europe/London'; END IF;
  IF c = 'ireland' THEN RETURN 'Europe/Dublin'; END IF;
  IF c = 'portugal' THEN RETURN 'Europe/Lisbon'; END IF;
  IF c IN ('france','monaco') THEN RETURN 'Europe/Paris'; END IF;
  IF c IN ('germany','austria','switzerland','liechtenstein','luxembourg') THEN RETURN 'Europe/Berlin'; END IF;
  IF c = 'netherlands' THEN RETURN 'Europe/Amsterdam'; END IF;
  IF c = 'belgium' THEN RETURN 'Europe/Brussels'; END IF;
  IF c = 'spain' THEN RETURN 'Europe/Madrid'; END IF;
  IF c IN ('italy','vatican city','san marino','malta') THEN RETURN 'Europe/Rome'; END IF;
  IF c = 'sweden' THEN RETURN 'Europe/Stockholm'; END IF;
  IF c = 'norway' THEN RETURN 'Europe/Oslo'; END IF;
  IF c = 'denmark' THEN RETURN 'Europe/Copenhagen'; END IF;
  IF c = 'finland' THEN RETURN 'Europe/Helsinki'; END IF;
  IF c = 'iceland' THEN RETURN 'Atlantic/Reykjavik'; END IF;
  IF c = 'poland' THEN RETURN 'Europe/Warsaw'; END IF;
  IF c = 'czech republic' THEN RETURN 'Europe/Prague'; END IF;
  IF c = 'slovakia' THEN RETURN 'Europe/Bratislava'; END IF;
  IF c = 'hungary' THEN RETURN 'Europe/Budapest'; END IF;
  IF c = 'romania' THEN RETURN 'Europe/Bucharest'; END IF;
  IF c = 'bulgaria' THEN RETURN 'Europe/Sofia'; END IF;
  IF c = 'greece' THEN RETURN 'Europe/Athens'; END IF;
  IF c = 'turkey' THEN RETURN 'Europe/Istanbul'; END IF;
  IF c = 'ukraine' THEN RETURN 'Europe/Kyiv'; END IF;
  IF c = 'israel' THEN RETURN 'Asia/Jerusalem'; END IF;
  IF c = 'united arab emirates' THEN RETURN 'Asia/Dubai'; END IF;
  IF c = 'saudi arabia' THEN RETURN 'Asia/Riyadh'; END IF;
  IF c = 'qatar' THEN RETURN 'Asia/Qatar'; END IF;
  IF c = 'kuwait' THEN RETURN 'Asia/Kuwait'; END IF;
  IF c = 'bahrain' THEN RETURN 'Asia/Bahrain'; END IF;
  IF c = 'oman' THEN RETURN 'Asia/Muscat'; END IF;
  IF c = 'jordan' THEN RETURN 'Asia/Amman'; END IF;
  IF c = 'lebanon' THEN RETURN 'Asia/Beirut'; END IF;
  IF c = 'egypt' THEN RETURN 'Africa/Cairo'; END IF;
  IF c = 'morocco' THEN RETURN 'Africa/Casablanca'; END IF;
  IF c = 'nigeria' THEN RETURN 'Africa/Lagos'; END IF;
  IF c = 'kenya' THEN RETURN 'Africa/Nairobi'; END IF;
  IF c = 'south africa' THEN RETURN 'Africa/Johannesburg'; END IF;
  IF c = 'india' THEN RETURN 'Asia/Kolkata'; END IF;
  IF c = 'pakistan' THEN RETURN 'Asia/Karachi'; END IF;
  IF c = 'bangladesh' THEN RETURN 'Asia/Dhaka'; END IF;
  IF c = 'sri lanka' THEN RETURN 'Asia/Colombo'; END IF;
  IF c = 'nepal' THEN RETURN 'Asia/Kathmandu'; END IF;
  IF c = 'china' THEN RETURN 'Asia/Shanghai'; END IF;
  IF c = 'hong kong' THEN RETURN 'Asia/Hong_Kong'; END IF;
  IF c = 'taiwan' THEN RETURN 'Asia/Taipei'; END IF;
  IF c = 'japan' THEN RETURN 'Asia/Tokyo'; END IF;
  IF c = 'south korea' THEN RETURN 'Asia/Seoul'; END IF;
  IF c = 'singapore' THEN RETURN 'Asia/Singapore'; END IF;
  IF c = 'malaysia' THEN RETURN 'Asia/Kuala_Lumpur'; END IF;
  IF c = 'indonesia' THEN RETURN 'Asia/Jakarta'; END IF;
  IF c = 'thailand' THEN RETURN 'Asia/Bangkok'; END IF;
  IF c = 'vietnam' THEN RETURN 'Asia/Ho_Chi_Minh'; END IF;
  IF c = 'philippines' THEN RETURN 'Asia/Manila'; END IF;
  IF c = 'new zealand' THEN RETURN 'Pacific/Auckland'; END IF;
  IF c = 'argentina' THEN RETURN 'America/Argentina/Buenos_Aires'; END IF;
  IF c = 'chile' THEN RETURN 'America/Santiago'; END IF;
  IF c = 'colombia' THEN RETURN 'America/Bogota'; END IF;
  IF c = 'peru' THEN RETURN 'America/Lima'; END IF;
  IF c = 'venezuela' THEN RETURN 'America/Caracas'; END IF;
  IF c = 'uruguay' THEN RETURN 'America/Montevideo'; END IF;
  IF c = 'ecuador' THEN RETURN 'America/Guayaquil'; END IF;
  IF c = 'bolivia' THEN RETURN 'America/La_Paz'; END IF;
  IF c = 'paraguay' THEN RETURN 'America/Asuncion'; END IF;

  RETURN NULL;
END;
$$;

-- ============================================================
-- 3. Backfill + trigger
-- ============================================================
UPDATE contacts SET timezone = derive_timezone(state, country);

CREATE OR REPLACE FUNCTION set_contact_timezone()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.timezone := derive_timezone(NEW.state, NEW.country);
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS contacts_set_timezone ON contacts;
CREATE TRIGGER contacts_set_timezone
  BEFORE INSERT OR UPDATE OF state, country ON contacts
  FOR EACH ROW EXECUTE FUNCTION set_contact_timezone();

-- ============================================================
-- 4. claim_next_contact — add business-hours filter
-- ============================================================
CREATE OR REPLACE FUNCTION claim_next_contact(
  p_user_id UUID,
  p_expire_minutes INT DEFAULT 30,
  p_cities TEXT[] DEFAULT NULL,
  p_states TEXT[] DEFAULT NULL,
  p_countries TEXT[] DEFAULT NULL,
  p_business_hours_only BOOLEAN DEFAULT FALSE
)
RETURNS SETOF contacts
LANGUAGE plpgsql
AS $$
DECLARE
  v_id UUID;
BEGIN
  SELECT c.id INTO v_id
  FROM contacts c
  WHERE (
      -- Fresh contacts
      (c.call_outcome IS NULL
       AND (c.assigned_to IS NULL
            OR c.assigned_at < NOW() - (p_expire_minutes || ' minutes')::INTERVAL))
      OR
      -- Retry contacts due for this specific user
      (c.call_outcome = 'didnt_pick_up'
       AND c.retry_at IS NOT NULL
       AND c.retry_at <= NOW()
       AND c.assigned_to = p_user_id)
    )
    AND (c.mobile_phone IS NOT NULL OR c.work_direct_phone IS NOT NULL OR c.corporate_phone IS NOT NULL)
    AND (p_cities IS NULL     OR c.city IS NULL    OR c.city = ''    OR c.city = ANY(p_cities))
    AND (p_states IS NULL     OR c.state IS NULL   OR c.state = ''   OR c.state = ANY(p_states))
    AND (p_countries IS NULL  OR c.country IS NULL OR c.country = '' OR c.country = ANY(p_countries))
    AND (
      NOT p_business_hours_only
      OR c.timezone IS NULL
      OR EXTRACT(HOUR FROM (NOW() AT TIME ZONE c.timezone)) IN (8, 9, 10, 11, 14, 15, 16, 17)
    )
  ORDER BY
    CASE WHEN c.call_outcome = 'didnt_pick_up' THEN 0 ELSE 1 END,
    c.score DESC NULLS LAST,
    c.created_at ASC
  LIMIT 1
  FOR UPDATE SKIP LOCKED;

  IF v_id IS NULL THEN
    RETURN;
  END IF;

  UPDATE contacts
  SET assigned_to = p_user_id,
      assigned_at = NOW(),
      call_outcome = NULL,
      retry_at = NULL
  WHERE id = v_id;

  RETURN QUERY SELECT * FROM contacts WHERE id = v_id;
END;
$$;
