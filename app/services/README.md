# Services Layer

Services are the **business logic layer** of the application. They sit between **routers** (HTTP request handling) and **repositories** (database access), forming the middle tier of a three-layer architecture:

```
Router  →  Service  →  Repository  →  Supabase
(HTTP)     (logic)     (queries)      (database)
```

Routers never import repositories directly. Every database interaction flows through a service function, which may orchestrate multiple repository calls, call external APIs, enforce validation rules, or combine results before returning them to the router.

There are **5 service modules**, each owning a single domain:

| Module | Domain | External Dependencies |
|---|---|---|
| `scoring_service.py` | AI-powered company scoring | Exa API, OpenAI API |
| `import_service.py` | CSV upload and batch processing | Exa API, OpenAI API (via scoring_service) |
| `call_service.py` | Twilio voice calls and call logging | Twilio SDK |
| `sms_service.py` | SMS sending, scheduling, and background dispatch | Twilio SDK |
| `contact_service.py` | Contact CRUD delegation | None (pure delegation) |

---

## 1. `scoring_service.py` — Company Scoring

This service coordinates the two-step scoring pipeline: scrape a company's website with Exa, then pass the content to OpenAI for scoring.

### Imports

```python
from app.scoring.exa_client import fetch_company_info
from app.scoring.openai_scorer import score_company
```

- `fetch_company_info` — calls the Exa search API to retrieve textual content from a company's website.
- `score_company` — sends that text to OpenAI with a scoring prompt and returns structured scoring data (score, company_type, rationale, rejection_reason).

### `score_website(exa_api_key, openai_api_key, openai_model, website, company_name, job_title) → dict`

**Purpose:** Given a company's website URL and name, fetch its web content and produce a numeric score with metadata.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `exa_api_key` | `str` | API key for the Exa content-fetching service |
| `openai_api_key` | `str` | API key for OpenAI |
| `openai_model` | `str` | Model identifier (e.g. `gpt-4o`) |
| `website` | `str` | The company's website URL to scrape |
| `company_name` | `str` | Human-readable company name, sent to both Exa and OpenAI |
| `job_title` | `str` | The contact's job title, used by OpenAI to factor role relevance into the score |

**Line-by-line walkthrough:**

```python
website_text, exa_success = fetch_company_info(exa_api_key, website, company_name)
```

Calls Exa to scrape the website. Returns two values: `website_text` is the scraped textual content (may be empty on failure), and `exa_success` is a boolean indicating whether Exa successfully retrieved content. Even when Exa fails, execution continues — OpenAI will score with whatever text is available (possibly empty).

```python
score_data = score_company(
    api_key=openai_api_key,
    company_name=company_name,
    job_title=job_title,
    website_text=website_text,
    model=openai_model,
)
```

Sends the scraped text to OpenAI for scoring. `score_data` is a dict containing at minimum: `score` (int 0–100), `company_type` (str), `rationale` (str), and `rejection_reason` (str or None).

```python
return {
    **score_data,
    "exa_scrape_success": exa_success,
    "scoring_failed": False,
}
```

Merges the OpenAI scoring result with two additional flags. `exa_scrape_success` lets the caller know whether the score was based on real website content or empty input. `scoring_failed` is hardcoded to `False` here — the only place it becomes `True` is in `import_service.py` when an exception is caught during scoring.

---

## 2. `import_service.py` — CSV Upload Processing

This is the most complex service. It handles the full lifecycle of importing an Apollo CSV export: parsing, column mapping, deduplication by website, scoring, filtering, batch insertion, and progress tracking.

### Imports

```python
from app.config import settings
from app.repositories import contact_repo, import_batch_repo
from app.services.scoring_service import score_website
```

- `settings` — application config singleton containing API keys.
- `contact_repo` — repository for contacts table operations.
- `import_batch_repo` — repository for the `import_batches` progress-tracking table.
- `score_website` — the scoring pipeline from `scoring_service.py`, called for each unique website.

### `COLUMN_MAP` (module-level constant)

```python
COLUMN_MAP: dict[str, str] = {
    "First Name": "first_name",
    "Last Name": "last_name",
    "Title": "title",
    "Company Name": "company_name",
    "Person Linkedin Url": "person_linkedin_url",
    "Website": "website",
    "Company Linkedin Url": "company_linkedin_url",
    "# Employees": "employees",
    "City": "city",
    "Country": "country",
    "Email": "email",
    "Phone": "mobile_phone",
    "Mobile Phone": "mobile_phone",
    "Work Direct Phone": "work_direct_phone",
    "Corporate Phone": "corporate_phone",
}
```

Maps **Apollo CSV column headers** (left) to **database column names** (right). This is the single source of truth for the column translation. Key details:

- Both `"Phone"` and `"Mobile Phone"` map to the same DB column `"mobile_phone"`. This creates a potential collision handled by `_map_row()` (first non-empty value wins).
- Apollo-specific headers like `"# Employees"` and `"Person Linkedin Url"` are normalized to snake_case DB names.
- Any CSV column **not** present in this dict is silently discarded.

### `BATCH_SIZE = 10`

Controls how many rows are processed between progress updates. After every 10 rows, the `import_batches` table is updated with current counters so the frontend can poll for progress.

### `process_csv_upload(db, file_content, filename, user_id) → str`

**Purpose:** Parse a CSV file uploaded by the user, score every unique company, filter out zero-score contacts, insert qualifying contacts into the database, and track progress throughout. Returns the `batch_id` for the frontend to poll.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `db` | `Client` | Supabase client instance |
| `file_content` | `bytes` | Raw bytes of the uploaded CSV file |
| `filename` | `str` | Original filename, stored for audit/display |
| `user_id` | `str` | ID of the user who uploaded the file |

**Line-by-line walkthrough:**

```python
text = file_content.decode("utf-8-sig")
```

Decodes the raw bytes to a string. The `utf-8-sig` codec handles the BOM (Byte Order Mark) that Excel and some Apollo exports prepend to CSV files. Without this, the first column header would contain invisible `\ufeff` characters and fail to match `COLUMN_MAP`.

```python
reader = csv.DictReader(io.StringIO(text))
```

Creates a `csv.DictReader` that yields each row as a `{column_header: value}` dict. The `io.StringIO` wrapper converts the string to a file-like object that `csv.DictReader` requires.

```python
rows = [_map_row(row, reader.fieldnames or []) for row in reader]
```

Iterates every CSV row through `_map_row()` to translate Apollo column names to DB column names. The result is a list of dicts with DB-compatible keys.

```python
rows = [r for r in rows if r.get("company_name")]
```

Filters out any rows that have no `company_name` after mapping. A contact without a company name cannot be scored or meaningfully used, so it is discarded immediately.

```python
batch = import_batch_repo.create_batch(db, {
    "user_id": user_id,
    "filename": filename,
    "total_rows": len(rows),
    "status": "processing",
})
batch_id = batch["id"]
```

Creates a record in the `import_batches` table to track this import's progress. The initial status is `"processing"`. The returned `batch_id` (UUID) is used as a foreign key on every contact inserted from this batch, and is returned to the caller for progress polling.

```python
websites = list({r["website"] for r in rows if r.get("website")})
existing_scores = contact_repo.get_existing_scores(db, websites)
```

Collects all unique website URLs from the parsed rows (set comprehension deduplicates). Then queries the database for any contacts that already have scores for these websites. `existing_scores` is a `dict[str, dict]` mapping website URL → scoring data. This avoids re-calling Exa + OpenAI for companies that were scored in a previous import.

```python
stored = 0
discarded = 0
processed = 0
```

Initializes three counters: `stored` tracks contacts inserted into the DB, `discarded` tracks contacts filtered out (score = 0), and `processed` tracks total rows examined. These are written to `import_batches` on every batch boundary.

```python
for i in range(0, len(rows), BATCH_SIZE):
    batch_rows = rows[i : i + BATCH_SIZE]
    contacts_to_insert: list[dict] = []
```

Outer loop: processes rows in chunks of `BATCH_SIZE` (10). For each chunk, `contacts_to_insert` accumulates the contacts that pass the score filter and will be inserted together at the end of the chunk.

```python
for row in batch_rows:
    processed += 1
    website = row.get("website", "")
```

Inner loop: processes each row individually. Extracts the website URL for score lookup/computation.

```python
if website and website in existing_scores:
    score_data = existing_scores[website]
```

**Fast path:** If this website was already scored (either from the database or from an earlier row in this same import), reuse the cached score. No API calls are made.

```python
elif website:
    try:
        score_data = score_website(
            exa_api_key=settings.exa_api_key,
            openai_api_key=settings.openai_api_key,
            openai_model=settings.openai_model,
            website=website,
            company_name=row.get("company_name", ""),
            job_title=row.get("title", ""),
        )
    except Exception as exc:
        logger.error("Scoring failed for %s: %s", website, exc)
        score_data = {
            "score": 0,
            "company_type": "rejected",
            "rationale": f"Scoring error: {str(exc)[:200]}",
            "rejection_reason": "unclear",
            "exa_scrape_success": False,
            "scoring_failed": True,
        }
```

**Slow path:** Website exists but has no cached score. Calls the full Exa → OpenAI pipeline via `score_website()`. If any exception occurs (network timeout, API rate limit, malformed response), it is caught and a synthetic zero-score result is created with `scoring_failed: True`. The rationale stores the first 200 characters of the error message for debugging. The `scoring_failed` flag is critical — it causes this contact to still be inserted (see filter logic below) so the user can see it failed and retry.

```python
    if website not in existing_scores:
        existing_scores[website] = score_data
```

Caches the newly computed score so that if another row in this import shares the same website, it will hit the fast path instead of calling the APIs again.

```python
else:
    score_data = {
        "score": 0,
        "company_type": "rejected",
        "rationale": "No website provided",
        "rejection_reason": "unclear",
        "exa_scrape_success": False,
        "scoring_failed": False,
    }
```

**No-website path:** The row has no website URL at all. It receives a zero score and will be discarded (since `scoring_failed` is `False`, the filter below will exclude it).

```python
score_val = score_data.get("score", 0)
is_failed = score_data.get("scoring_failed", False)

if score_val > 0 or is_failed:
    contact = {**row, **score_data, "import_batch_id": batch_id}
    contacts_to_insert.append(contact)
    stored += 1
else:
    discarded += 1
```

The filtering decision. A contact is inserted if **either**: (a) the score is greater than 0 (the company qualifies), or (b) scoring failed (`is_failed` is `True`), because failed contacts should be visible in the UI for manual review or retry. Contacts with score = 0 and no failure are discarded — they represent companies that the AI determined are not relevant. The contact dict is built by merging the mapped CSV row with the score data and tagging it with `import_batch_id`.

```python
if contacts_to_insert:
    contact_repo.create_contacts_batch(db, contacts_to_insert)
```

Bulk-inserts all qualifying contacts from this chunk into the `contacts` table via the repository.

```python
import_batch_repo.update_batch(db, batch_id, {
    "processed_rows": processed,
    "stored_rows": stored,
    "discarded_rows": discarded,
})
```

Updates the `import_batches` record with current progress counters. The frontend polls this record to show a progress bar or status message.

```python
import_batch_repo.update_batch(db, batch_id, {"status": "completed"})
return batch_id
```

After all chunks are processed, marks the batch as `"completed"` and returns the batch ID to the router.

### `_map_row(row, fieldnames) → dict`

**Purpose:** Translate a single CSV row from Apollo column names to database column names, discarding any columns not in `COLUMN_MAP`.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `row` | `dict[str, Any]` | A single CSV row as parsed by `DictReader` |
| `fieldnames` | `list[str]` | The CSV header names, used for iteration order |

**Line-by-line walkthrough:**

```python
mapped: dict[str, Any] = {}
```

Initializes an empty dict that will hold the translated row.

```python
for csv_col in fieldnames:
    db_col = COLUMN_MAP.get(csv_col)
```

Iterates over every CSV column header in the order they appear in the file. Looks up the corresponding DB column name from `COLUMN_MAP`. If the CSV column is not in the map, `db_col` is `None`.

```python
    if db_col:
        value = (row.get(csv_col) or "").strip()
```

Only proceeds if this CSV column has a known mapping. Extracts the value, coalescing `None` to empty string, and strips leading/trailing whitespace.

```python
        if value:
            if db_col in mapped and mapped[db_col]:
                continue
            mapped[db_col] = value
```

Only stores non-empty values. The **collision guard** (`if db_col in mapped and mapped[db_col]: continue`) handles the case where multiple CSV columns map to the same DB column (e.g. both `"Phone"` and `"Mobile Phone"` map to `"mobile_phone"`). The **first non-empty value wins** — subsequent columns that map to the same DB column are skipped if the DB column already has a value.

```python
return mapped
```

Returns the translated row dict with DB-compatible keys.

---

## 3. `call_service.py` — Voice Calling and Call Logging

Handles Twilio voice integration (token generation, bridge calls) and the business logic around logging calls, tracking call occasions, and determining when to prompt the user to send an SMS.

### Imports

```python
from twilio.rest import Client as TwilioClient
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant

from app.repositories import call_log_repo, contact_repo, settings_repo
```

- `AccessToken` / `VoiceGrant` — Twilio JWT classes for generating browser-calling tokens.
- `TwilioClient` — the Twilio REST API client for making outbound calls.
- `call_log_repo` — repository for the `call_logs` table.
- `contact_repo` — repository for reading and updating contacts.
- `settings_repo` — repository for the global `settings` table (stores SMS threshold).

### `generate_twilio_token(user_id) → str`

**Purpose:** Generate a short-lived JWT that authorizes the frontend (running in the browser) to make outbound voice calls via Twilio.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `user_id` | `str` | Identifies the calling user; embedded in the token as the identity |

**Line-by-line walkthrough:**

```python
token = AccessToken(
    settings.twilio_account_sid,
    settings.twilio_api_key if hasattr(settings, "twilio_api_key") else settings.twilio_account_sid,
    settings.twilio_auth_token,
    identity=user_id,
)
```

Creates a Twilio `AccessToken`. The three positional arguments are the account SID, the API key SID, and the API key secret. The `hasattr` check provides a fallback: if the deployment hasn't configured a separate `twilio_api_key`, it falls back to using the account SID as the key SID (valid for test/main credentials). The `identity` ties the token to a specific user so Twilio can route incoming events correctly.

```python
voice_grant = VoiceGrant(
    outgoing_application_sid=settings.twilio_twiml_app_sid,
    incoming_allow=False,
)
```

Creates a `VoiceGrant` that allows outbound calls through the specified TwiML App (`twilio_twiml_app_sid`). Incoming calls are disabled (`incoming_allow=False`) because this system only makes outbound calls to contacts.

```python
token.add_grant(voice_grant)
return token.to_jwt()
```

Attaches the voice grant to the token and serializes it to a JWT string. The frontend stores this token and passes it to the Twilio Device SDK for browser-based calling.

### `initiate_bridge_call(phone_number, user_phone) → str`

**Purpose:** Start a Twilio bridge call — Twilio first dials the sales rep's phone, and when they answer, connects them to the contact.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `phone_number` | `str` | The contact's phone number (destination) |
| `user_phone` | `str` | The sales rep's own phone number (called first) |

**Line-by-line walkthrough:**

```python
client = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
```

Instantiates a Twilio REST client using account credentials from settings.

```python
call = client.calls.create(
    to=user_phone,
    from_=settings.twilio_phone_number,
    url=f"{settings.frontend_url}/api/twilio/connect?to={phone_number}",
)
```

Creates an outbound call **to the sales rep's phone** (`user_phone`). When the rep answers, Twilio fetches TwiML from the `url` — this endpoint instructs Twilio to `<Dial>` the contact's `phone_number`, bridging the two parties. The `from_` number is the Twilio phone number owned by the application.

```python
return call.sid
```

Returns the Twilio Call SID, a unique identifier the frontend can use to track or hang up the call.

### `log_call(db, contact_id, user_id, call_method, phone_number_called, outcome, callback_date) → dict`

**Purpose:** This is the most complex function in the calling domain. It records a call log, detects whether this is a new "occasion" (first call to this contact today), increments the occasion counter, checks whether the SMS threshold has been reached, and manages the retry/callback schedule for "didn't pick up" outcomes.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `db` | `Client` | Supabase client instance |
| `contact_id` | `str` | UUID of the contact that was called |
| `user_id` | `str` | UUID of the user who made the call |
| `call_method` | `str` | How the call was made (e.g. `"browser"`, `"bridge"`, `"manual"`) |
| `phone_number_called` | `str \| None` | The actual phone number dialed, or None if unknown |
| `outcome` | `str` | Call outcome (e.g. `"didnt_pick_up"`, `"not_interested"`, `"interested"`) |
| `callback_date` | `str \| None` | Optional ISO date string for a per-contact callback override. When provided and outcome is `"didnt_pick_up"`, this date is used as `retry_at` instead of computing from `settings.retry_days`. Defaults to `None`. |

**Returns:** A dict with six keys: `call_log`, `is_new_occasion`, `sms_prompt_needed`, `occasion_count`, `times_called`, `retry_at`.

**Line-by-line walkthrough:**

```python
already_called_today = call_log_repo.has_call_today(db, contact_id)
is_new_occasion = not already_called_today
```

Queries the `call_logs` table to check if there is already a call logged for this `contact_id` with today's date. An "occasion" represents a unique day on which a contact was called. If the contact was already called today, this call is part of the same occasion (e.g. a redial). If not, it is a new occasion. This distinction matters for the SMS threshold logic.

```python
call_data = {
    "contact_id": contact_id,
    "user_id": user_id,
    "call_date": date.today().isoformat(),
    "call_method": call_method,
    "phone_number_called": phone_number_called,
    "outcome": outcome,
    "is_new_occasion": is_new_occasion,
}
call_log = call_log_repo.create_call_log(db, call_data)
```

Builds the call log payload and inserts it into the `call_logs` table via the repository. The `is_new_occasion` flag is stored on the log itself for historical reference.

```python
contact = contact_repo.get_contact(db, contact_id)
occasion_count = contact.get("call_occasion_count", 0) if contact else 0
```

Fetches the current contact record to read its `call_occasion_count` — the running total of unique days this contact has been called. Defaults to `0` if the field is missing or the contact is not found.

```python
update_data: dict = {"call_outcome": outcome}
if is_new_occasion:
    occasion_count += 1
    update_data["call_occasion_count"] = occasion_count
```

Always updates the contact's `call_outcome` to reflect the latest call result. If this is a new occasion, increments the occasion counter and includes it in the update payload.

```python
contact_repo.update_contact(db, contact_id, update_data)
```

Persists the contact updates (outcome and possibly the incremented occasion count).

```python
sms_prompt_needed = False
if is_new_occasion and not (contact or {}).get("sms_sent", False):
    global_settings = settings_repo.get_settings(db)
    threshold = global_settings.get("sms_call_threshold", 3)
    if occasion_count >= threshold:
        sms_prompt_needed = True
```

The SMS threshold check. This block only fires when **all three conditions** are met:

1. **New occasion** — only check on the first call of a new day, not on redials.
2. **SMS not already sent** — if `sms_sent` is `True` on the contact, they already received an SMS and should not be prompted again.
3. **Threshold reached** — the `call_occasion_count` (after incrementing) must meet or exceed the `sms_call_threshold` from the global settings table (defaults to 3).

When all conditions are met, `sms_prompt_needed` is set to `True`, signaling the frontend to show an SMS prompt dialog to the user.

```python
return {
    "call_log": call_log,
    "is_new_occasion": is_new_occasion,
    "sms_prompt_needed": sms_prompt_needed,
    "occasion_count": occasion_count,
    "times_called": times_called,
    "retry_at": retry_at_value,
}
```

Returns all six pieces of information the router needs: the created call log record, whether a new occasion was counted, whether the frontend should prompt for SMS, the current occasion count, total times called, and the confirmed callback date (or `None` for non-retry outcomes).

---

## 4. `sms_service.py` — SMS Sending and Scheduling

Handles SMS template rendering, immediate sending, scheduling for future delivery, and background processing of scheduled messages.

### Imports

```python
from twilio.rest import Client as TwilioClient

from app.repositories import contact_repo, settings_repo
```

- `TwilioClient` — Twilio REST client for sending SMS messages.
- `contact_repo` — for reading contact data and updating SMS status fields.
- `settings_repo` — for fetching the SMS template from the global settings table.

### `render_template(template, contact) → str`

**Purpose:** Replace `<variable>` placeholders in an SMS template string with actual values from a contact record.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `template` | `str` | The SMS template text containing `<variable>` placeholders |
| `contact` | `dict` | The contact record whose values will be substituted |

**Line-by-line walkthrough:**

```python
replacements = {
    "<first_name>": contact.get("first_name") or "",
    "<last_name>": contact.get("last_name") or "",
    "<company_name>": contact.get("company_name") or "",
    "<title>": contact.get("title") or "",
    "<website>": contact.get("website") or "",
}
```

Builds a lookup dict mapping each supported placeholder to the contact's corresponding value. The `or ""` ensures that `None` values become empty strings rather than the literal text `"None"` in the final message. Five placeholders are supported: first name, last name, company name, job title, and website.

```python
result = template
for placeholder, value in replacements.items():
    result = result.replace(placeholder, value)
return result
```

Iterates over all placeholders and performs string replacement on the template. Returns the fully rendered message. Any placeholder not present in the template is harmlessly skipped. Any placeholder in the template not in the `replacements` dict remains as literal text (e.g. `<custom_field>` would not be replaced).

### `send_sms(db, contact_id) → dict`

**Purpose:** Send an SMS immediately to a contact. Fetches the contact, renders the template, sends via Twilio, and updates the contact's SMS status.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `db` | `Client` | Supabase client instance |
| `contact_id` | `str` | UUID of the contact to message |

**Line-by-line walkthrough:**

```python
contact = contact_repo.get_contact(db, contact_id)
if not contact:
    raise ValueError(f"Contact {contact_id} not found")
```

Fetches the contact from the database. Raises `ValueError` if the contact does not exist — this surfaces as an HTTP error in the router.

```python
phone = contact.get("mobile_phone")
if not phone:
    raise ValueError(f"Contact {contact_id} has no mobile phone number")
```

Extracts the mobile phone number. Raises `ValueError` if missing — SMS cannot be sent without a destination number.

```python
global_settings = settings_repo.get_settings(db)
template = global_settings.get("sms_template", "")
body = render_template(template, contact)
```

Fetches the SMS template from the global settings table and renders it with the contact's data. If no template is configured, `template` defaults to an empty string and the SMS body will be empty.

```python
client = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
message = client.messages.create(
    to=phone,
    from_=settings.twilio_phone_number,
    body=body,
)
```

Creates a Twilio client and sends the SMS. `from_` is the application's Twilio phone number. `to` is the contact's mobile phone. `body` is the rendered template.

```python
contact_repo.update_contact(db, contact_id, {
    "sms_sent": True,
    "messaging_status": "message_sent",
    "sms_sent_after_calls": contact.get("call_occasion_count", 0),
})
```

Updates three fields on the contact after successful send:

- `sms_sent` → `True` — prevents future SMS prompts for this contact (checked in `call_service.log_call`).
- `messaging_status` → `"message_sent"` — the contact's current messaging state for UI display and filtering.
- `sms_sent_after_calls` — records how many call occasions occurred before the SMS was sent, useful for analytics (e.g. "on average, SMS is sent after N calls").

```python
logger.info("SMS sent to %s (contact %s): SID %s", phone, contact_id, message.sid)
return {"message_sid": message.sid, "body": body}
```

Logs the successful send and returns the Twilio message SID (for tracking/debugging) and the rendered body (for UI confirmation).

### `schedule_sms(db, contact_id, scheduled_at) → dict`

**Purpose:** Schedule an SMS for future delivery by updating the contact's messaging status and storing the scheduled datetime.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `db` | `Client` | Supabase client instance |
| `contact_id` | `str` | UUID of the contact to schedule a message for |
| `scheduled_at` | `datetime` | The future date/time when the SMS should be sent |

**Line-by-line walkthrough:**

```python
contact = contact_repo.get_contact(db, contact_id)
if not contact:
    raise ValueError(f"Contact {contact_id} not found")

if not contact.get("mobile_phone"):
    raise ValueError(f"Contact {contact_id} has no mobile phone number")
```

Same validation as `send_sms`: the contact must exist and must have a phone number. These checks happen at schedule time so the user gets immediate feedback rather than a silent failure when the background job runs.

```python
contact_repo.update_contact(db, contact_id, {
    "messaging_status": "to_be_messaged",
    "sms_scheduled_at": scheduled_at.isoformat(),
})
```

Updates two fields on the contact:

- `messaging_status` → `"to_be_messaged"` — flags this contact for pickup by the background scheduler.
- `sms_scheduled_at` — the ISO 8601 datetime string when the message should be sent. The background job compares this against the current time.

```python
return {"scheduled_at": scheduled_at.isoformat(), "contact_id": contact_id}
```

Returns confirmation data to the router.

### `process_scheduled_messages(db) → int`

**Purpose:** Background job function called by the scheduler (e.g. APScheduler cron). Finds all contacts whose scheduled SMS is due and sends them. Returns the count of successfully sent messages.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `db` | `Client` | Supabase client instance |

**Line-by-line walkthrough:**

```python
contacts = contact_repo.get_contacts_needing_sms(db)
```

Queries the `contacts` table for all contacts where `messaging_status = 'to_be_messaged'` and `sms_scheduled_at <= now()`. These are the contacts whose scheduled time has arrived.

```python
sent_count = 0

for contact in contacts:
    try:
        send_sms(db, contact["id"])
        sent_count += 1
    except Exception as exc:
        logger.error("Failed to send scheduled SMS to contact %s: %s", contact["id"], exc)

return sent_count
```

Iterates over every due contact and calls `send_sms()` for each one. If any individual send fails (invalid phone number, Twilio error, contact deleted between query and send), the exception is logged but does **not** halt processing — remaining contacts are still attempted. `send_sms()` handles updating the contact's `messaging_status` to `"message_sent"` on success, so failed contacts retain `"to_be_messaged"` status and will be retried on the next scheduler run. Returns the total number of successfully sent messages.

---

## 5. `contact_service.py` — Contact CRUD Delegation

This is intentionally a thin delegation layer. Every function passes its arguments directly to the corresponding `contact_repo` function without additional logic.

### Import

```python
from app.repositories import contact_repo
```

The only dependency is the contact repository.

### Why this layer exists

Without `contact_service.py`, routers would import `contact_repo` directly, breaking the three-layer architecture:

```
Router → Service → Repository    ✓  consistent layering
Router → Repository              ✗  routers coupled to data layer
```

Even though the functions are pure pass-throughs today, having the service layer means:

- Future business rules (validation, authorization, event emission) can be added without touching routers.
- All routers follow the same import pattern: `from app.services import X`.
- Testing can mock the service layer uniformly rather than mixing service and repo mocks.

### `list_contacts(db, sort_by, sort_order, outcome_filter, page, per_page) → tuple[list[dict], int]`

Delegates to `contact_repo.list_contacts()` with the same parameters. Returns a tuple of (contact list, total count) for paginated display.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `db` | `Client` | — | Supabase client instance |
| `sort_by` | `str` | `"created_at"` | Column to sort by |
| `sort_order` | `str` | `"asc"` | Sort direction (`"asc"` or `"desc"`) |
| `outcome_filter` | `str \| None` | `None` | If set, filters contacts by `call_outcome` value |
| `page` | `int` | `1` | Page number for pagination (1-indexed) |
| `per_page` | `int` | `50` | Number of contacts per page |

### `get_contact(db, contact_id) → dict | None`

Delegates to `contact_repo.get_contact()`. Returns the contact dict or `None` if not found.

### `update_contact(db, contact_id, data) → dict | None`

Delegates to `contact_repo.update_contact()`. Applies the partial update in `data` to the specified contact. Returns the updated contact or `None`.

### `delete_contact(db, contact_id) → bool`

Delegates to `contact_repo.delete_contact()`. Returns `True` if the contact was deleted, `False` if it did not exist.

---

## Architecture: SOLID Principles

### Single Responsibility

Each service module handles exactly one domain:

- `scoring_service` — company scoring only
- `import_service` — CSV parsing and batch import only
- `call_service` — voice calls and call logging only
- `sms_service` — SMS messaging only
- `contact_service` — contact CRUD only

### Open/Closed

Adding a new scoring algorithm (e.g. switching from OpenAI to Anthropic) only requires changes in `scoring_service.py` and the underlying `openai_scorer.py` module. No router, import service, or other service needs modification.

### Dependency Inversion

Services depend on **repository functions** (abstractions over database queries), never on the Supabase client directly. For example, `call_service.py` calls `call_log_repo.has_call_today()` rather than constructing a Supabase query inline. This means:

- The database implementation can change without touching business logic.
- Services are testable by mocking repository functions.
- Repository query logic is reusable across services.

### Interface Segregation

Each repository exposes only the operations its consumers need. `call_log_repo` provides `has_call_today()` and `create_call_log()` — it does not expose a generic "run any query" interface.

### Liskov Substitution

All service functions accept the `supabase.Client` type. Any client that satisfies the Supabase `Client` interface (including test doubles) can be substituted without breaking service logic.
