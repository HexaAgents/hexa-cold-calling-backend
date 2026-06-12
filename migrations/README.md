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

## To-Do Tables

`026_todos.sql` creates the `todos` table. `027_todo_multi_assignees.sql` adds `todo_assignees` with one row per assigned user. The application now treats `todo_assignees` as canonical and mirrors the first assignee into `todos.assigned_to_id` / `todos.assigned_to_name` so older API rows and UI code remain readable during the transition.

## Adding a Migration

1. Create a new file using the next three-digit prefix, for example `028_add_example.sql`.
2. Keep the migration idempotent where practical (`IF NOT EXISTS`, safe backfills, named constraints).
3. Include any backfill needed for existing data in the same file.
4. Update this README when the migration introduces a new feature area or changes an existing contract.
5. Add or update repository, schema, and route tests for code that depends on the migration.
