# Schemas — API Request/Response Models

This directory contains Pydantic models that define the exact shape of every API request and response. They act as the contract between the frontend and the backend — any data crossing the API boundary must conform to one of these schemas.

## SOLID Principle: Interface Segregation

Each resource has separate schemas for different operations. `ContactOut` (read) has 30 fields. `ContactUpdate` (write) only exposes 2 mutable fields. The frontend never receives more structure than it needs for a given operation, and the backend rejects payloads that try to set fields they shouldn't.

---

## contact.py

### `ContactOut`

The full read model for a contact, returned by `GET /contacts` and `GET /contacts/{id}`.

- **Lines 9–30**: Every column from the `contacts` database table is represented as a typed field. Fields that can be null in the database are typed as `str | None = None`. The `company_name` field is the only required string — it maps to the `NOT NULL` constraint in the schema.
- **`score: int | None`**: Null when scoring hasn't run yet (e.g., a failed import row).
- **`exa_scrape_success: bool = False`**: Whether the Exa API returned usable content (>100 chars).
- **`scoring_failed: bool = False`**: True when scoring errored after retry — these rows are kept for manual review.
- **`call_occasion_count: int = 0`**: Number of separate days the contact has been called.
- **`messaging_status: str | None`**: Either `"to_be_messaged"` (SMS scheduled) or `"message_sent"`.
- **`created_at: datetime | None`**: Set by the database `DEFAULT NOW()`, used for sort-by-import-order.

### `ContactUpdate`

The write model for `PATCH /contacts/{id}`. Only two fields are mutable from the API:

- **`call_outcome: str | None`**: Set after logging a call — one of `"didnt_pick_up"`, `"not_interested"`, `"interested"`.
- **`messaging_status: str | None`**: Set when scheduling or sending SMS.

All other contact fields are set internally by the import or scoring process and cannot be modified via the API. This enforces data integrity — you can't accidentally change a contact's score or company name through the API.

### `ContactListParams`

Defines the query parameters for `GET /contacts`. Not used directly as a Pydantic model in the router (the router uses `Query()` parameters instead), but documents the expected parameter shape:

- **`sort_by`**: Which column to sort on. Validated against an allowlist in `contact_repo.py`.
- **`sort_order`**: `"asc"` or `"desc"`.
- **`outcome_filter`**: If set, only returns contacts with this `call_outcome` value.
- **`page` / `per_page`**: Pagination. Defaults to page 1, 50 per page.

### `ContactListOut`

Wraps a paginated response:

- **`contacts: list[ContactOut]`**: The current page of results.
- **`total: int`**: Total count across all pages (from Supabase's `count="exact"`).
- **`page` / `per_page`**: Echoed back so the frontend knows its position.

---

## call.py

### `CallLogCreate`

Request body for `POST /calls/log`:

- **`contact_id: str`**: UUID of the contact being called.
- **`call_method: str`**: Either `"browser"` (WebRTC via Twilio Client) or `"bridge"` (Twilio calls user's phone first).
- **`phone_number_called: str | None`**: Which of the contact's numbers was dialed. Optional because the call might not connect.
- **`outcome: str`**: Required — one of `"didnt_pick_up"`, `"not_interested"`, `"interested"`. The frontend enforces selection before submission.

### `CallLogOut`

Read model for a single call log entry:

- **`call_date: str`**: ISO date string (e.g., `"2026-04-20"`). Stored as DATE in the database.
- **`is_new_occasion: bool`**: True if this was the first call to this contact today. Used by the frontend to decide whether to show the occasion count increment.

### `CallLogResponse`

Extended response from `POST /calls/log`:

- **`call_log: CallLogOut`**: The created call log.
- **`sms_prompt_needed: bool`**: If True, the frontend should show the SMS dialog. This is True when: (1) this was a new occasion, (2) the occasion count just reached the SMS threshold, and (3) SMS hasn't been sent yet.
- **`occasion_count: int`**: The updated total occasion count for this contact.

---

## note.py

### `NoteCreate` / `NoteUpdate`

Both contain a single `content: str` field. Kept as separate classes even though they're identical because they represent different operations — creating a new note vs editing an existing one. If validation rules diverge later (e.g., max length on create but not update), they can evolve independently.

### `NoteOut`

- **`note_date: str`**: The date the note was written (defaults to current date in the database).
- **`created_at` / `updated_at`**: Timestamps for audit purposes. `updated_at` is auto-set by the database trigger on `UPDATE`.

---

## settings.py

### `SettingsOut`

Read model for `GET /settings`. Returns the single global settings row:

- **`sms_call_threshold: int`**: After this many separate-day call occasions, the SMS prompt appears.
- **`sms_template: str`**: The message template with `<variable>` placeholders.

### `SettingsUpdate`

Write model for `PUT /settings`. Both fields are optional — you can update just the threshold, just the template, or both:

- Uses `model_dump(exclude_none=True)` in the router to only send changed fields to the database.

---

## import_batch.py

### `ImportBatchOut`

Tracks the progress and result of a CSV import:

- **`total_rows: int`**: How many valid rows were in the CSV (rows with a company_name).
- **`processed_rows: int`**: How many rows have been scored so far. Updated after each batch of 10.
- **`stored_rows: int`**: How many contacts were inserted into the database (score > 0 or scoring_failed).
- **`discarded_rows: int`**: How many were rejected (score = 0).
- **`status: str`**: One of `"processing"`, `"completed"`, `"failed"`.

The frontend polls `GET /imports/{id}/status` every 2 seconds during an import, using `processed_rows / total_rows` to render a progress bar.
