# Hexa Cold Calling Backend

FastAPI backend for the Hexa cold-calling workflow. It owns authentication verification, Supabase persistence, contact imports and scoring, call tracking, Twilio/SMS workflows, Gmail follow-up, Apollo enrichment, productivity reporting, scheduled calls, and the standalone team to-do list.

## Tech Stack

- FastAPI with Python 3.11.
- Supabase PostgREST/Auth through the server-side service-role client.
- Pydantic schemas for request and response contracts.
- OpenAI and Exa for lead scoring and enrichment.
- Twilio for browser calling, call status webhooks, and SMS.
- Google Gmail OAuth/API for email send, drafts, logs, and tracking.
- Pytest, FastAPI `TestClient`, and `unittest.mock` for isolated tests.

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
python -m uvicorn app.main:app --host localhost --port 8000 --reload
```

The API runs at `http://localhost:8000` by default. The frontend should point `NEXT_PUBLIC_API_URL` to the same URL.

## Environment

Copy `.env.example` to `.env` for local development. Keep `.env` local and never commit secrets.

- `SUPABASE_URL`: Supabase project URL.
- `SUPABASE_SERVICE_ROLE_KEY`: server-side Supabase key used by the backend only.
- `OPENAI_API_KEY` and `OPENAI_MODEL`: scoring model configuration.
- `EXA_API_KEY`: company research and enrichment.
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`, `TWILIO_TWIML_APP_SID`, `TWILIO_PHONE_NUMBERS_JSON`: voice/SMS configuration.
- `APOLLO_API_KEY` and `BACKEND_PUBLIC_URL`: Apollo enrichment and webhook callback support. `BACKEND_PUBLIC_URL` must be publicly reachable for Apollo webhooks.
- `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`: Gmail OAuth.
- `FRONTEND_URL`: URL used when the backend generates frontend links.
- `ALLOWED_ORIGINS`: comma-separated CORS allowlist.

## Project Structure

- `app/main.py`: creates the FastAPI app, configures CORS, registers routers, and starts background tasks.
- `app/config.py`: typed settings loaded from environment variables and `.env`.
- `app/dependencies.py`: injectable Supabase client and authenticated user dependencies.
- `app/routers/`: HTTP endpoint layer. See `app/routers/README.md`.
- `app/services/`: orchestration layer for multi-step workflows and external APIs. See `app/services/README.md`.
- `app/repositories/`: Supabase query layer. See `app/repositories/README.md`.
- `app/schemas/`: Pydantic API contracts. See `app/schemas/README.md`.
- `app/tasks/`: background task loops. See `app/tasks/README.md`.
- `app/scoring/`: Exa/OpenAI scoring helpers and prompt documentation. See `app/scoring/README.md`.
- `migrations/`: ordered SQL migrations. See `migrations/README.md`.
- `tests/`: unit and integration tests. See `tests/README.md`.

## API Areas

- Auth: login and current-user introspection.
- Contacts and companies: contact CRUD, search, grouping, phone cleanup, notes, and call history.
- Calls: browser token generation, claim/release queueing, call logging, callbacks, and outcome tracking.
- Imports: CSV upload, scoring/enrichment pipeline, batch status, filtered CSV download, and stale import recovery.
- Twilio and SMS: voice TwiML/status webhooks plus direct/scheduled SMS.
- Gmail: OAuth connect/callback, send, draft, logs, sync, tracking summaries, and threads.
- Apollo: enrichment requests and webhook ingestion.
- Productivity: team call/outcome reporting.
- Scheduled calls: follow-up scheduling and completion/cancellation.
- To-do list: title-only task creation, optional descriptions/due dates, multi-assignees, assigner/assignee editing, assigner-only delete, and assignment notifications.

## Tests

```bash
python -m pytest tests/ -q
python -m pytest tests/unit/ -q
python -m pytest tests/integration/ -q
python -m pytest tests/unit/test_todo_schema.py tests/unit/test_todo_repo.py tests/integration/test_todos_routes.py -q
```

The tests override FastAPI dependencies, mock Supabase/Auth/external services, and should not require real credentials. Add unit tests for pure service/repository/schema behavior and integration tests when an HTTP contract, dependency override, or permission rule changes.

## Migrations

Apply SQL files in numeric order. Recent to-do functionality depends on both `026_todos.sql` and `027_todo_multi_assignees.sql`; the latter adds canonical multi-assignee rows while keeping legacy first-assignee columns mirrored for compatibility.

## Security Notes

- The backend uses the Supabase service-role key and therefore must enforce authorization at the API layer.
- Keep provider webhook verification and OAuth state handling in mind when changing Twilio, Apollo, or Gmail routes.
- Do not expose `.env`, service-role keys, Gmail tokens, or Twilio auth tokens to the frontend.
