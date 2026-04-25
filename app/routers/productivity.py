from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Query

from app.dependencies import SupabaseDep, CurrentUserDep
from app.schemas.productivity import ProductivityUser, ProductivityRow, ProductivityResponse, OutcomeBreakdown, UserOutcomeBreakdown

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/productivity", tags=["productivity"])


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

    result = (
        db.table("call_logs")
        .select("user_id, call_date, outcome")
        .gte("call_date", cutoff)
        .execute()
    )

    pivot: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    overall: dict[str, int] = defaultdict(int)
    per_user: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for row in result.data or []:
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
