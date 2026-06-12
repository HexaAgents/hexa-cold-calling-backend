# Repositories — Data Access Layer

Repositories are the **only layer that touches the database**. Every Supabase query in the application lives inside one of these files. No router, service, or task module ever builds a query directly — they call a repository function instead.

Every repository function takes a **`supabase.Client` as its first argument**. The repository never creates or fetches its own client. This is **Dependency Inversion** — the caller (a service or router) owns the connection and passes it in, which makes every function trivially testable with a mock client.

Each file maps to **one database table** (Single Responsibility). `contact_repo` touches `contacts`, `call_log_repo` touches `call_logs`, and so on. If a feature requires data from two tables, the service layer calls two repositories — the repositories themselves never join across files.

---

## Files

| File | Table | Purpose |
|---|---|---|
| `contact_repo.py` | `contacts` | CRUD + filtered listing, score lookups, SMS due queries, user queue, stale claim release, company grouping, interacted contacts |
| `call_log_repo.py` | `call_logs` | Create logs, fetch per-contact history, same-day check |
| `note_repo.py` | `notes` | CRUD for free-text notes linked to contacts |
| `settings_repo.py` | `settings` | Read/update the single global settings row |
| `import_batch_repo.py` | `import_batches` | Track CSV import jobs (create, update, recent list) |
| `email_repo.py` | `user_gmail_tokens`, `email_logs` | Gmail OAuth token storage, email send logging |
| `email_tracking_repo.py` | `tracked_emails` | Upsert synced Gmail messages, contact summaries with reply status, per-contact thread retrieval |
| `todo_repo.py` | `todos`, `todo_assignees` | CRUD for the standalone team to-do list; lists unfinished tasks before finished tasks, orders each group by closest due date (no-due-date last), hydrates multi-assignee lists, and mirrors the first assignee into legacy columns during the transition. |
| `company_flag_repo.py` | `company_flags` | One informational flag per company (get/upsert/delete) keyed by normalized company name; surfaced as a call-tracker warning, never affects pool eligibility |

---

## contact_repo.py

### `VALID_SORT_COLUMNS` (line 6)

```python
VALID_SORT_COLUMNS = {"created_at", "call_occasion_count", "call_outcome", "score"}
```

A frozen allowlist of column names that the API will accept for sorting. This prevents SQL-injection-style attacks through the `sort_by` query parameter — any value not in the set is silently replaced with `"created_at"` inside `list_contacts()`. The set is defined at module level so it is allocated once and shared across every request.

### `list_contacts()` (lines 9-32)

```python
def list_contacts(
    db: Client,
    sort_by: str = "created_at",
    sort_order: str = "asc",
    outcome_filter: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict], int]:
```

The main listing endpoint behind `GET /contacts`. It returns a tuple of `(rows, total_count)` so the router can build a paginated response.

**Line 17-18 — Sort validation:** If the caller passes a `sort_by` value that is not in `VALID_SORT_COLUMNS`, the function silently resets it to `"created_at"`. This is a defence-in-depth measure — the Pydantic schema at the router level may already constrain the value, but the repo enforces it again so the rule cannot be bypassed if called from a different entry point.

**Line 20 — Base query:** `db.table("contacts").select("*", count="exact")` selects every column and tells Supabase to include the total row count in the response headers. The count is essential for the frontend to render page numbers.

**Line 22-23 — Optional filter:** If `outcome_filter` is provided (e.g. `"interested"`, `"not_interested"`), a `.eq("call_outcome", outcome_filter)` clause is appended. When it is `None`, no filter is applied and all contacts are returned. This pattern keeps the function flexible — one function serves both filtered and unfiltered views.

**Line 25-26 — Sort direction:** `sort_order` is normalized to a boolean `desc` by comparing the lowered string to `"desc"`. The `query.order()` call uses this boolean. Defaulting to ascending means the first page shows the oldest contacts, which matches the typical import order.

**Lines 28-29 — Pagination via `range()`:** The offset is calculated as `(page - 1) * per_page`. Supabase's `.range(start, end)` is inclusive on both ends, so the end index is `offset + per_page - 1`. For page 1 with 50 per page, this resolves to `.range(0, 49)`, returning exactly 50 rows.

**Lines 31-32 — Execute and return:** `result.data` contains the rows; `result.count` contains the total matching count (from the `count="exact"` parameter). Both fall back to empty/zero if the response is `None`.

### `get_contact()` (lines 35-37)

```python
def get_contact(db: Client, contact_id: str) -> dict | None:
    result = db.table("contacts").select("*").eq("id", contact_id).single().execute()
    return result.data
```

Fetches a single contact by primary key. The `.single()` call tells Supabase to return exactly one row (not a list) and raises an error if zero or multiple rows match. Returns the dict directly — the caller checks for `None`.

### `create_contacts_batch()` (lines 40-44)

```python
def create_contacts_batch(db: Client, contacts: list[dict]) -> list[dict]:
    if not contacts:
        return []
    result = db.table("contacts").insert(contacts).execute()
    return result.data or []
```

Inserts multiple contacts in a single round-trip. The early return on an empty list avoids sending a pointless request to Supabase. This is used by the CSV import pipeline, which may build a batch of hundreds of rows from one uploaded file.

### `update_contact()` (lines 47-49)

```python
def update_contact(db: Client, contact_id: str, data: dict) -> dict | None:
    result = db.table("contacts").update(data).eq("id", contact_id).execute()
    return result.data[0] if result.data else None
```

Partial update — only the keys present in `data` are written. The `.eq("id", contact_id)` clause scopes the update to one row. Returns the updated row or `None` if the id did not match.

### `delete_contact()` (lines 52-54)

```python
def delete_contact(db: Client, contact_id: str) -> bool:
    result = db.table("contacts").delete().eq("id", contact_id).execute()
    return bool(result.data)
```

Deletes a contact by id. Returns `True` if a row was actually deleted, `False` if nothing matched.

### `get_existing_scores()`

```python
def get_existing_scores(db: Client, websites: list[str]) -> dict[str, dict]:
```

Called during CSV import scoring to **avoid re-scoring websites that were already scored** in a previous import. When a new CSV is uploaded, many rows may share a website with contacts that were imported before. Scoring is expensive (Exa API call + OpenAI API call per website), so this function returns a lookup map of `website → scoring result` for all websites that already have a non-null score.

**Early exit:** If the website list is empty, return an empty dict immediately. This avoids an `IN ()` query that some databases reject.

**Query:** Selects only the scoring-related columns (`website`, `score`, `company_type`, `rationale`, `rejection_reason`, `exa_scrape_success`, `company_description`) for rows whose `website` is in the provided list AND whose `score` is not null. Websites are queried in chunks of `_SCORE_QUERY_CHUNK` (50) to keep the `IN` clause bounded. The `.not_.is_("score", "null")` clause filters out contacts that were imported but haven't been scored yet.

**Best-verdict selection:** Multiple contacts can share the same website, and a website can carry conflicting verdicts (e.g. old rejected rows plus a newer passing row after re-evaluation under an updated prompt). The loop keeps the **best** row per website using `_score_row_rank()` — distributor rows beat rejected rows, then higher scores win. This ensures the import service's cache-reuse policy (`_is_reusable_score()` in `import_service.py`: reuse only `distributor` rows scoring >= 40) sees a passing verdict when one exists, instead of needlessly re-scoring a company because a stale rejected row happened to be returned first.

### `contact_identity_key()` and `get_existing_identity_keys()`

```python
def contact_identity_key(row: dict) -> tuple[str, str, str] | None:
def get_existing_identity_keys(db: Client) -> tuple[set, set]:
```

The contact-deduplication primitives used by the CSV import.

`contact_identity_key()` normalizes a contact (or mapped CSV row) into a `(first_name, last_name, person_linkedin_url)` tuple: lowercased, whitespace-stripped, with trailing slashes removed from the LinkedIn URL. Returns `None` when the row has none of the identity fields, so identity-less rows are never deduped against each other.

`get_existing_identity_keys()` pages through the entire contacts table (`_IDENTITY_PAGE` = 1000 rows per request, selecting only the identity columns plus `company_type` and `hidden`) and returns **two sets**:

- **`passing_keys`** — identities with at least one *live* contact (not `company_type = "rejected"`, not `hidden`). The import skips these rows entirely so the same person is never inserted, scored, or enriched twice.
- **`failed_only_keys`** — identities that exist *only* as rejected/hidden rows. The import lets these rows through so the company can be re-evaluated under the current scoring prompt; if it still fails, no second rejected copy is stored.

### `get_contacts_needing_sms()` (lines 76-86)

```python
def get_contacts_needing_sms(db: Client) -> list[dict]:
```

Called by the SMS scheduler background task every 60 seconds. It finds contacts whose scheduled SMS is **due for delivery**. Three conditions must all be true:

1. **`messaging_status = "to_be_messaged"`** — The contact has been flagged for messaging but hasn't been sent one yet.
2. **`sms_scheduled_at IS NOT NULL`** — A specific send time was set (via the `schedule_sms` service function).
3. **`sms_scheduled_at <= now()`** — The scheduled time has arrived or passed. The `now()` is evaluated server-side by Supabase/Postgres, so clock skew between the backend and database is not a concern.

Returns full contact rows (`select("*")`) because the downstream `sms_service.send_sms()` needs the phone number, name, and company for template rendering.

---

## call_log_repo.py

### `create_call_log()` (lines 8-10)

```python
def create_call_log(db: Client, data: dict) -> dict:
    result = db.table("call_logs").insert(data).execute()
    return result.data[0] if result.data else {}
```

Inserts a single call log row. The `data` dict is built by the call service and includes `contact_id`, `user_id`, `call_date`, `call_method`, `phone_number_called`, `outcome`, and `is_new_occasion`. Returns the inserted row (with its server-generated `id` and `created_at`).

### `get_call_logs_for_contact()` (lines 13-21)

```python
def get_call_logs_for_contact(db: Client, contact_id: str) -> list[dict]:
```

Returns all call logs for a specific contact, ordered newest-first (`desc=True` on `created_at`). This powers the call history panel in the frontend. No pagination — call logs per contact are expected to be a small number (tens, not thousands).

### `has_call_today()` (lines 24-33)

```python
def has_call_today(db: Client, contact_id: str) -> bool:
    today = date.today().isoformat()
    result = (
        db.table("call_logs")
        .select("id", count="exact")
        .eq("contact_id", contact_id)
        .eq("call_date", today)
        .execute()
    )
    return (result.count or 0) > 0
```

Checks whether the given contact has **already been called today**. This is critical for the **call occasion tracking** system. A "call occasion" is defined as a unique day on which a contact was called. If `has_call_today()` returns `False`, the call service knows this call starts a new occasion and increments `call_occasion_count` on the contact. If it returns `True`, the call is recorded but the occasion count stays the same (multiple calls on the same day count as one occasion).

**Line 25** — `date.today().isoformat()` produces a string like `"2026-04-20"`, which matches the `call_date` column format.

**Line 28** — `select("id", count="exact")` is an optimization: we don't need the row data, just the count. Selecting only `id` minimizes data transfer. The `count="exact"` tells Supabase to return a count in the response metadata.

**Line 33** — The count is compared against zero to return a boolean.

---

## note_repo.py

### `get_notes_for_contact()` (lines 6-14)

```python
def get_notes_for_contact(db: Client, contact_id: str) -> list[dict]:
```

Returns all notes for a contact, ordered newest-first. Like call logs, notes are expected to be a small set per contact, so no pagination is needed.

### `create_note()` (lines 17-19)

```python
def create_note(db: Client, data: dict) -> dict:
    result = db.table("notes").insert(data).execute()
    return result.data[0] if result.data else {}
```

Inserts a single note. The `data` dict includes `contact_id`, `user_id`, `content`, and `note_date` — assembled by the note service before calling this function.

### `update_note()` (lines 22-24)

```python
def update_note(db: Client, note_id: str, data: dict) -> dict | None:
    result = db.table("notes").update(data).eq("id", note_id).execute()
    return result.data[0] if result.data else None
```

Partial update scoped to one note by id. Only the provided fields are overwritten.

### `delete_note()` (lines 27-29)

```python
def delete_note(db: Client, note_id: str) -> bool:
    result = db.table("notes").delete().eq("id", note_id).execute()
    return bool(result.data)
```

Deletes a note by id and returns whether a row was actually removed.

---

## settings_repo.py

### `get_settings()` (lines 6-8)

```python
def get_settings(db: Client) -> dict:
    result = db.table("settings").select("*").limit(1).single().execute()
    return result.data or {}
```

Fetches the single global settings row. The `settings` table is designed to hold exactly one row (a singleton pattern). `.limit(1).single()` is a defensive measure — it ensures only one row is returned and that the result is a dict rather than a list.

### `update_settings()` (lines 11-13)

```python
def update_settings(db: Client, settings_id: str, data: dict) -> dict | None:
    result = db.table("settings").update(data).eq("id", settings_id).execute()
    return result.data[0] if result.data else None
```

Updates the settings row by its id. The `data` dict may contain `sms_call_threshold` (how many call occasions before an SMS prompt appears) and/or `sms_template` (the message body template with placeholders like `<first_name>`).

---

## import_batch_repo.py

### `create_batch()` (lines 6-8)

```python
def create_batch(db: Client, data: dict) -> dict:
    result = db.table("import_batches").insert(data).execute()
    return result.data[0] if result.data else {}
```

Creates a new import batch record when a CSV upload starts. The initial `data` contains the `user_id`, `filename`, and `total_rows` from the parsed CSV. `status` starts as `"processing"`.

### `update_batch()` (lines 11-13)

```python
def update_batch(db: Client, batch_id: str, data: dict) -> dict | None:
    result = db.table("import_batches").update(data).eq("id", batch_id).execute()
    return result.data[0] if result.data else None
```

Updates a batch's progress or final state. Called multiple times during import: once to set `processed_rows`/`stored_rows`/`discarded_rows` counts, and once at the end to set `status` to `"completed"` or `"failed"`.

### `get_batch()` (lines 16-18)

```python
def get_batch(db: Client, batch_id: str) -> dict | None:
    result = db.table("import_batches").select("*").eq("id", batch_id).single().execute()
    return result.data
```

Fetches a single batch by id. Used by the frontend to poll the status of an in-progress import.

### `get_recent_batches()` (lines 21-29)

```python
def get_recent_batches(db: Client, limit: int = 10) -> list[dict]:
```

Returns the most recent import batches, ordered newest-first, capped at `limit` (default 10). Powers the import history view in the frontend.

---

## company_flag_repo.py

Backs the company-flag feature (migration `032_company_flags.sql`): a single informational flag per company shown as a warning banner on the call tracker. Flags **never** affect whether contacts are claimable — they only annotate.

### `company_flag_key()`

```python
def company_flag_key(company_name: str) -> str:
    return (company_name or "").strip().lower()
```

Normalizes a company name into the unique `company_key` used by the table. Matches how the companies pages group contacts (by name), so a flag set from any contact of "ACME Corp" applies to every contact whose `company_name` normalizes to `"acme corp"`. Handles `None` and whitespace-only input by returning `""`.

### `get_flag()`

Returns the flag row for a company or `None`. Short-circuits without touching the database when the normalized key is empty (e.g. a contact with a blank company name can never be flagged).

### `upsert_flag()`

```python
def upsert_flag(db, company_name, reason, details, flagged_by, flagged_by_name) -> dict:
```

Creates or replaces the flag using `upsert(..., on_conflict="company_key")` — there is intentionally **one flag per company**, so re-flagging overwrites the previous reason/details rather than accumulating rows. Stores both the flagger's user id (`flagged_by`) and display name (`flagged_by_name`) so the banner can show who set the flag without a join. `updated_at` is refreshed on every upsert.

### `delete_flag()`

Deletes the flag by normalized key and returns `True` if a row was actually removed (the router translates `False` into a 404). Short-circuits on blank names like `get_flag()`.

---

## Design Principles (SOLID)

**Single Responsibility** — Each repository file is responsible for one database table. `contact_repo.py` never queries `call_logs`, and `call_log_repo.py` never queries `contacts`. If a service needs data from both, it calls both repositories separately.

**Dependency Inversion** — Repositories depend on the abstract `supabase.Client` interface passed in as a parameter. They never import `get_supabase()` or create a client themselves. This means:
- Unit tests can pass a mock client without touching any database.
- The same repository functions work with a service-role client (background tasks) or a user-scoped client (if row-level security were enabled).
- No global state or singletons inside the repository layer.

**Open/Closed** — Adding a new query (e.g. `get_contacts_by_score_range()`) means adding a new function, not modifying existing ones. The existing functions remain untouched and their callers unaffected.
