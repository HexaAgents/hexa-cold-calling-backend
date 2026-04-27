# Backend Test Suite

## Directory Structure

```
tests/
├── conftest.py                           # Shared pytest fixtures used by every test
├── unit/
│   ├── test_call_service.py              # Call logging, retry/callback, SMS threshold
│   ├── test_contact_service.py           # Contact CRUD delegation
│   ├── test_contact_schema.py            # ContactOut resilience (NULLs, extra columns)
│   ├── test_import_service.py            # CSV parsing, scoring, batch insert
│   ├── test_scoring_service.py           # AI scoring pipeline (Exa + OpenAI)
│   ├── test_sms_service.py              # SMS template rendering
│   ├── test_openai_scorer.py            # OpenAI response parsing
│   ├── test_apollo_service.py           # Apollo enrichment helpers
│   ├── test_apollo_webhook.py           # Apollo webhook payload handling
│   ├── test_stale_recovery.py           # Stale import detection/recovery
│   ├── test_stale_claims.py             # 10-hour claim auto-release + route integration
│   ├── test_email_service.py            # Email OAuth, send, template, draft, token refresh
│   ├── test_email_repo.py              # Gmail tokens + email logs CRUD
│   ├── test_email_tracking_repo.py      # Tracked emails upsert, summary, thread
│   ├── test_email_tracking_service.py   # Gmail sync, header parsing, user-level sync
│   └── test_companies_repo.py           # Company grouping, search, contacts by company
└── integration/
    ├── test_health.py                    # Health check endpoint
    ├── test_auth_routes.py               # Auth/me endpoints
    ├── test_contacts_routes.py           # Contact CRUD + search + phone delete
    ├── test_calls_routes.py              # Call logging, claim, release, queue, callback_date
    ├── test_settings_routes.py           # Settings GET/PUT including retry_days
    ├── test_imports_routes.py            # CSV upload, batch status, recent imports
    ├── test_twilio_routes.py             # Voice TwiML + status webhook
    ├── test_sms_routes.py               # Send/schedule SMS
    ├── test_notes_routes.py             # Notes CRUD
    ├── test_apollo_routes.py            # Apollo enrichment + webhook
    ├── test_productivity_routes.py      # Productivity aggregation
    ├── test_email_routes.py             # Gmail OAuth, send, draft, logs endpoints
    ├── test_email_tracking_routes.py    # Email tracking sync, list, thread endpoints
    └── test_companies_routes.py         # Companies list + detail endpoints
```

Unit tests validate individual functions in complete isolation — every external dependency (Exa, OpenAI, Supabase) is replaced with a mock. Integration tests spin up a real FastAPI `TestClient` and make actual HTTP requests against the app, but still mock the database and authentication layers so no real credentials are needed.

---

## conftest.py — Shared Fixtures

This file is automatically discovered by pytest. Any fixture defined here is available to every test in the `tests/` directory and all subdirectories without any explicit import.

### `mock_supabase` fixture (line 9–11)

```python
@pytest.fixture
def mock_supabase():
    return MagicMock()
```

Creates a `unittest.mock.MagicMock` instance that stands in for the real Supabase client. MagicMock is used (rather than plain Mock) because the Supabase client uses chained method calls like `supabase.table("contacts").select("*").execute()`. MagicMock auto-creates nested attributes on access, so any chain of `.method().method()` calls succeeds without explicit setup. Tests that need a specific return value can configure it via `mock_supabase.table.return_value.select.return_value.execute.return_value = ...`.

### `mock_current_user` fixture (line 14–20)

```python
@pytest.fixture
def mock_current_user():
    return {
        "id": "test-user-id",
        "email": "test@hexaagents.com",
        "full_name": "Test User",
    }
```

Returns a plain dictionary with the same shape the real `get_current_user` dependency produces after validating a JWT. The `id` is a deterministic string (`"test-user-id"`) so tests can assert against it in database queries. The email uses the `@hexaagents.com` domain to make it obvious this is test data. This dict is injected into the FastAPI dependency graph by the `client` fixture below, so every authenticated endpoint sees this user without touching Supabase Auth.

### `client` fixture (line 23–34)

```python
@pytest.fixture
def client(mock_supabase, mock_current_user):
    from app.main import app
    from app.dependencies import get_supabase, get_current_user

    app.dependency_overrides[get_supabase] = lambda: mock_supabase
    app.dependency_overrides[get_current_user] = lambda: mock_current_user

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
```

This is the most important fixture — it wires everything together:

1. **Lazy import** (lines 25–26): `app` and the dependency functions are imported inside the fixture body, not at module level. This avoids import-time side effects (like the app trying to connect to a real database during test collection).

2. **Dependency overrides** (lines 28–29): FastAPI's `dependency_overrides` dict maps a dependency callable to a replacement callable. When any route declares `Depends(get_supabase)`, FastAPI calls the lambda instead, which returns the `mock_supabase` MagicMock. Same for `get_current_user` — the lambda returns `mock_current_user`, bypassing JWT validation entirely. This is the key mechanism that lets the entire test suite run with zero real API keys or database connections.

3. **TestClient context manager** (lines 31–32): `TestClient(app)` creates an HTTPX-based client that sends requests directly to the ASGI app in-process (no real HTTP server is started). The `with` block triggers FastAPI's startup/shutdown lifespan events. `yield c` hands the client to the test function.

4. **Cleanup** (line 34): After the test completes, `app.dependency_overrides.clear()` removes all overrides so one test's mocks don't leak into another. This runs even if the test raises an exception because it's after the `yield` in a pytest fixture.

---

## unit/test_scoring_service.py — Scoring Pipeline Tests

This file tests `score_website()` from `app.services.scoring_service`. The function is a two-step pipeline: (1) call Exa to scrape company info, (2) call OpenAI to score the company. Both external calls are patched so the tests run instantly with no network.

### `test_score_website_success` (lines 6–33)

```python
def test_score_website_success():
    with (
        patch("app.services.scoring_service.fetch_company_info") as mock_exa,
        patch("app.services.scoring_service.score_company") as mock_openai,
    ):
```

Uses Python 3.10+ parenthesized context managers to patch two functions simultaneously. The patch targets are fully qualified paths to where the functions are *used* (inside `scoring_service`), not where they are *defined*. This is a critical distinction — patching at the usage site ensures the mock is injected correctly regardless of how the module imports the function.

```python
        mock_exa.return_value = ("ACME manufactures industrial valves...", True)
```

Simulates a successful Exa scrape. The function returns a tuple: `(scraped_text, success_boolean)`. The text is a realistic snippet so the test documents what real data looks like.

```python
        mock_openai.return_value = {
            "score": 85,
            "company_type": "distributor",
            "rationale": "ACME is an industrial distributor of valves and fittings.",
            "rejection_reason": None,
        }
```

Simulates OpenAI returning a structured scoring result. Score 85 means high-quality lead (confirmed industrial distributor). `rejection_reason` is `None` because the company passed scoring.

```python
        result = score_website(
            exa_api_key="fake",
            openai_api_key="fake",
            openai_model="gpt-4o-mini",
            website="https://acme.com",
            company_name="ACME Corp",
            job_title="CEO",
        )
```

Calls the real `score_website` function with fake API keys. Because both dependencies are patched, the keys are never actually used — they just need to be non-empty strings to pass any validation.

```python
        assert result["score"] == 85
        assert result["company_type"] == "manufacturer"
        assert result["exa_scrape_success"] is True
        assert result["scoring_failed"] is False
```

Four assertions verify the happy path:
- The score from OpenAI is passed through unchanged.
- The company type (`"distributor"`) is passed through unchanged.
- `exa_scrape_success` reflects the `True` from the Exa mock.
- `scoring_failed` is `False` because no exception was raised.

### `test_score_website_exa_failure` (lines 36–60)

```python
        mock_exa.return_value = ("", False)
```

Simulates Exa failing to scrape the website. The text is empty and the success flag is `False`. This happens in production when a website blocks scraping, returns a 404, or times out.

```python
        mock_openai.return_value = {
            "score": 0,
            "company_type": "rejected",
            "rationale": "No website content available.",
            "rejection_reason": "unclear",
        }
```

When Exa fails, OpenAI receives minimal context and typically scores the company at 0 with a `"rejected"` type. The `rejection_reason` of `"unclear"` indicates there wasn't enough data to make a determination.

```python
        result = score_website(
            exa_api_key="fake",
            openai_api_key="fake",
            openai_model="gpt-4o-mini",
            website="https://broken.com",
            company_name="Broken Inc",
        )
```

Note that `job_title` is omitted here (it's optional). This tests that the function handles missing optional parameters.

```python
        assert result["score"] == 0
        assert result["exa_scrape_success"] is False
```

Verifies the failure path: score is 0 and `exa_scrape_success` correctly reflects the scrape failure.

---

## unit/test_sms_service.py — SMS Template Tests

This file tests `render_template()` from `app.services.sms_service`. The function takes a template string containing `<variable_name>` placeholders and a contact dictionary, then replaces each placeholder with the corresponding value. No mocking is needed — this is a pure function with no external dependencies.

### `test_render_template_all_variables` (lines 6–16)

```python
    template = "Hi <first_name> <last_name>, we help <company_name> (<title>) at <website>."
    contact = {
        "first_name": "John",
        "last_name": "Smith",
        "company_name": "ACME Corp",
        "title": "COO",
        "website": "https://acme.com",
    }
    result = render_template(template, contact)
    assert result == "Hi John Smith, we help ACME Corp (COO) at https://acme.com."
```

Exercises every supported placeholder: `<first_name>`, `<last_name>`, `<company_name>`, `<title>`, `<website>`. The assertion verifies that all five are replaced with the correct values and the surrounding punctuation is preserved.

### `test_render_template_missing_values` (lines 19–26)

```python
    contact = {
        "first_name": "Jane",
        "company_name": "",
    }
    result = render_template(template, contact)
    assert result == "Hi Jane, this is Hexa. We'd love to help ."
```

Tests the edge case where `company_name` exists in the dict but is an empty string. The function replaces `<company_name>` with `""`, resulting in "help ." with a trailing space before the period. This documents the current behavior — the function does not clean up surrounding whitespace when a value is empty.

### `test_render_template_no_placeholders` (lines 29–32)

```python
    template = "Hello, this is a static message."
    result = render_template(template, {})
    assert result == "Hello, this is a static message."
```

Tests a template with zero `<...>` placeholders. The empty dict `{}` has no values to substitute. The function returns the template string unchanged. This proves the function is safe to call even when the user writes a completely static SMS.

---

## integration/test_health.py — Health Check Test

### `test_health_check` (lines 4–7)

```python
def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

This is an integration test because it uses the `client` fixture (from `conftest.py`) to make a real HTTP request through the full FastAPI stack — middleware, routing, dependency injection, and response serialization all execute. The `client` fixture injects mock dependencies, so the health endpoint works without a database.

The test verifies two things:
1. The `/health` endpoint returns HTTP 200 (the app booted successfully and the route is registered).
2. The response body is exactly `{"status": "ok"}` (the endpoint returns the expected JSON, not an error page or redirect).

This test is intentionally minimal. Its primary purpose is to catch deployment regressions — if the app fails to start (bad import, missing env var, syntax error), this test fails immediately.

---

## Running Tests

```bash
cd hexa-cold-calling-backend
python -m pytest tests/ -v
```

To run only unit tests:
```bash
python -m pytest tests/unit/ -v
```

To run only integration tests:
```bash
python -m pytest tests/integration/ -v
```
