-- SQL-side aggregation RPCs.
--
-- These replace endpoints that previously fetched whole tables over PostgREST
-- and aggregated in Python:
--   * get_callable_location_counts(): the call tracker pool counts paged the
--     entire callable pool 1000 rows at a time on every page load and after
--     every claim. Now a single GROUP BY returning one small JSON object.
--   * get_distinct_locations(): the location filter dropdowns ran 3 unbounded
--     full-column scans and deduped in Python (silently truncating at the
--     PostgREST max-rows cap). Now one query with SQL DISTINCT.
--   * get_company_summaries(): the companies page fetched every non-rejected
--     contact row and grouped in Python. Now a SQL GROUP BY.
--
-- Filter semantics intentionally mirror the previous PostgREST queries,
-- including the NULL-excluding `company_type <> 'rejected'` used by the
-- locations and companies endpoints (PostgREST `neq`).

-- ============================================================
-- 1. Callable pool counts for the call tracker
-- ============================================================

CREATE OR REPLACE FUNCTION get_callable_location_counts()
RETURNS JSON
LANGUAGE sql
STABLE
AS $$
  WITH callable AS (
    SELECT
      NULLIF(TRIM(city), '') AS city,
      NULLIF(TRIM(state), '') AS state,
      NULLIF(TRIM(country), '') AS country,
      COALESCE(times_called, 0) AS times_called
    FROM contacts
    WHERE hidden IS NOT TRUE
      AND company_type IS DISTINCT FROM 'rejected'
      AND (mobile_phone IS NOT NULL OR work_direct_phone IS NOT NULL OR corporate_phone IS NOT NULL)
      AND (
        call_outcome IS NULL
        OR (call_outcome = 'didnt_pick_up' AND retry_at IS NOT NULL AND retry_at <= NOW())
      )
  )
  SELECT json_build_object(
    'total', (SELECT COUNT(*) FROM callable),
    'countries', COALESCE(
      (SELECT json_agg(json_build_object('name', name, 'count', cnt) ORDER BY cnt DESC, name ASC)
       FROM (SELECT country AS name, COUNT(*) AS cnt FROM callable WHERE country IS NOT NULL GROUP BY country) t),
      '[]'::json),
    'states', COALESCE(
      (SELECT json_agg(json_build_object('name', name, 'count', cnt) ORDER BY cnt DESC, name ASC)
       FROM (SELECT state AS name, COUNT(*) AS cnt FROM callable WHERE state IS NOT NULL GROUP BY state) t),
      '[]'::json),
    'cities', COALESCE(
      (SELECT json_agg(json_build_object('name', name, 'count', cnt) ORDER BY cnt DESC, name ASC)
       FROM (SELECT city AS name, COUNT(*) AS cnt FROM callable WHERE city IS NOT NULL GROUP BY city) t),
      '[]'::json),
    'no_location', (SELECT COUNT(*) FROM callable WHERE city IS NULL AND state IS NULL AND country IS NULL),
    'call_counts', (SELECT json_build_object(
        'never', COUNT(*) FILTER (WHERE times_called = 0),
        'once', COUNT(*) FILTER (WHERE times_called = 1),
        'twice', COUNT(*) FILTER (WHERE times_called = 2),
        'three_plus', COUNT(*) FILTER (WHERE times_called >= 3)
      ) FROM callable)
  );
$$;

-- ============================================================
-- 2. Distinct location values for filter dropdowns
-- ============================================================

CREATE OR REPLACE FUNCTION get_distinct_locations()
RETURNS JSON
LANGUAGE sql
STABLE
AS $$
  SELECT json_build_object(
    'cities', COALESCE(
      (SELECT json_agg(v ORDER BY v)
       FROM (SELECT DISTINCT city AS v FROM contacts
             WHERE city IS NOT NULL AND city <> '' AND company_type <> 'rejected') t),
      '[]'::json),
    'states', COALESCE(
      (SELECT json_agg(v ORDER BY v)
       FROM (SELECT DISTINCT state AS v FROM contacts
             WHERE state IS NOT NULL AND state <> '' AND company_type <> 'rejected') t),
      '[]'::json),
    'countries', COALESCE(
      (SELECT json_agg(v ORDER BY v)
       FROM (SELECT DISTINCT country AS v FROM contacts
             WHERE country IS NOT NULL AND country <> '' AND company_type <> 'rejected') t),
      '[]'::json)
  );
$$;

-- ============================================================
-- 3. Company summaries for the companies page
-- ============================================================
-- "First non-empty" per field mirrors the old Python grouping, which took
-- the first truthy value it encountered per company.

CREATE OR REPLACE FUNCTION get_company_summaries(p_search TEXT DEFAULT NULL)
RETURNS JSON
LANGUAGE sql
STABLE
AS $$
  SELECT COALESCE(json_agg(row_to_json(s) ORDER BY s.contact_count DESC, s.company_name ASC), '[]'::json)
  FROM (
    SELECT
      company_name,
      (array_agg(NULLIF(website, '')) FILTER (WHERE NULLIF(website, '') IS NOT NULL))[1] AS website,
      (array_agg(NULLIF(company_linkedin_url, '')) FILTER (WHERE NULLIF(company_linkedin_url, '') IS NOT NULL))[1] AS company_linkedin_url,
      (array_agg(NULLIF(company_description, '')) FILTER (WHERE NULLIF(company_description, '') IS NOT NULL))[1] AS company_description,
      (array_agg(NULLIF(employees, '')) FILTER (WHERE NULLIF(employees, '') IS NOT NULL))[1] AS employees,
      (array_agg(NULLIF(industry_tag, '')) FILTER (WHERE NULLIF(industry_tag, '') IS NOT NULL))[1] AS industry_tag,
      (array_agg(NULLIF(city, '')) FILTER (WHERE NULLIF(city, '') IS NOT NULL))[1] AS city,
      (array_agg(NULLIF(state, '')) FILTER (WHERE NULLIF(state, '') IS NOT NULL))[1] AS state,
      (array_agg(NULLIF(country, '')) FILTER (WHERE NULLIF(country, '') IS NOT NULL))[1] AS country,
      COUNT(*)::int AS contact_count,
      ROUND(AVG(score))::int AS avg_score
    FROM contacts
    WHERE company_type <> 'rejected'
      AND hidden IS NOT TRUE
      AND company_name <> ''
      AND (p_search IS NULL OR company_name ILIKE '%' || p_search || '%')
    GROUP BY company_name
  ) s;
$$;
