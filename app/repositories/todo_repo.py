from __future__ import annotations

from supabase import Client


def _legacy_assignee(row: dict) -> list[dict]:
    if not row.get("assigned_to_id"):
        return []
    return [{"id": str(row["assigned_to_id"]), "first_name": row.get("assigned_to_name") or "Unknown"}]


def _normalize_assignees(row: dict) -> dict:
    assignees = row.get("assignees") or _legacy_assignee(row)
    row["assignees"] = assignees
    first = assignees[0] if assignees else None
    row["assigned_to_id"] = first["id"] if first else None
    row["assigned_to_name"] = first["first_name"] if first else None
    return row


def _attach_assignees(db: Client, rows: list[dict]) -> list[dict]:
    if not rows:
        return []

    todo_ids = [r["id"] for r in rows]
    result = (
        db.table("todo_assignees")
        .select("todo_id,user_id,first_name")
        .in_("todo_id", todo_ids)
        .execute()
    )
    grouped: dict[str, list[dict]] = {}
    for item in result.data or []:
        grouped.setdefault(str(item["todo_id"]), []).append(
            {"id": str(item["user_id"]), "first_name": item["first_name"]}
        )

    normalized: list[dict] = []
    for row in rows:
        row = dict(row)
        row["assignees"] = grouped.get(str(row["id"]), _legacy_assignee(row))
        normalized.append(_normalize_assignees(row))
    return normalized


def _mirror_first_assignee(data: dict, assignees: list[dict] | None) -> dict:
    if assignees is None:
        return data
    first = assignees[0] if assignees else None
    return {
        **data,
        "assigned_to_id": first["id"] if first else None,
        "assigned_to_name": first["first_name"] if first else None,
    }


def _replace_assignees(db: Client, todo_id: str, assignees: list[dict]) -> None:
    db.table("todo_assignees").delete().eq("todo_id", todo_id).execute()
    if not assignees:
        return
    rows = [
        {
            "todo_id": todo_id,
            "user_id": a["id"],
            "first_name": a["first_name"],
        }
        for a in assignees
    ]
    db.table("todo_assignees").insert(rows).execute()


def get_todos(db: Client) -> list[dict]:
    # Open tasks first, then completed tasks; each group sorts by closest due date.
    result = (
        db.table("todos")
        .select("*")
        .order("is_done", desc=False)
        .order("due_date", desc=False, nullsfirst=False)
        .order("created_at", desc=False)
        .execute()
    )
    return _attach_assignees(db, result.data or [])


def get_overdue_todos(db: Client, today: str) -> list[dict]:
    """Open todos whose due date has passed, with assignees attached.

    `today` is an ISO date string (YYYY-MM-DD); a todo is overdue when its
    due_date is strictly before it.
    """
    result = (
        db.table("todos")
        .select("*")
        .eq("is_done", False)
        .lt("due_date", today)
        .order("due_date", desc=False)
        .execute()
    )
    return _attach_assignees(db, result.data or [])


def get_todo(db: Client, todo_id: str) -> dict | None:
    result = db.table("todos").select("*").eq("id", todo_id).execute()
    rows = _attach_assignees(db, result.data or [])
    return rows[0] if rows else None


def create_todo(db: Client, data: dict, assignees: list[dict]) -> dict:
    result = db.table("todos").insert(_mirror_first_assignee(data, assignees)).execute()
    row = result.data[0] if result.data else {}
    if not row:
        return {}
    _replace_assignees(db, row["id"], assignees)
    return _normalize_assignees({**row, "assignees": assignees})


def update_todo(db: Client, todo_id: str, data: dict, assignees: list[dict] | None = None) -> dict | None:
    result = db.table("todos").update(_mirror_first_assignee(data, assignees)).eq("id", todo_id).execute()
    if not result.data:
        return None
    if assignees is not None:
        _replace_assignees(db, todo_id, assignees)
    row = dict(result.data[0])
    if assignees is not None:
        row["assignees"] = assignees
    return _normalize_assignees(row)


def delete_todo(db: Client, todo_id: str) -> bool:
    result = db.table("todos").delete().eq("id", todo_id).execute()
    return bool(result.data)


def mark_recurrence_spawned(db: Client, todo_id: str) -> None:
    """Record that this row's completion already created the next occurrence."""
    db.table("todos").update({"recurrence_spawned": True}).eq("id", todo_id).execute()
