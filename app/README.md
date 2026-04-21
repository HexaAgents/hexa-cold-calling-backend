# `app/` — Application Root Package

This document provides an exhaustive, line-by-line reference for the three root-level files that compose the FastAPI application skeleton:

| File | Responsibility |
|---|---|
| `config.py` | Load and validate environment variables into a typed settings object |
| `dependencies.py` | Provide injectable dependencies (database client, authenticated user) |
| `main.py` | Create the ASGI app, register middleware, mount routers, manage background tasks |

Together they form the **bootstrap layer** — the thinnest possible shell that wires everything else together without containing any business logic.

---

## Table of Contents

1. [config.py — Environment & Settings](#configpy--environment--settings)
2. [dependencies.py — Dependency Injection](#dependenciespy--dependency-injection)
3. [main.py — Application Factory & Entrypoint](#mainpy--application-factory--entrypoint)
4. [SOLID Principles in Practice](#solid-principles-in-practice)

---

## `config.py` — Environment & Settings

### Purpose

Centralise **every** tuneable value the application needs into a single, validated, type-safe object. No other module reads `os.environ` directly — they all import `settings` from here.

### Full Source

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    openai_api_key: str = ""
    exa_api_key: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""
    twilio_twiml_app_sid: str = ""
    openai_model: str = "gpt-4o-mini"
    frontend_url: str = "http://localhost:3000"
    allowed_origins: str = "http://localhost:3000"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()  # type: ignore[call-arg]
```

### Line-by-Line Breakdown

#### Import (line 1)

```python
from pydantic_settings import BaseSettings
```

`BaseSettings` is the foundation class from the [`pydantic-settings`](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) library. Unlike plain `BaseModel`, it automatically reads values from **environment variables** (case-insensitive) and from `.env` files. This single import replaces all manual `os.getenv()` calls and gives us automatic type coercion and validation for free.

#### `Settings` Class (lines 4–21)

```python
class Settings(BaseSettings):
```

Inheriting from `BaseSettings` means every field declared below maps 1-to-1 with an environment variable of the same name (uppercased). For example, the field `supabase_url` is populated from the env var `SUPABASE_URL`.

##### Field: `supabase_url` (line 5)

```python
supabase_url: str = ""
```

The base URL of the Supabase project (e.g. `https://xyzcompany.supabase.co`). Used by `dependencies.py` to initialise the Supabase client. Defaults to an empty string so the container process can start even if the variable is not yet injected — this is critical for container orchestrators that deliver secrets after the process forks.

##### Field: `supabase_service_role_key` (line 6)

```python
supabase_service_role_key: str = ""
```

The **service-role** key for Supabase. This key bypasses Row-Level Security, so it is used server-side only. Combined with `supabase_url` to construct the admin Supabase client. Defaults to empty string for the same late-injection safety as above.

##### Field: `openai_api_key` (line 7)

```python
openai_api_key: str = ""
```

API key for OpenAI. Consumed by any service that calls GPT models (e.g. lead scoring, call summarisation). Empty default prevents a crash at import time if the secret is delivered asynchronously.

##### Field: `exa_api_key` (line 8)

```python
exa_api_key: str = ""
```

API key for the [Exa](https://exa.ai) search API, used for web-based lead enrichment. Same empty-default pattern.

##### Fields: Twilio Credentials (lines 9–12)

```python
twilio_account_sid: str = ""
twilio_auth_token: str = ""
twilio_phone_number: str = ""
twilio_twiml_app_sid: str = ""
```

| Field | Purpose |
|---|---|
| `twilio_account_sid` | Identifies the Twilio account. Required for every Twilio API call. |
| `twilio_auth_token` | Secret used to authenticate Twilio REST requests and to validate incoming webhook signatures. |
| `twilio_phone_number` | The outbound caller ID (E.164 format, e.g. `+15551234567`). Used when placing calls or sending SMS. |
| `twilio_twiml_app_sid` | SID of the TwiML Application resource that routes browser-initiated VoIP calls to the correct webhook URL. |

All four default to empty strings to allow graceful boot before secrets are available.

##### Field: `openai_model` (line 13)

```python
openai_model: str = "gpt-4o-mini"
```

The OpenAI model identifier used throughout the application. Defaults to `gpt-4o-mini` — a cost-effective model suitable for the call-summarisation and lead-scoring workloads. Override with `OPENAI_MODEL=gpt-4o` in production to switch models without code changes.

##### Field: `frontend_url` (line 14)

```python
frontend_url: str = "http://localhost:3000"
```

The URL of the Next.js frontend. Referenced when the backend needs to generate links that point back to the UI (e.g. in SMS messages or email notifications). Defaults to the local dev server.

##### Field: `allowed_origins` (line 15)

```python
allowed_origins: str = "http://localhost:3000"
```

A **comma-separated** string of origins that are permitted by the CORS middleware. Stored as a flat string because environment variables are inherently scalar. The `cors_origins` property (below) parses it into a list at access time.

##### Property: `cors_origins` (lines 17–19)

```python
@property
def cors_origins(self) -> list[str]:
    return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]
```

Transforms the raw `allowed_origins` string into a clean `list[str]`. The list comprehension:

1. Splits on commas.
2. Strips leading/trailing whitespace from each entry.
3. Filters out empty strings (handles trailing commas or accidental double-commas).

This property is consumed directly by `CORSMiddleware` in `main.py`.

##### `model_config` (line 21)

```python
model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
```

Pydantic v2 configuration dict (replaces the inner `class Config` from v1). Tells `BaseSettings` to also look for a `.env` file in the working directory and read it as UTF-8. Environment variables set in the actual shell **take precedence** over values in `.env`, which is the standard 12-factor convention.

#### Module-Level Singleton (line 24)

```python
settings = Settings()  # type: ignore[call-arg]
```

Instantiates a single `Settings` object at **module import time**. Because Python modules are singletons, every file that does `from app.config import settings` receives the same object — no duplicate parsing, no inconsistent state.

The `# type: ignore[call-arg]` comment suppresses a mypy false positive that occurs because all constructor arguments have defaults supplied by the environment rather than by explicit keyword arguments.

---

## `dependencies.py` — Dependency Injection

### Purpose

Define **reusable FastAPI dependencies** that route handlers declare via type hints. This keeps route functions free of boilerplate (no manual header parsing, no repeated client construction) and makes every dependency independently testable via `app.dependency_overrides`.

### Full Source

```python
from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Header
from supabase import create_client, Client

from app.config import settings


@lru_cache
def get_supabase() -> Client:
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    db: Client = Depends(get_supabase),
) -> dict:
    """Validate the JWT from the Authorization header and return user info."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        user_response = db.auth.get_user(token)
        if not user_response or not user_response.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = user_response.user
        return {
            "id": str(user.id),
            "email": user.email,
            "full_name": (user.user_metadata or {}).get("full_name", ""),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {exc}")


SupabaseDep = Annotated[Client, Depends(get_supabase)]
CurrentUserDep = Annotated[dict, Depends(get_current_user)]
```

### Line-by-Line Breakdown

#### Imports (lines 1–9)

```python
from __future__ import annotations
```

Enables **PEP 604** union syntax (`str | None`) on all Python 3.9+ versions by deferring annotation evaluation. Without this import, `str | None` would raise a `TypeError` at class-definition time on Python < 3.10.

```python
from functools import lru_cache
```

`lru_cache` is a decorator from the standard library that memoises the return value of a function based on its arguments. Since `get_supabase()` takes zero arguments, the decorator effectively turns it into a **singleton factory** — the Supabase client is created once and reused for the lifetime of the process.

```python
from typing import Annotated
```

`Annotated` allows attaching metadata to type hints. FastAPI uses this metadata to resolve dependencies, extract headers, validate query parameters, and more. It is the modern replacement for the older `param: str = Header()` signature style.

```python
from fastapi import Depends, HTTPException, Header
```

| Symbol | Role |
|---|---|
| `Depends` | Declares that a parameter should be resolved by calling another function (the dependency). |
| `HTTPException` | A raise-able exception that FastAPI converts into an HTTP error response with the given status code and detail message. |
| `Header` | Tells FastAPI to extract the parameter value from an HTTP request header instead of a query parameter. |

```python
from supabase import create_client, Client
```

| Symbol | Role |
|---|---|
| `create_client` | Factory function that returns a configured Supabase `Client`. Takes a project URL and a key. |
| `Client` | The type annotation for a Supabase client instance. Used both for type hints and as the binding in `Annotated`. |

```python
from app.config import settings
```

Imports the module-level singleton from `config.py`. This is the **only** place settings are read in this file — the dependency functions themselves never touch environment variables directly.

#### `get_supabase()` — Database Client Factory (lines 12–14)

```python
@lru_cache
def get_supabase() -> Client:
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
```

**Decorator: `@lru_cache`**
Ensures `create_client` is called exactly once. Every subsequent call returns the cached `Client` instance. This matters because creating a client involves network handshakes and connection setup — doing it per-request would be wasteful.

**Parameters:** None. The function is zero-arity by design so that `lru_cache` can memoise it without key complexity.

**Return value:** A fully initialised `supabase.Client` connected with the **service-role key**, which means it has admin-level access and bypasses Supabase Row-Level Security. This is appropriate for a trusted backend but must never be exposed to the client.

**Why a function and not a plain module-level variable?**
FastAPI's `Depends()` mechanism requires a callable. Wrapping the client in a function also makes it trivially overridable in tests:

```python
app.dependency_overrides[get_supabase] = lambda: mock_client
```

#### `get_current_user()` — Authentication Dependency (lines 17–39)

```python
async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    db: Client = Depends(get_supabase),
) -> dict:
```

**Parameter: `authorization`**
Type: `Annotated[str | None, Header()]` — FastAPI extracts the `Authorization` HTTP header and passes it here. If the header is absent, the value is `None` (the default). The `Annotated` wrapper keeps the function signature clean while still carrying the `Header()` metadata.

**Parameter: `db`**
Type: `Client`, resolved via `Depends(get_supabase)`. This injects the cached Supabase client so the function can validate tokens without constructing its own client. It also means tests can override `get_supabase` once and the override propagates into `get_current_user` automatically.

**Return type:** `dict` with keys `id`, `email`, and `full_name`.

##### Guard Clause (lines 22–23)

```python
if not authorization or not authorization.startswith("Bearer "):
    raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
```

Rejects the request immediately if:
- The `Authorization` header is missing entirely (`not authorization`).
- The header is present but does not follow the `Bearer <token>` scheme.

Returns HTTP **401 Unauthorized** with a descriptive message.

##### Token Extraction (line 25)

```python
token = authorization.removeprefix("Bearer ").strip()
```

`str.removeprefix()` (Python 3.9+) strips the literal prefix `"Bearer "` and `.strip()` removes any accidental leading/trailing whitespace. The result is the raw JWT string.

##### Supabase Token Validation (lines 26–35)

```python
try:
    user_response = db.auth.get_user(token)
    if not user_response or not user_response.user:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = user_response.user
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": (user.user_metadata or {}).get("full_name", ""),
    }
```

`db.auth.get_user(token)` sends the JWT to Supabase's GoTrue server for verification. Supabase checks the signature, expiry, and audience claims. If the token is valid, the response contains the full user object.

The returned dict is intentionally minimal — only the fields downstream handlers actually need:

| Key | Source | Notes |
|---|---|---|
| `id` | `user.id` | Cast to `str` because Supabase returns a UUID object. |
| `email` | `user.email` | The user's verified email address. |
| `full_name` | `user.user_metadata.full_name` | Extracted from the JSONB metadata column. Falls back to an empty string via `.get("full_name", "")` if the key is missing. The `or {}` guard handles the case where `user_metadata` itself is `None`. |

##### Exception Handling (lines 36–39)

```python
except HTTPException:
    raise
except Exception as exc:
    raise HTTPException(status_code=401, detail=f"Authentication failed: {exc}")
```

Two-tier catch:

1. **`HTTPException`** — Re-raised as-is. These are the intentional 401s thrown above; wrapping them again would lose the original detail message.
2. **`Exception`** — Catches any unexpected failure (network timeout, malformed response, Supabase SDK bug) and converts it into a generic 401. This prevents internal stack traces from leaking to the caller while still surfacing the exception message for server-side debugging.

#### Type Aliases (lines 42–43)

```python
SupabaseDep = Annotated[Client, Depends(get_supabase)]
CurrentUserDep = Annotated[dict, Depends(get_current_user)]
```

These are **`Annotated` type aliases** — a pattern recommended by the FastAPI documentation. Instead of writing `db: Client = Depends(get_supabase)` in every route handler, you write `db: SupabaseDep`. This provides:

- **DRY signatures** — the dependency wiring is defined once.
- **Refactorability** — changing the underlying dependency function only requires editing this one line.
- **Readability** — route handlers read like a contract: "I need a Supabase client" or "I need the current user."

Usage in a router:

```python
@router.get("/contacts")
async def list_contacts(db: SupabaseDep, user: CurrentUserDep):
    ...
```

---

## `main.py` — Application Factory & Entrypoint

### Purpose

Construct the ASGI application object, attach cross-cutting middleware, mount all feature routers, and manage the lifecycle of background tasks. This is the file that Uvicorn (or any ASGI server) points at: `uvicorn app.main:app`.

### Full Source

```python
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import auth, contacts, imports, calls, twilio_webhooks, sms, notes, settings as settings_router
from app.tasks.sms_scheduler import run_sms_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(run_sms_scheduler())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Hexa Cold Calling API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(contacts.router)
app.include_router(imports.router)
app.include_router(calls.router)
app.include_router(twilio_webhooks.router)
app.include_router(sms.router)
app.include_router(notes.router)
app.include_router(settings_router.router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
```

### Line-by-Line Breakdown

#### Imports (lines 1–12)

```python
from __future__ import annotations
```

Same purpose as in `dependencies.py` — enables deferred annotation evaluation for modern union syntax.

```python
import asyncio
```

The standard-library async I/O module. Used here for `asyncio.create_task()` to spawn the SMS scheduler as a background coroutine, and `asyncio.CancelledError` to handle its graceful shutdown.

```python
import logging
```

Python's built-in logging framework. Configured once at module level (line 14) so that every logger in the application inherits the same format and level.

```python
from contextlib import asynccontextmanager
```

A decorator that turns an `async def` generator function into an async context manager. FastAPI's `lifespan` parameter expects exactly this shape — an async context manager that yields once (separating startup logic from shutdown logic).

```python
from fastapi import FastAPI
```

The core application class. `FastAPI()` returns an ASGI-compatible application object that Uvicorn serves.

```python
from fastapi.middleware.cors import CORSMiddleware
```

Middleware that injects the appropriate `Access-Control-Allow-*` response headers to support Cross-Origin Resource Sharing. Without it, browsers would block requests from the frontend (`localhost:3000`) to the backend (`localhost:8000`).

```python
from app.config import settings
```

The settings singleton. Used here to read `cors_origins` for the CORS middleware configuration.

```python
from app.routers import auth, contacts, imports, calls, twilio_webhooks, sms, notes, settings as settings_router
```

Imports every feature router module. Each module exposes a `router` attribute (a `fastapi.APIRouter` instance) that groups related endpoints under a common prefix and tag.

The `settings` router is aliased to `settings_router` to avoid shadowing the `settings` object imported from `app.config`.

| Router Module | Domain |
|---|---|
| `auth` | Sign-up, login, token refresh, password reset |
| `contacts` | CRUD operations for contacts/leads |
| `imports` | Bulk CSV/spreadsheet import of contacts |
| `calls` | Call records, summaries, and call initiation |
| `twilio_webhooks` | Inbound webhooks from Twilio (call status, voice) |
| `sms` | SMS conversations and message history |
| `notes` | Per-contact notes |
| `settings` | User-level application settings |

```python
from app.tasks.sms_scheduler import run_sms_scheduler
```

Imports the long-running coroutine that periodically checks for scheduled SMS messages and dispatches them via Twilio. It runs as a background task for the entire lifetime of the application process.

#### Logging Configuration (line 14)

```python
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
```

Configures the **root logger** so all `logging.getLogger(__name__)` calls throughout the codebase inherit these defaults:

| Parameter | Value | Effect |
|---|---|---|
| `level` | `logging.INFO` | Suppresses `DEBUG` messages in production; shows `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `format` | `"%(asctime)s %(name)s %(levelname)s %(message)s"` | Produces structured, timestamp-prefixed lines for easy parsing by log aggregators (e.g. `2026-04-20 12:00:00,123 app.routers.calls INFO Call initiated`). |

#### `lifespan()` — Startup & Shutdown Manager (lines 17–25)

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(run_sms_scheduler())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
```

FastAPI's **lifespan** protocol replaces the older `@app.on_event("startup")` / `@app.on_event("shutdown")` decorators. Everything **before** `yield` runs at startup; everything **after** `yield` runs at shutdown.

**Startup (line 19):**

```python
task = asyncio.create_task(run_sms_scheduler())
```

Schedules `run_sms_scheduler()` as a concurrent `Task` on the running event loop. `create_task` returns immediately — the scheduler runs in the background alongside request handling.

**Yield (line 20):**

```python
yield
```

Control passes to FastAPI. The application is now accepting requests. The `yield` acts as the boundary between "app is starting" and "app is shutting down."

**Shutdown (lines 21–25):**

```python
task.cancel()
try:
    await task
except asyncio.CancelledError:
    pass
```

`task.cancel()` sends a `CancelledError` into the scheduler coroutine at its next `await` point. `await task` waits for the cancellation to propagate. The `except asyncio.CancelledError: pass` block is the standard pattern to suppress the expected exception so shutdown completes cleanly without tracebacks in the logs.

#### Application Construction (lines 28–32)

```python
app = FastAPI(
    title="Hexa Cold Calling API",
    version="1.0.0",
    lifespan=lifespan,
)
```

| Parameter | Purpose |
|---|---|
| `title` | Shown in the auto-generated OpenAPI (Swagger) documentation at `/docs`. |
| `version` | Semantic version string displayed in the API docs. |
| `lifespan` | The async context manager defined above. Binds the scheduler's lifecycle to the app's lifecycle. |

#### CORS Middleware (lines 34–40)

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

| Parameter | Value | Effect |
|---|---|---|
| `allow_origins` | `settings.cors_origins` | Only origins in this list receive a valid `Access-Control-Allow-Origin` header. Parsed from the `ALLOWED_ORIGINS` env var. |
| `allow_credentials` | `True` | Permits the browser to send cookies and `Authorization` headers in cross-origin requests. Required because the frontend sends JWTs. |
| `allow_methods` | `["*"]` | Allows all HTTP methods (`GET`, `POST`, `PUT`, `DELETE`, `PATCH`, `OPTIONS`). |
| `allow_headers` | `["*"]` | Allows all request headers. Necessary because the frontend sends custom headers like `Authorization`. |

#### Router Registration (lines 42–49)

```python
app.include_router(auth.router)
app.include_router(contacts.router)
app.include_router(imports.router)
app.include_router(calls.router)
app.include_router(twilio_webhooks.router)
app.include_router(sms.router)
app.include_router(notes.router)
app.include_router(settings_router.router)
```

Each call mounts a router's endpoints onto the application. The routers define their own `prefix` (e.g. `/api/contacts`) and `tags` internally, so `main.py` does not need to know about URL structures. This is the **Open/Closed** principle in action — extending the API with a new domain requires only adding one `app.include_router(new_module.router)` line here.

#### Health Check Endpoint (lines 52–54)

```python
@app.get("/health")
def health_check():
    return {"status": "ok"}
```

A minimal `GET /health` endpoint that returns `{"status": "ok"}` with a `200` status code. Used by:

- **Container orchestrators** (Docker, ECS, Kubernetes) as a liveness/readiness probe.
- **Load balancers** to determine whether the instance should receive traffic.
- **Uptime monitors** (e.g. UptimeRobot, Datadog) to alert on downtime.

The function is intentionally synchronous (`def` not `async def`) because it performs no I/O — FastAPI runs it in a threadpool automatically, avoiding unnecessary coroutine overhead.

---

## SOLID Principles in Practice

### Single Responsibility Principle

Each file has exactly **one reason to change**:

| File | Changes when… |
|---|---|
| `config.py` | A new environment variable is introduced or a default changes. |
| `dependencies.py` | The authentication flow changes or a new shared dependency is needed. |
| `main.py` | A router is added/removed, middleware changes, or the startup lifecycle evolves. |

No file mixes concerns. Configuration does not authenticate. Authentication does not wire routers. The entrypoint does not parse tokens.

### Dependency Inversion Principle

Route handlers never instantiate their own `Client` or parse their own headers. They declare abstract needs through type aliases:

```python
async def list_contacts(db: SupabaseDep, user: CurrentUserDep):
    ...
```

The concrete resolution (`create_client(...)`, `db.auth.get_user(...)`) is defined in `dependencies.py` and injected by FastAPI's DI container at request time. This means:

- Routers can be tested with mock dependencies via `app.dependency_overrides`.
- Swapping Supabase for another provider requires changing only `dependencies.py` — zero router modifications.

### Open/Closed Principle

The application is **open for extension** (add a new feature router) but **closed for modification** (existing routers and middleware are untouched). The extension point is a single line:

```python
app.include_router(new_feature.router)
```

No existing code needs to change. The new router brings its own prefix, tags, dependencies, and endpoint definitions.
