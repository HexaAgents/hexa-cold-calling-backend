from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Query

from app.dependencies import SupabaseDep, CurrentUserDep
from app.schemas.productivity import ProductivityUser, ProductivityRow, ProductivityResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/productivity", tags=["productivity"])


@router.get("", response_model=ProductivityResponse)
def get_productivity(
    current_user: CurrentUserDep,
    db: SupabaseDep,
    days: int = Query(30, ge=1, le=365),
):
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    users_resp = db.auth.admin.list_users()
    user_map: dict[str, str] = {}
    users: list[ProductivityUser] = []
    for u in users_resp:
        uid = str(u.id)
        meta = u.user_metadata or {}
        full_name = meta.get("full_name", u.email or "Unknown")
        first_name = full_name.split(" ")[0] if full_name else "Unknown"
        user_map[uid] = first_name
        users.append(ProductivityUser(id=uid, first_name=first_name))

    result = (
        db.table("call_logs")
        .select("user_id, call_date")
        .gte("call_date", cutoff)
        .execute()
    )

    pivot: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in result.data or []:
        d = row["call_date"]
        uid = row["user_id"]
        pivot[d][uid] += 1

    rows: list[ProductivityRow] = []
    for d in sorted(pivot.keys(), reverse=True):
        rows.append(ProductivityRow(date=d, counts=dict(pivot[d])))

    return ProductivityResponse(users=users, rows=rows)
