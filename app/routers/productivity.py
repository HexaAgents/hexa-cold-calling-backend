from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

from app.dependencies import SupabaseDep, CurrentUserDep
from app.schemas.productivity import (
    ProductivityUser,
    ProductivityRow,
    ProductivityResponse,
    OutcomeBreakdown,
    UserOutcomeBreakdown,
    HourBucket,
    HeatCell,
    BestWindow,
    BestCallTimesResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/productivity", tags=["productivity"])

# PostgREST/Supabase caps a single response at `max-rows` (default 1000). A
# bare `.select().execute()` therefore silently truncates large result sets,
# which is what made the productivity counters freeze at 1000 calls. We page
# through with `.range()` until a page comes back smaller than the page size.
_PAGE_SIZE = 1000

# Times are bucketed in the caller's (San Francisco / Pacific) timezone so the
# "best time to call" reads directly off a rep's own clock.
_DISPLAY_TZ = "America/Los_Angeles"
_DISPLAY_ZONE = ZoneInfo(_DISPLAY_TZ)

# Below this many calls a bucket's rate is too noisy to trust, so we exclude it
# from the "best time" recommendations (but still display it, de-emphasized).
_MIN_SAMPLE = 15

_PICKUP_OUTCOMES = {"interested", "not_interested"}


def _fetch_call_logs_since(db, cutoff: str) -> list[dict]:
    rows: list[dict] = []
    start = 0
    while True:
        page = (
            db.table("call_logs")
            .select("user_id, call_date, outcome")
            .gte("call_date", cutoff)
            .range(start, start + _PAGE_SIZE - 1)
            .execute()
            .data
            or []
        )
        rows.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        start += _PAGE_SIZE
    return rows


@router.get("", response_model=ProductivityResponse)
def get_productivity(
    current_user: CurrentUserDep,
    db: SupabaseDep,
    days: int = Query(30, ge=1, le=365),
):
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    users_result = db.rpc("get_auth_users").execute()
    user_map: dict[str, str] = {}
    users: list[ProductivityUser] = []
    for u in users_result.data or []:
        uid = str(u["id"])
        meta = u.get("raw_user_meta_data") or {}
        full_name = meta.get("full_name", u.get("email") or "Unknown")
        first_name = full_name.split(" ")[0] if full_name else "Unknown"
        user_map[uid] = first_name
        users.append(ProductivityUser(id=uid, first_name=first_name))

    log_rows = _fetch_call_logs_since(db, cutoff)

    pivot: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    overall: dict[str, int] = defaultdict(int)
    per_user: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for row in log_rows:
        d = row["call_date"]
        uid = row["user_id"]
        outcome = row.get("outcome") or "other"
        pivot[d][uid] += 1
        overall[outcome] += 1
        overall["total"] += 1
        per_user[uid][outcome] += 1
        per_user[uid]["total"] += 1

    rows: list[ProductivityRow] = []
    for d in sorted(pivot.keys(), reverse=True):
        rows.append(ProductivityRow(date=d, counts=dict(pivot[d])))

    def _breakdown(counts: dict[str, int]) -> OutcomeBreakdown:
        return OutcomeBreakdown(
            total=counts.get("total", 0),
            didnt_pick_up=counts.get("didnt_pick_up", 0),
            interested=counts.get("interested", 0),
            not_interested=counts.get("not_interested", 0),
            bad_number=counts.get("bad_number", 0),
            other=counts.get("total", 0) - counts.get("didnt_pick_up", 0) - counts.get("interested", 0) - counts.get("not_interested", 0) - counts.get("bad_number", 0),
        )

    user_breakdowns = [
        UserOutcomeBreakdown(
            user_id=uid,
            first_name=user_map.get(uid, "Unknown"),
            breakdown=_breakdown(per_user[uid]),
        )
        for uid in per_user
    ]

    return ProductivityResponse(
        users=users,
        rows=rows,
        overall_breakdown=_breakdown(overall),
        per_user_breakdown=user_breakdowns,
    )


def _fetch_call_times_since(db, cutoff: str) -> list[dict]:
    """Page through call_logs since `cutoff`."""
    rows: list[dict] = []
    start = 0
    while True:
        page = (
            db.table("call_logs")
            .select("created_at, outcome")
            .gte("call_date", cutoff)
            .range(start, start + _PAGE_SIZE - 1)
            .execute()
            .data
            or []
        )
        rows.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        start += _PAGE_SIZE
    return rows


@router.get("/best-call-times", response_model=BestCallTimesResponse)
def get_best_call_times(
    current_user: CurrentUserDep,
    db: SupabaseDep,
    days: int = Query(90, ge=1, le=365),
):
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    log_rows = _fetch_call_times_since(db, cutoff)

    # hour -> {total, pickups, interested}; (weekday, hour) -> {total, pickups}
    hour_acc: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    grid_acc: dict[tuple[int, int], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    total_calls = 0
    total_pickups = 0

    for row in log_rows:
        created = row.get("created_at")
        if not created:
            continue
        try:
            dt = datetime.fromisoformat(created)
        except ValueError:
            continue

        local = dt.astimezone(_DISPLAY_ZONE)
        hour = local.hour
        weekday = local.weekday()  # Monday = 0 .. Sunday = 6

        outcome = row.get("outcome")
        is_pickup = 1 if outcome in _PICKUP_OUTCOMES else 0
        is_interested = 1 if outcome == "interested" else 0

        total_calls += 1
        total_pickups += is_pickup

        h = hour_acc[hour]
        h["total"] += 1
        h["pickups"] += is_pickup
        h["interested"] += is_interested

        g = grid_acc[(weekday, hour)]
        g["total"] += 1
        g["pickups"] += is_pickup

    hours: list[HourBucket] = []
    for hour in sorted(hour_acc.keys()):
        c = hour_acc[hour]
        total = c["total"]
        hours.append(
            HourBucket(
                hour=hour,
                total=total,
                pickups=c["pickups"],
                interested=c["interested"],
                pickup_rate=(c["pickups"] / total) if total else 0.0,
                interested_rate=(c["interested"] / total) if total else 0.0,
            )
        )

    heatmap: list[HeatCell] = []
    for (weekday, hour), c in grid_acc.items():
        total = c["total"]
        heatmap.append(
            HeatCell(
                weekday=weekday,
                hour=hour,
                total=total,
                pickups=c["pickups"],
                pickup_rate=(c["pickups"] / total) if total else 0.0,
            )
        )
    heatmap.sort(key=lambda x: (x.weekday, x.hour))

    eligible_hours = [h for h in hours if h.total >= _MIN_SAMPLE]
    best_hour = max(eligible_hours, key=lambda h: h.pickup_rate) if eligible_hours else None

    eligible_cells = [c for c in heatmap if c.total >= _MIN_SAMPLE]
    best_window = None
    if eligible_cells:
        top = max(eligible_cells, key=lambda c: c.pickup_rate)
        best_window = BestWindow(
            weekday=top.weekday,
            hour=top.hour,
            total=top.total,
            pickup_rate=top.pickup_rate,
        )

    return BestCallTimesResponse(
        timezone=_DISPLAY_TZ,
        min_sample=_MIN_SAMPLE,
        total_calls=total_calls,
        overall_pickup_rate=(total_pickups / total_calls) if total_calls else 0.0,
        hours=hours,
        heatmap=heatmap,
        best_hour=best_hour,
        best_window=best_window,
    )
