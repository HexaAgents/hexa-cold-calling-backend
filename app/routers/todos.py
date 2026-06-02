from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import SupabaseDep, CurrentUserDep
from app.schemas.todo import TodoCreate, TodoUpdate, TodoOut, TodoAssignee
from app.repositories import todo_repo

router = APIRouter(prefix="/todos", tags=["todos"])


def _first_name(full_name: str | None, fallback: str = "") -> str:
    if not full_name:
        return fallback
    return full_name.split(" ")[0]


@router.get("", response_model=list[TodoOut])
def list_todos(current_user: CurrentUserDep, db: SupabaseDep):
    todos = todo_repo.get_todos(db)
    return [TodoOut(**t) for t in todos]


@router.get("/assignees", response_model=list[TodoAssignee])
def list_assignees(current_user: CurrentUserDep, db: SupabaseDep):
    """Platform users (first names) available to be assigned a task."""
    users_result = db.rpc("get_auth_users").execute()
    assignees: list[TodoAssignee] = []
    for u in users_result.data or []:
        uid = str(u["id"])
        meta = u.get("raw_user_meta_data") or {}
        full_name = meta.get("full_name", u.get("email") or "Unknown")
        assignees.append(TodoAssignee(id=uid, first_name=_first_name(full_name, "Unknown")))
    return assignees


@router.get("/{todo_id}", response_model=TodoOut)
def get_todo(todo_id: str, current_user: CurrentUserDep, db: SupabaseDep):
    todo = todo_repo.get_todo(db, todo_id)
    if not todo:
        raise HTTPException(status_code=404, detail="Task not found")
    return TodoOut(**todo)


@router.post("", response_model=TodoOut, status_code=201)
def create_todo(body: TodoCreate, current_user: CurrentUserDep, db: SupabaseDep):
    data = {
        "title": body.title,
        "description": body.description,
        "assigned_to_id": body.assigned_to_id,
        "assigned_to_name": body.assigned_to_name,
        "assigned_by_id": current_user["id"],
        "assigned_by_name": _first_name(current_user.get("full_name"), current_user.get("email", "")),
        "due_date": body.due_date,
    }
    todo = todo_repo.create_todo(db, data)
    return TodoOut(**todo)


@router.patch("/{todo_id}", response_model=TodoOut)
def update_todo(todo_id: str, body: TodoUpdate, current_user: CurrentUserDep, db: SupabaseDep):
    existing = todo_repo.get_todo(db, todo_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Task not found")

    uid = str(current_user["id"])
    is_assigner = str(existing.get("assigned_by_id")) == uid
    is_assignee = existing.get("assigned_to_id") is not None and str(existing.get("assigned_to_id")) == uid

    provided = body.model_dump(exclude_unset=True)
    provided.pop("unassign", None)
    if body.unassign:
        provided["assigned_to_id"] = None
        provided["assigned_to_name"] = None

    # The assigner can edit anything. The assignee can only flip their own
    # task's done state — not retitle, reassign, or change the due date.
    if not is_assigner:
        if not is_assignee:
            raise HTTPException(status_code=403, detail="Only the person who assigned or is assigned this task can change it")
        if body.unassign or set(provided.keys()) - {"is_done"}:
            raise HTTPException(status_code=403, detail="You can only mark this task as done or not done")

    if not provided:
        return TodoOut(**existing)

    updated = todo_repo.update_todo(db, todo_id, provided)
    if not updated:
        raise HTTPException(status_code=404, detail="Task not found")
    return TodoOut(**updated)


@router.delete("/{todo_id}")
def delete_todo(todo_id: str, current_user: CurrentUserDep, db: SupabaseDep):
    existing = todo_repo.get_todo(db, todo_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Task not found")
    if str(existing.get("assigned_by_id")) != str(current_user["id"]):
        raise HTTPException(status_code=403, detail="Only the person who assigned this task can delete it")
    todo_repo.delete_todo(db, todo_id)
    return {"detail": "Task deleted"}
