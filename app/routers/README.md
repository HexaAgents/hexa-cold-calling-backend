# Routers — API Endpoint Layer

This directory contains the 8 FastAPI router modules that define every HTTP endpoint in the Hexa Cold-Calling backend. Routers are the **thinnest possible layer** between an incoming HTTP request and the service/repository that fulfils it.

---

## Architectural Invariants

Every router in this directory obeys the same structural contract:

1. **Creates an `APIRouter`** with a URL prefix and OpenAPI tag.
2. **Injects dependencies** via FastAPI's `Depends` mechanism, using the two shared type aliases from `app.dependencies`:
   - `SupabaseDep` — an `Annotated[Client, Depends(get_supabase)]` that yields a Supabase service-role client.
   - `CurrentUserDep` — an `Annotated[dict, Depends(get_current_user)]` that extracts and validates the JWT from the `Authorization: Bearer <token>` header, returning a `{"id", "email", "full_name"}` dict.
3. **Contains zero business logic.** Each endpoint either:
   - Calls a **service** function (for operations that orchestrate multiple steps or side-effects), or
   - Calls a **repository** function (for single-table CRUD that needs no orchestration).
4. **Returns Pydantic schema objects** declared in `app/schemas/`, giving the client a typed, stable JSON contract.
5. **Raises `HTTPException`** with an appropriate status code on every error path — validation failures (400), missing resources (404), auth failures (401), and server errors (500).

### SOLID Principles at Work

| Principle | How it manifests |
|---|---|
| **Single Responsibility** | Each router handles exactly one resource domain (contacts, calls, SMS, …). |
| **Dependency Inversion** | Routers depend on abstract service/repo functions, never on database tables or Supabase internals. |
| **Interface Segregation** | Each router exposes only the endpoints the frontend actually needs — no catch-all god-router. |
| **Open/Closed** | Adding a new feature (e.g. a new call outcome) requires changing a service, not a router. |

---

## Router-by-Router Reference

### 1. `auth.py` — Authentication

```
APIRouter(prefix="/auth", tags=["auth"])
```

Handles user login and session introspection. This is the only router that talks to Supabase Auth directly (via `db.auth.sign_in_with_password`) rather than going through a service, because authentication **is** the Supabase client call — there is no additional business logic to extract.

#### Inline Schemas

Two Pydantic models are defined directly in this file because they are used nowhere else:

| Model | Fields | Purpose |
|---|---|---|
| `LoginRequest` | `email: str`, `password: str` | Request body for `/login` |
| `LoginResponse` | `access_token: str`, `user: dict` | Response body for `/login` |

#### Endpoints

##### `POST /auth/login`

```
def login(body: LoginRequest, db: SupabaseDep)
```

| Aspect | Detail |
|---|---|
| **Parameters** | JSON body with `email` (string) and `password` (string). |
| **Auth required** | No — this *creates* a session. |
| **What it does** | Calls `db.auth.sign_in_with_password({"email": …, "password": …})`. Extracts `result.user` and `result.session`. If either is `None`, raises 401. |
| **Returns** | `LoginResponse` — `{ access_token: str, user: { id, email, full_name } }`. |
| **Error handling** | Re-raises any `HTTPException` as-is. Catches all other exceptions and wraps them in a 401 with `"Login failed: {exc}"`. |

Line-by-line:

- **Line 22** — Receives the Pydantic `LoginRequest` body and the injected Supabase client.
- **Lines 23-27** — `try` block: calls Supabase Auth's `sign_in_with_password` with the email/password dict.
- **Lines 28-30** — Extracts the `user` and `session` objects from the auth result; raises 401 if either is falsy.
- **Lines 33-40** — Constructs a `LoginResponse`, extracting `access_token` from the session and building a minimal user dict from `user.id`, `user.email`, and the `full_name` field in `user.user_metadata`.
- **Lines 41-42** — `except HTTPException: raise` — lets explicit HTTP errors pass through untouched.
- **Lines 43-44** — Generic catch-all: any unexpected Supabase/network error becomes a 401.

##### `GET /auth/me`

```
def get_me(current_user: CurrentUserDep)
```

| Aspect | Detail |
|---|---|
| **Parameters** | None (auth token is extracted by the dependency). |
| **Auth required** | Yes — `CurrentUserDep` validates the Bearer token. |
| **What it does** | Nothing — simply returns the already-resolved user dict. |
| **Returns** | `dict` — `{ id, email, full_name }` (the same dict that `get_current_user` produces). |
| **Error handling** | All error handling lives in the `CurrentUserDep` dependency (401 if token missing/invalid). |

---

### 2. `contacts.py` — Contact Management

```
APIRouter(prefix="/contacts", tags=["contacts"])
```

Full CRUD (minus Create, which happens through CSV import) for the contacts table. Every endpoint delegates to `app.services.contact_service`. Response shapes come from `app/schemas/contact.py`.

#### Schemas Used

| Schema | Source | Purpose |
|---|---|---|
| `ContactOut` | `app.schemas.contact` | Full contact representation (30+ fields including score, call state, SMS state). |
| `ContactUpdate` | `app.schemas.contact` | Partial update — only `call_outcome` and `messaging_status` are writable. |
| `ContactListOut` | `app.schemas.contact` | Paginated wrapper: `{ contacts: list, total: int, page: int, per_page: int }`. |

#### Endpoints

##### `GET /contacts`

```
def list_contacts(
    current_user: CurrentUserDep,
    db: SupabaseDep,
    sort_by: str = Query("created_at"),
    sort_order: str = Query("asc"),
    outcome_filter: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
)
```

| Aspect | Detail |
|---|---|
| **Parameters** | Query params: `sort_by` (column name, default `created_at`), `sort_order` (`asc`/`desc`), `outcome_filter` (optional string to filter by `call_outcome`), `page` (≥ 1), `per_page` (1–200). |
| **Auth required** | Yes. |
| **Service called** | `contact_service.list_contacts(db, sort_by, sort_order, outcome_filter, page, per_page)` — returns `(list[dict], int)`. |
| **Returns** | `ContactListOut` — wraps the contact dicts into `ContactOut` objects and includes pagination metadata. |
| **Error handling** | Implicit — service raises on DB errors; FastAPI's query validation rejects out-of-range `page`/`per_page`. |

Line-by-line:

- **Lines 12-20** — Endpoint signature. `Query(...)` declarations provide defaults, validation constraints (`ge=1`, `le=200`), and OpenAPI documentation.
- **Lines 22-29** — Delegates entirely to `contact_service.list_contacts`, which returns a tuple of `(contacts_list, total_count)`.
- **Lines 30-35** — Constructs the `ContactListOut` response: maps each raw dict through `ContactOut(**c)` for Pydantic validation, and attaches `total`, `page`, and `per_page`.

##### `GET /contacts/{contact_id}`

```
def get_contact(contact_id: str, current_user: CurrentUserDep, db: SupabaseDep)
```

| Aspect | Detail |
|---|---|
| **Parameters** | Path param `contact_id` (UUID string). |
| **Auth required** | Yes. |
| **Service called** | `contact_service.get_contact(db, contact_id)` — returns `dict | None`. |
| **Returns** | `ContactOut`. |
| **Error handling** | 404 if the service returns `None`. |

Line-by-line:

- **Line 39** — Extracts `contact_id` from the URL path.
- **Lines 40-42** — Calls the service; if `None`, raises 404.
- **Line 43** — Wraps the raw dict in `ContactOut` for response serialization.

##### `PATCH /contacts/{contact_id}`

```
def update_contact(contact_id: str, body: ContactUpdate, current_user: CurrentUserDep, db: SupabaseDep)
```

| Aspect | Detail |
|---|---|
| **Parameters** | Path param `contact_id`; JSON body matching `ContactUpdate` (optional `call_outcome`, `messaging_status`). |
| **Auth required** | Yes. |
| **Service called** | `contact_service.update_contact(db, contact_id, data)` — returns `dict | None`. |
| **Returns** | `ContactOut` (the updated row). |
| **Error handling** | 400 if the body is entirely empty after `exclude_none`; 404 if the contact doesn't exist. |

Line-by-line:

- **Lines 47-52** — Endpoint signature accepts the path param, `ContactUpdate` body, and both dependencies.
- **Line 53** — `body.model_dump(exclude_none=True)` strips unset fields so only explicitly-provided values are sent to the DB.
- **Lines 54-55** — If the resulting dict is empty (caller sent `{}`), returns 400 immediately.
- **Lines 57-59** — Delegates to the service; 404 if the contact was not found.
- **Line 60** — Returns the updated record as `ContactOut`.

##### `DELETE /contacts/{contact_id}`

```
def delete_contact(contact_id: str, current_user: CurrentUserDep, db: SupabaseDep)
```

| Aspect | Detail |
|---|---|
| **Parameters** | Path param `contact_id`. |
| **Auth required** | Yes. |
| **Service called** | `contact_service.delete_contact(db, contact_id)` — returns `bool`. |
| **Returns** | `{"detail": "Contact deleted"}`. |
| **Error handling** | 404 if the service returns `False`. |

---

### 3. `imports.py` — CSV Import Pipeline

```
APIRouter(prefix="/imports", tags=["imports"])
```

Handles file upload and background processing of CSV contact data. Uses **both** a service (`import_service`) for the heavy processing and a repository (`import_batch_repo`) for lightweight status lookups.

#### Background Task Helper

```python
def _run_import(file_content: bytes, filename: str, user_id: str) -> None
```

A module-level function (not an endpoint) that runs **inside a FastAPI `BackgroundTask`**. It:

1. Creates its own Supabase client via `get_supabase()` (because background tasks run outside the request lifecycle).
2. Calls `import_service.process_csv_upload(db, file_content, filename, user_id)`.
3. Catches and logs any exception so the background task doesn't crash silently.

#### Schemas Used

| Schema | Source | Purpose |
|---|---|---|
| `ImportBatchOut` | `app.schemas.import_batch` | Batch status: `id`, `user_id`, `filename`, `total_rows`, `processed_rows`, `stored_rows`, `discarded_rows`, `status`, `created_at`. |

#### Endpoints

##### `POST /imports/upload`

```
async def upload_csv(
    file: UploadFile,
    current_user: CurrentUserDep,
    db: SupabaseDep,
    background_tasks: BackgroundTasks,
)
```

| Aspect | Detail |
|---|---|
| **Parameters** | Multipart form upload: `file` (`UploadFile`). |
| **Auth required** | Yes. |
| **Service called** | `import_batch_repo.create_batch(db, {...})` for the initial record; `import_service.process_csv_upload(...)` asynchronously via `BackgroundTasks`. |
| **Returns** | `{ batch_id: str, status: "processing" }`. |
| **Error handling** | 400 if the file is not `.csv` or is empty. |

Line-by-line:

- **Line 24** — `async def` because `UploadFile.read()` is an awaitable.
- **Lines 30-31** — Validates the filename ends with `.csv`; rejects otherwise with 400.
- **Lines 33-35** — Reads the full file content into memory; rejects empty files with 400.
- **Lines 37-42** — Creates an `import_batch` record in the database with `status: "processing"` and `total_rows: 0` (updated later by the background task).
- **Line 44** — Enqueues `_run_import` as a background task with the file bytes, filename, and user ID.
- **Line 46** — Returns immediately with the batch ID so the frontend can poll for status.

##### `GET /imports/{batch_id}/status`

```
def get_import_status(batch_id: str, current_user: CurrentUserDep, db: SupabaseDep)
```

| Aspect | Detail |
|---|---|
| **Parameters** | Path param `batch_id` (UUID string). |
| **Auth required** | Yes. |
| **Repo called** | `import_batch_repo.get_batch(db, batch_id)`. |
| **Returns** | `ImportBatchOut`. |
| **Error handling** | 404 if the batch doesn't exist. |

##### `GET /imports/recent`

```
def get_recent_imports(current_user: CurrentUserDep, db: SupabaseDep)
```

| Aspect | Detail |
|---|---|
| **Parameters** | None. |
| **Auth required** | Yes. |
| **Repo called** | `import_batch_repo.get_recent_batches(db)`. |
| **Returns** | `list[ImportBatchOut]`. |
| **Error handling** | None needed — an empty list is a valid response. |

---

### 4. `calls.py` — Call Logging & Twilio Tokens

```
APIRouter(prefix="/calls", tags=["calls"])
```

Manages the call lifecycle: generating browser-call tokens, logging call outcomes, and retrieving call history. Uses `call_service` for token generation and call logging, and `call_log_repo` for read-only history queries.

#### Schemas Used

| Schema | Source | Purpose |
|---|---|---|
| `CallLogCreate` | `app.schemas.call` | Input: `contact_id`, `call_method`, `phone_number_called` (optional), `outcome`. |
| `CallLogOut` | `app.schemas.call` | Full call log row: `id`, `contact_id`, `user_id`, `call_date`, `call_method`, `phone_number_called`, `outcome`, `is_new_occasion`, `created_at`. |
| `CallLogResponse` | `app.schemas.call` | Composite response: `{ call_log: CallLogOut, sms_prompt_needed: bool, occasion_count: int }`. |

#### Endpoints

##### `POST /calls/token`

```
def get_twilio_token(current_user: CurrentUserDep)
```

| Aspect | Detail |
|---|---|
| **Parameters** | None (user ID comes from the auth dependency). |
| **Auth required** | Yes. |
| **Service called** | `call_service.generate_twilio_token(current_user["id"])`. |
| **Returns** | `{ token: str }` — a short-lived Twilio Access Token for the browser SDK. |
| **Error handling** | 500 if token generation fails (Twilio config missing, etc.). |

Line-by-line:

- **Line 14** — Only `CurrentUserDep` is injected — no database needed; token generation uses the Twilio SDK with env-var credentials.
- **Lines 15-17** — Calls the service; wraps the token string in a dict.
- **Lines 18-19** — Any exception becomes a 500 with the error message.

##### `POST /calls/log`

```
def log_call(body: CallLogCreate, current_user: CurrentUserDep, db: SupabaseDep)
```

| Aspect | Detail |
|---|---|
| **Parameters** | JSON body: `contact_id` (str), `call_method` (str, e.g. `"browser"` or `"manual"`), `phone_number_called` (optional str), `outcome` (str, e.g. `"no_answer"`, `"interested"`). |
| **Auth required** | Yes. |
| **Service called** | `call_service.log_call(db, contact_id, user_id, call_method, phone_number_called, outcome)` — returns a dict with keys `call_log`, `sms_prompt_needed`, `occasion_count`. |
| **Returns** | `CallLogResponse` — contains the persisted `CallLogOut` plus SMS-threshold metadata. |
| **Error handling** | Implicit — relies on service-layer exceptions propagating as 500s. |

Line-by-line:

- **Lines 23-31** — Passes every field from the body plus the authenticated user's ID to the service.
- **Lines 32-36** — Unpacks the service result into a `CallLogResponse`, converting the raw `call_log` dict into a `CallLogOut`.

The `sms_prompt_needed` flag is the key integration point: the service checks whether the contact's `call_occasion_count` has reached the SMS threshold (from `app_settings`), signalling the frontend to show an "Send SMS?" prompt.

##### `GET /calls/contact/{contact_id}`

```
def get_call_history(contact_id: str, current_user: CurrentUserDep, db: SupabaseDep)
```

| Aspect | Detail |
|---|---|
| **Parameters** | Path param `contact_id`. |
| **Auth required** | Yes. |
| **Repo called** | `call_log_repo.get_call_logs_for_contact(db, contact_id)`. |
| **Returns** | `list[CallLogOut]`. |
| **Error handling** | None — empty list is valid. |

---

### 5. `twilio_webhooks.py` — Twilio Webhook Handlers

```
APIRouter(prefix="/twilio", tags=["twilio"])
```

These endpoints are **called by Twilio's servers**, not by the frontend. They do not require `CurrentUserDep` because Twilio sends form-encoded POST data, not Bearer tokens. This is the only router that imports `app.config.settings` directly (for the Twilio phone number).

#### Endpoints

##### `POST /twilio/voice`

```
def voice_webhook(To: str = Form(""))
```

| Aspect | Detail |
|---|---|
| **Parameters** | Form field `To` — the phone number the browser SDK wants to call (sent by Twilio). |
| **Auth required** | No — called by Twilio infrastructure. |
| **Service called** | None — generates TwiML inline. |
| **Returns** | XML `Response` with `media_type="application/xml"` containing a `<Dial>` TwiML instruction. |
| **Error handling** | None — Twilio retries on failure. |

Line-by-line:

- **Line 11** — `To` is extracted from the form data Twilio POSTs when the browser SDK initiates a call.
- **Lines 13-18** — Constructs a raw TwiML XML string: `<Response><Dial callerId="{twilio_phone_number}"><Number>{To}</Number></Dial></Response>`. The `callerId` is read from `settings.twilio_phone_number` so the recipient sees the business number.
- **Line 19** — Returns a FastAPI `Response` with the XML content type so Twilio parses it as TwiML.

##### `POST /twilio/status`

```
def status_callback(CallSid: str = Form(""), CallStatus: str = Form(""))
```

| Aspect | Detail |
|---|---|
| **Parameters** | Form fields `CallSid` (Twilio's unique call identifier) and `CallStatus` (e.g. `"completed"`, `"busy"`, `"no-answer"`). |
| **Auth required** | No — called by Twilio. |
| **Service called** | None (currently a pass-through). |
| **Returns** | `{ call_sid: str, status: str }` — an acknowledgement. |
| **Error handling** | None. |

This endpoint currently acts as a logging hook. It acknowledges the status callback from Twilio so Twilio stops retrying. Future iterations can persist status updates to the `call_logs` table.

---

### 6. `sms.py` — SMS Sending & Scheduling

```
APIRouter(prefix="/sms", tags=["sms"])
```

Handles both immediate and scheduled SMS sending. All Twilio SMS logic lives in `sms_service`.

#### Inline Schemas

| Model | Fields | Purpose |
|---|---|---|
| `SendSMSRequest` | `contact_id: str` | Identifies which contact to text right now. |
| `ScheduleSMSRequest` | `contact_id: str`, `scheduled_at: datetime` | Identifies which contact and when. |

#### Endpoints

##### `POST /sms/send`

```
def send_sms(body: SendSMSRequest, current_user: CurrentUserDep, db: SupabaseDep)
```

| Aspect | Detail |
|---|---|
| **Parameters** | JSON body with `contact_id`. |
| **Auth required** | Yes. |
| **Service called** | `sms_service.send_sms(db, contact_id)`. |
| **Returns** | The service result dict (Twilio message SID, status, etc.). |
| **Error handling** | `ValueError` → 400 (e.g. contact has no phone number, or template is missing). All other exceptions → 500 with `"SMS send failed: {exc}"`. |

Line-by-line:

- **Lines 24-27** — Calls the service inside a `try` block.
- **Lines 28-29** — Catches `ValueError` specifically — these represent client-fixable problems (bad contact data), so they become 400s.
- **Lines 30-31** — Generic catch-all for infrastructure failures (Twilio API down, etc.) becomes a 500.

##### `POST /sms/schedule`

```
def schedule_sms(body: ScheduleSMSRequest, current_user: CurrentUserDep, db: SupabaseDep)
```

| Aspect | Detail |
|---|---|
| **Parameters** | JSON body with `contact_id` and `scheduled_at` (ISO 8601 datetime). |
| **Auth required** | Yes. |
| **Service called** | `sms_service.schedule_sms(db, contact_id, scheduled_at)`. |
| **Returns** | The service result dict. |
| **Error handling** | `ValueError` → 400. |

---

### 7. `notes.py` — Contact Notes (CRUD)

```
APIRouter(tags=["notes"])
```

The only router **without a prefix** — it mounts endpoints under two different path hierarchies:
- `/contacts/{contact_id}/notes` for collection operations (list, create).
- `/notes/{note_id}` for item operations (update, delete).

All database work is delegated to `note_repo` (a repository, not a service) because notes are a simple CRUD resource with no cross-cutting business logic.

#### Schemas Used

| Schema | Source | Purpose |
|---|---|---|
| `NoteCreate` | `app.schemas.note` | Input: `content: str`. |
| `NoteUpdate` | `app.schemas.note` | Input: `content: str`. |
| `NoteOut` | `app.schemas.note` | Output: `id`, `contact_id`, `user_id`, `content`, `note_date`, `created_at`, `updated_at`. |

#### Endpoints

##### `GET /contacts/{contact_id}/notes`

```
def get_notes(contact_id: str, current_user: CurrentUserDep, db: SupabaseDep)
```

| Aspect | Detail |
|---|---|
| **Parameters** | Path param `contact_id`. |
| **Auth required** | Yes. |
| **Repo called** | `note_repo.get_notes_for_contact(db, contact_id)`. |
| **Returns** | `list[NoteOut]`. |
| **Error handling** | None — empty list is valid. |

##### `POST /contacts/{contact_id}/notes` (status 201)

```
def create_note(contact_id: str, body: NoteCreate, current_user: CurrentUserDep, db: SupabaseDep)
```

| Aspect | Detail |
|---|---|
| **Parameters** | Path param `contact_id`; JSON body with `content`. |
| **Auth required** | Yes. |
| **Repo called** | `note_repo.create_note(db, data)` where `data = { contact_id, user_id, content }`. |
| **Returns** | `NoteOut` with HTTP 201. |
| **Error handling** | Implicit (DB constraint violations propagate as 500). |

Line-by-line:

- **Lines 25-29** — Builds the insertion dict: merges the path param `contact_id`, the authenticated `user_id`, and the body `content`.
- **Line 30** — Delegates to the repo.
- **Line 31** — Wraps the returned row in `NoteOut`.

##### `PATCH /notes/{note_id}`

```
def update_note(note_id: str, body: NoteUpdate, current_user: CurrentUserDep, db: SupabaseDep)
```

| Aspect | Detail |
|---|---|
| **Parameters** | Path param `note_id`; JSON body with `content`. |
| **Auth required** | Yes. |
| **Repo called** | `note_repo.update_note(db, note_id, {"content": body.content})`. |
| **Returns** | `NoteOut`. |
| **Error handling** | 404 if the note doesn't exist. |

##### `DELETE /notes/{note_id}`

```
def delete_note(note_id: str, current_user: CurrentUserDep, db: SupabaseDep)
```

| Aspect | Detail |
|---|---|
| **Parameters** | Path param `note_id`. |
| **Auth required** | Yes. |
| **Repo called** | `note_repo.delete_note(db, note_id)`. |
| **Returns** | `{"detail": "Note deleted"}`. |
| **Error handling** | 404 if the note doesn't exist. |

---

### 8. `settings.py` — Global App Settings

```
APIRouter(prefix="/settings", tags=["settings"])
```

Manages the single-row `app_settings` table. The two configurable values control the SMS automation behaviour: how many call occasions trigger the SMS prompt, and what message template to send.

#### Schemas Used

| Schema | Source | Purpose |
|---|---|---|
| `SettingsOut` | `app.schemas.settings` | Output: `id`, `sms_call_threshold: int`, `sms_template: str`. |
| `SettingsUpdate` | `app.schemas.settings` | Input: both fields optional — `sms_call_threshold: int | None`, `sms_template: str | None`. |

#### Endpoints

##### `GET /settings`

```
def get_settings(current_user: CurrentUserDep, db: SupabaseDep)
```

| Aspect | Detail |
|---|---|
| **Parameters** | None. |
| **Auth required** | Yes. |
| **Repo called** | `settings_repo.get_settings(db)`. |
| **Returns** | `SettingsOut`. |
| **Error handling** | 404 if no settings row exists (should not happen in practice — the row is seeded on deploy). |

##### `PUT /settings`

```
def update_settings(body: SettingsUpdate, current_user: CurrentUserDep, db: SupabaseDep)
```

| Aspect | Detail |
|---|---|
| **Parameters** | JSON body with optional `sms_call_threshold` (int) and/or `sms_template` (str). |
| **Auth required** | Yes. |
| **Repo called** | `settings_repo.get_settings(db)` to fetch the current row, then `settings_repo.update_settings(db, id, update_data)` to apply changes. |
| **Returns** | `SettingsOut` (the updated row). |
| **Error handling** | 404 if settings don't exist. Returns the current settings unchanged if the body is empty after `exclude_none`. 500 if the update itself fails. |

Line-by-line:

- **Lines 21-23** — Fetches the current settings row. If missing, returns 404.
- **Lines 26-28** — Strips `None` fields from the body. If nothing remains, short-circuits by returning the existing settings (no DB write).
- **Lines 30-33** — Delegates the update to the repo using the existing row's `id`. If the repo returns `None`, something went wrong at the DB level → 500.

---

## Dependency Injection Flow

Every authenticated request follows this dependency chain:

```
HTTP Request
  │
  ├─ Authorization header
  │    └─ get_current_user()          → validates JWT via Supabase Auth
  │         └─ returns CurrentUserDep → {"id", "email", "full_name"}
  │
  └─ get_supabase()                   → returns cached Supabase Client
       └─ SupabaseDep                 → injected into service/repo calls
```

`get_supabase()` is decorated with `@lru_cache`, so the Supabase client is created once per process and reused across all requests.

---

## File → Endpoint Quick Reference

| File | Prefix | Endpoints | Delegates to |
|---|---|---|---|
| `auth.py` | `/auth` | `POST /login`, `GET /me` | Supabase Auth directly |
| `contacts.py` | `/contacts` | `GET /`, `GET /{id}`, `PATCH /{id}`, `DELETE /{id}` | `contact_service` |
| `imports.py` | `/imports` | `POST /upload`, `GET /{id}/status`, `GET /recent` | `import_service`, `import_batch_repo` |
| `calls.py` | `/calls` | `POST /token`, `POST /log`, `GET /contact/{id}` | `call_service`, `call_log_repo` |
| `twilio_webhooks.py` | `/twilio` | `POST /voice`, `POST /status` | Inline TwiML generation |
| `sms.py` | `/sms` | `POST /send`, `POST /schedule` | `sms_service` |
| `notes.py` | *(none)* | `GET /contacts/{id}/notes`, `POST /contacts/{id}/notes`, `PATCH /notes/{id}`, `DELETE /notes/{id}` | `note_repo` |
| `settings.py` | `/settings` | `GET /`, `PUT /` | `settings_repo` |
