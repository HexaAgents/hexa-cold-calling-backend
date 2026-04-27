"""Apply Postgres migration(s) and rescore all contacts with a website.

- Runs SQL migration file(s) against DATABASE_URL (direct Postgres URI from Supabase).
- Re-scores each distinct website (same pattern as CSV import) and updates only
  scoring columns on contacts. Does NOT read or write call_logs, so productivity
  outcome counts stay unchanged.

Usage (from repo root, with .env loaded):

    export DATABASE_URL="postgresql://postgres:...@db.xxx.supabase.co:5432/postgres"
    export SUPABASE_URL="https://xxx.supabase.co"
    export SUPABASE_SERVICE_ROLE_KEY="..."
    export OPENAI_API_KEY="..."
    export EXA_API_KEY="..."

    python scripts/rescore_all_contacts.py

Options:
    --dry-run          Print contact / website counts and outcome histogram only.
    --skip-migrate     Do not run SQL migrations (rescore only).
    --migrate-only     Run SQL migration(s) only; verify call_logs counts unchanged; exit.
    --migration PATH   SQL file to run (repeatable). Default: migrations/022_add_bad_number_outcome.sql
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

# Repo root = parent of scripts/
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from supabase import create_client  # noqa: E402

from app.config import settings  # noqa: E402
from app.repositories.contact_repo import update_contact  # noqa: E402
from app.services.import_service import SCORING_TIMEOUT  # noqa: E402
from app.services.scoring_service import score_website  # noqa: E402

logger = logging.getLogger("rescore")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

DEFAULT_MIGRATION = ROOT / "migrations" / "022_add_bad_number_outcome.sql"
PAGE_SIZE = 500
RESCORE_WORKERS = 6


def _outcome_histogram(db) -> dict[str, int]:
    """Counts call_logs rows by outcome (productivity slice)."""
    keys = ["didnt_pick_up", "interested", "not_interested", "bad_number"]
    hist: dict[str, int] = {}
    for k in keys:
        res = db.table("call_logs").select("id", count="exact").eq("outcome", k).execute()
        hist[k] = res.count or 0
    res_all = db.table("call_logs").select("id", count="exact").execute()
    hist["_all_rows"] = res_all.count or 0
    return hist


def _assert_histogram_unchanged(before: dict[str, int], after: dict[str, int]) -> None:
    for k in ("didnt_pick_up", "interested", "not_interested", "bad_number", "_all_rows"):
        if before.get(k) != after.get(k):
            raise RuntimeError(
                f"call_logs counts changed for {k!r}: before={before.get(k)} after={after.get(k)} "
                "(this script must not modify call_logs)"
            )


def _run_sql_files(paths: list[Path]) -> None:
    try:
        import psycopg
    except ImportError as exc:
        print("Install psycopg: pip install 'psycopg[binary]>=3.2'", file=sys.stderr)
        raise SystemExit(1) from exc

    db_url = (settings.database_url or os.environ.get("DATABASE_URL", "")).strip()
    if not db_url:
        raise SystemExit(
            "database_url / DATABASE_URL is required for migrations (Supabase Dashboard → "
            "Project Settings → Database → Connection string → URI)."
        )

    for path in paths:
        sql = path.read_text(encoding="utf-8")
        logger.info("Applying migration %s", path)
        with psycopg.connect(db_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)


def _fetch_contacts_with_website(db) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        res = (
            db.table("contacts")
            .select("id,website,company_name,title")
            .not_.is_("website", "null")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        batch = res.data or []
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return [r for r in rows if (r.get("website") or "").strip()]


def _group_by_website(contacts: list[dict]) -> dict[str, list[dict]]:
    by_site: dict[str, list[dict]] = defaultdict(list)
    for c in contacts:
        w = (c.get("website") or "").strip()
        if w:
            by_site[w].append(c)
    return dict(by_site)


def _score_one_website(website: str, company_name: str, job_title: str) -> tuple[str, dict]:
    try:
        data = score_website(
            exa_api_key=settings.exa_api_key,
            openai_api_key=settings.openai_api_key,
            openai_model=settings.openai_model,
            website=website,
            company_name=company_name or "Unknown",
            job_title=job_title or "",
        )
        return website, data
    except Exception as exc:
        logger.error("Scoring failed for %s: %s", website, exc)
        return website, {
            "score": 0,
            "company_type": "rejected",
            "rationale": f"Scoring error: {str(exc)[:200]}",
            "rejection_reason": "unclear",
            "exa_scrape_success": False,
            "scoring_failed": True,
            "company_description": None,
            "industry_tag": None,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Only print stats and exit")
    parser.add_argument("--skip-migrate", action="store_true", help="Skip SQL migrations")
    parser.add_argument(
        "--migrate-only",
        action="store_true",
        help="Run SQL migration(s) and exit (no rescoring; still checks call_logs counts unchanged)",
    )
    parser.add_argument(
        "--migration",
        action="append",
        type=Path,
        default=None,
        help="SQL migration file (repeatable). Defaults to 022 bad_number outcome.",
    )
    args = parser.parse_args()

    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise SystemExit("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (e.g. in .env)")

    db = create_client(settings.supabase_url, settings.supabase_service_role_key)

    before_hist = _outcome_histogram(db)
    logger.info("call_logs snapshot: %s", before_hist)

    contacts = _fetch_contacts_with_website(db)
    by_site = _group_by_website(contacts)
    logger.info("Contacts with website: %s rows, %s distinct websites", len(contacts), len(by_site))

    if args.dry_run:
        logger.info("Dry run — no migration or rescore.")
        return

    if args.migrate_only:
        raw_paths = [Path(p) for p in args.migration] if args.migration else [DEFAULT_MIGRATION]
        migration_paths = []
        for p in raw_paths:
            path = p if p.is_absolute() else ROOT / p
            if not path.exists():
                raise SystemExit(f"Migration file not found: {path}")
            migration_paths.append(path)
        db_url = (settings.database_url or os.environ.get("DATABASE_URL", "")).strip()
        if not db_url:
            raise SystemExit("database_url / DATABASE_URL required for --migrate-only")
        _run_sql_files(migration_paths)
        after_hist = _outcome_histogram(db)
        logger.info("call_logs snapshot after migrate: %s", after_hist)
        _assert_histogram_unchanged(before_hist, after_hist)
        logger.info("Migrations applied; call_logs unchanged.")
        return

    raw_paths = [Path(p) for p in args.migration] if args.migration else [DEFAULT_MIGRATION]
    migration_paths: list[Path] = []
    for p in raw_paths:
        path = p if p.is_absolute() else ROOT / p
        if not path.exists():
            raise SystemExit(f"Migration file not found: {path}")
        migration_paths.append(path)

    if not args.skip_migrate:
        db_url = (settings.database_url or os.environ.get("DATABASE_URL", "")).strip()
        if not db_url:
            logger.warning(
                "database_url / DATABASE_URL not set — skipping SQL migrations. "
                "Add the Postgres URI from Supabase (Settings → Database) to .env to run them."
            )
        else:
            _run_sql_files(migration_paths)

    if not settings.exa_api_key or not settings.openai_api_key:
        raise SystemExit("Set EXA_API_KEY and OPENAI_API_KEY for rescoring")

    # Re-score each distinct website; apply result to every contact on that site.
    work: list[tuple[str, str, str]] = []
    for website, group in by_site.items():
        rep = group[0]
        work.append(
            (
                website,
                (rep.get("company_name") or "").strip() or "Unknown",
                (rep.get("title") or "").strip(),
            )
        )

    scores_by_website: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=RESCORE_WORKERS) as ex:
        futures = {ex.submit(_score_one_website, w, cn, jt): w for w, cn, jt in work}
        for fut in as_completed(futures):
            website = futures[fut]
            try:
                w, data = fut.result(timeout=SCORING_TIMEOUT + 30)
                scores_by_website[w] = data
            except Exception as exc:
                logger.error("Future failed for %s: %s", website, exc)
                scores_by_website[website] = {
                    "score": 0,
                    "company_type": "rejected",
                    "rationale": f"Scoring error: {str(exc)[:200]}",
                    "rejection_reason": "unclear",
                    "exa_scrape_success": False,
                    "scoring_failed": True,
                    "company_description": None,
                    "industry_tag": None,
                }
            time.sleep(0.05)

    updated = 0
    for website, group in by_site.items():
        data = scores_by_website.get(website)
        if not data:
            continue
        payload = {
            "score": data.get("score", 0),
            "company_type": data.get("company_type", "rejected"),
            "rationale": data.get("rationale"),
            "rejection_reason": data.get("rejection_reason"),
            "company_description": data.get("company_description"),
            "industry_tag": data.get("industry_tag"),
            "exa_scrape_success": data.get("exa_scrape_success", False),
            "scoring_failed": data.get("scoring_failed", False),
            "hidden": data.get("company_type") == "rejected",
        }
        for c in group:
            update_contact(db, c["id"], payload)
            updated += 1

    logger.info("Updated %s contact rows (scoring fields only)", updated)

    after_hist = _outcome_histogram(db)
    logger.info("call_logs snapshot after: %s", after_hist)
    _assert_histogram_unchanged(before_hist, after_hist)
    logger.info("Verified call_logs outcome totals unchanged.")


if __name__ == "__main__":
    main()
