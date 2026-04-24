from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.dependencies import get_supabase
from app.repositories import import_batch_repo
from app.routers import auth, contacts, imports, calls, twilio_webhooks, sms, notes, settings as settings_router, apollo_webhooks, apollo_enrichment, productivity, email
from app.services import apollo_service
from app.tasks.sms_scheduler import run_sms_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_STALE_SWEEP_INTERVAL = 120
_ENRICHMENT_SWEEP_INTERVAL = 600


async def _sweep_stale_imports_loop() -> None:
    """Periodically mark stale 'processing' imports as failed."""
    while True:
        await asyncio.sleep(_STALE_SWEEP_INTERVAL)
        try:
            db = get_supabase()
            import_batch_repo.recover_stale_imports(db)
        except Exception as exc:
            logger.error("Stale import sweep failed: %s", exc)


async def _sweep_enrichment_loop() -> None:
    """Every 10 min, recover contacts stuck in 'enriching' and auto-retry transient enrichment failures."""
    while True:
        await asyncio.sleep(_ENRICHMENT_SWEEP_INTERVAL)
        try:
            db = get_supabase()
            # Runs synchronously (contains blocking Apollo HTTP + sleeps). Offload to a
            # thread so we don't block the event loop.
            await asyncio.to_thread(apollo_service.sweep_stuck_enrichments, db, False)
        except Exception as exc:
            logger.error("Enrichment sweep failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        db = get_supabase()
        import_batch_repo.recover_stale_imports(db)
    except Exception as exc:
        logger.error("Startup stale recovery failed: %s", exc)

    # One-shot sweep at startup: recover anything left stuck between restarts.
    try:
        db = get_supabase()
        await asyncio.to_thread(apollo_service.sweep_stuck_enrichments, db, False)
    except Exception as exc:
        logger.error("Startup enrichment sweep failed: %s", exc)

    sms_task = asyncio.create_task(run_sms_scheduler())
    sweep_task = asyncio.create_task(_sweep_stale_imports_loop())
    enrich_task = asyncio.create_task(_sweep_enrichment_loop())
    yield
    enrich_task.cancel()
    sweep_task.cancel()
    sms_task.cancel()
    for t in (enrich_task, sweep_task, sms_task):
        try:
            await t
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
app.include_router(apollo_webhooks.router)
app.include_router(apollo_enrichment.router)
app.include_router(productivity.router)
app.include_router(email.router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
