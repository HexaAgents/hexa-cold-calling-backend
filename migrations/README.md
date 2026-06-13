# Database Migrations

This directory contains ordered Supabase/Postgres SQL migrations. Apply files in ascending numeric order and keep new files append-only with the next available number.

## Current Migration Areas

- `001_initial_schema.sql` through `004_add_contact_claim.sql`: base contacts, call tracking, claims, settings, notes, and early feature columns.
- `005_add_enriched_rows.sql` through `015_add_industry_tag.sql`: import progress, location filtering, retry/enrichment status, auth user RPC, timezone, hidden contacts, and industry tagging.
- `016_email.sql` through `020_email_tracking.sql`: Gmail OAuth tokens, email logs, and tracked email sync/thread data.
- `021_scheduled_calls.sql` through `025_silence_exhausted_contacts.sql`: scheduled callbacks, bad-number handling, filtered CSV download, and exhausted-contact cleanup/silencing.
- `026_todos.sql`: standalone team to-do list with task metadata and first-assignee compatibility fields.
- `027_todo_multi_assignees.sql`: canonical multi-assignee join table for to-do tasks.
- `028_add_discarded_csv.sql` and `030_add_input_csv.sql`: store the discarded-rows CSV and the original upload CSV on import batches for download.
- `029_reactivate_stale_didnt_pickup.sql`: shared-pool refeed of stale "didn't pick up" contacts (claimable by any caller) plus the reactivation function.
- `031_call_priority_order.sql`: claim queue priority — least-called first, then later local time of day, then higher score (replaces the old retries-first, score-only ordering).
- `032_company_flags.sql`: `company_flags` table — one informational flag per company (keyed by normalized company name) with a reason, optional details, and who flagged it. Surfaced as a warning banner on the call tracker; never removes contacts from the calling pool.
- `033_todo_time_estimates.sql`: AI time estimates for todos (feature since removed; columns dropped by `037_drop_todo_time_estimates.sql`).
- `034_search_indexes.sql`: pg_trgm extension, generated `contacts.search_text` column with a trigram GIN index (fast `%term%` contact search), trigram index on `company_name`, B-tree indexes on hot filter columns, and a partial composite index matching the `claim_next_contact` eligibility scan.
- `035_aggregate_rpcs.sql`: SQL aggregation RPCs (`get_callable_location_counts`, `get_distinct_locations`, `get_company_summaries`) replacing endpoints that fetched whole tables over PostgREST and aggregated in Python.
- `037_drop_todo_time_estimates.sql`: removes the AI time-estimate feature — drops `estimated_hours_min`, `estimated_hours_max`, `estimate_status`, and `actual_hours` from `todos`.

## To-Do Tables

`026_todos.sql` creates the `todos` table. `027_todo_multi_assignees.sql` adds `todo_assignees` with one row per assigned user. The application now treats `todo_assignees` as canonical and mirrors the first assignee into `todos.assigned_to_id` / `todos.assigned_to_name` so older API rows and UI code remain readable during the transition.

## Adding a Migration

1. Create a new file using the next three-digit prefix, for example `028_add_example.sql`.
2. Keep the migration idempotent where practical (`IF NOT EXISTS`, safe backfills, named constraints).
3. Include any backfill needed for existing data in the same file.
4. Update this README when the migration introduces a new feature area or changes an existing contract.
5. Add or update repository, schema, and route tests for code that depends on the migration.
