# Tasks — Background Jobs

This module contains background tasks that run alongside the FastAPI application. Tasks are long-running async loops that perform periodic work outside the request/response cycle.

---

## Files

| File | Purpose |
|---|---|
| `sms_scheduler.py` | Polls for due scheduled SMS messages and sends them every 60 seconds |

---

## sms_scheduler.py

### Overview

A simple async background loop that runs for the entire lifetime of the application. Every 60 seconds, it queries the database for contacts whose scheduled SMS is due and sends each one via the SMS service. It is the **consumer** side of the scheduling system — `sms_service.schedule_sms()` is the producer that marks contacts as `"to_be_messaged"` and sets their `sms_scheduled_at` timestamp.

### Constant (line 11)

```python
POLL_INTERVAL_SECONDS = 60
```

The loop sleeps for 60 seconds between each poll cycle. This means a scheduled SMS may be sent up to 60 seconds after its `sms_scheduled_at` time, which is acceptable for the use case (follow-up messages to cold-call contacts are not time-critical to the second).

### `run_sms_scheduler()` (lines 14-27)

```python
async def run_sms_scheduler() -> None:
    """Background loop that checks for and sends due scheduled SMS messages."""
    logger.info("SMS scheduler started (polling every %ds)", POLL_INTERVAL_SECONDS)

    while True:
        try:
            db = get_supabase()
            sent = sms_service.process_scheduled_messages(db)
            if sent > 0:
                logger.info("Sent %d scheduled SMS messages", sent)
        except Exception as exc:
            logger.error("SMS scheduler error: %s", exc)

        await asyncio.sleep(POLL_INTERVAL_SECONDS)
```

**Line 16 — Startup log:** Logs once at startup to confirm the scheduler is running and at what interval. Useful for verifying the background task actually started after deployment.

**Line 18 — Infinite loop:** `while True` keeps the loop running for the entire application lifetime. The loop is only broken when the task is cancelled during shutdown.

**Line 20 — Database client:** Calls `get_supabase()` from `app.dependencies` to get the Supabase client. This function is `@lru_cache`-decorated, so it returns the same client instance on every call rather than creating a new connection each cycle.

**Line 21 — Process messages:** Delegates to `sms_service.process_scheduled_messages(db)`, which:
1. Calls `contact_repo.get_contacts_needing_sms(db)` to find all contacts where `messaging_status = "to_be_messaged"` AND `sms_scheduled_at <= now()`.
2. For each contact, calls `sms_service.send_sms(db, contact_id)`, which fetches the SMS template from settings, renders it with contact data, sends it via Twilio, and updates the contact's `sms_sent`, `messaging_status`, and `sms_sent_after_calls` fields.
3. Returns the count of successfully sent messages.

**Lines 22-23 — Conditional logging:** Only logs when messages were actually sent. This prevents the log from being flooded with "Sent 0 messages" lines every 60 seconds during quiet periods.

**Lines 24-25 — Exception handling:** The bare `except Exception` catch is intentional and critical. If any error occurs (database connection failure, Twilio API error, network timeout), it is logged but the loop **continues running**. Without this catch, a single exception would kill the `while True` loop and no further scheduled messages would ever be sent until the application is restarted. This is the most important defensive pattern in the scheduler.

**Line 27 — Async sleep:** `await asyncio.sleep(POLL_INTERVAL_SECONDS)` yields control back to the event loop for 60 seconds. This is `await`-based (not `time.sleep()`), so it does not block the FastAPI event loop — HTTP requests continue to be served normally during the sleep.

### Lifecycle Management (in `main.py`)

The scheduler is started and stopped by FastAPI's lifespan context manager in `app/main.py`:

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

**Startup:** `asyncio.create_task(run_sms_scheduler())` launches the coroutine as a background task on the event loop. It starts running immediately and continues alongside all HTTP request handling.

**Shutdown:** When the application receives a shutdown signal (SIGTERM, Ctrl+C), the lifespan exits its `yield`. `task.cancel()` sends a `CancelledError` to the scheduler coroutine (which will interrupt the `asyncio.sleep()` call). The `await task` with the `except asyncio.CancelledError: pass` block ensures the task is cleanly awaited without the cancellation error propagating up to the application.

### Why Polling Instead of a Queue

A 60-second polling loop is the simplest possible implementation for this use case. The volume of scheduled SMS messages is low (tens per day, not thousands), and a 60-second delay is acceptable. A message queue (Redis, RabbitMQ, Celery) would add infrastructure complexity without meaningful benefit at this scale. If volume grows significantly, the architecture can be replaced with a task queue without changing the service layer — `sms_service.process_scheduled_messages()` would remain the same; only the trigger mechanism would change.
