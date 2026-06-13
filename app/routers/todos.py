from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.dependencies import SupabaseDep, CurrentUserDep
from app.schemas.todo import (
    TodoCreate,
    TodoUpdate,
    TodoOut,
    TodoAssignee,
    DueDateEstimateRequest,
    DueDateEstimateResponse,
)
from app.repositories import todo_repo, email_repo, user_repo
from app.scoring import due_date_estimator
from app.services import email_service, todo_recurrence_service

router = APIRouter(prefix="/todos", tags=["todos"])
logger = logging.getLogger(__name__)

# Ishaan can tick off any task, regardless of who created it.
SUPER_USER_EMAIL = "ishaan@hexaagents.com"


def _is_super_user(current_user: dict) -> bool:
    return (current_user.get("email") or "").lower() == SUPER_USER_EMAIL


_first_name = user_repo.first_name


def _assignee_payload(assignees: list[TodoAssignee] | None, assigned_to_id: str | None, assigned_to_name: str | None) -> list[dict]:
    if assignees is not None:
        people = assignees
    elif assigned_to_id:
        people = [TodoAssignee(id=assigned_to_id, first_name=assigned_to_name or "Unknown")]
    else:
        people = []

    deduped: dict[str, dict] = {}
    for person in people:
        deduped[str(person.id)] = {"id": str(person.id), "first_name": person.first_name}
    return list(deduped.values())


def _notify_new_assignees(
    db: SupabaseDep,
    actor: dict,
    todo: dict,
    previous_assignee_ids: set[str],
) -> None:
    """Best-effort email notification for assignees newly added to a task.

    Everyone newly added is notified, including the assigner if they assign
    themselves. Pre-existing assignees are not re-notified on edits.
    """
    new_assignees = [
        a for a in todo.get("assignees", [])
        if str(a["id"]) not in previous_assignee_ids
    ]
    if not new_assignees:
        return

    try:
        directory = user_repo.get_auth_user_directory(db)
    except Exception as exc:
        logger.warning("Could not load users for todo assignment notifications: %s", exc)
        return

    sender_tokens = email_repo.get_gmail_tokens_by_address(db, settings.notification_sender_email)
    if not sender_tokens:
        logger.warning(
            "Notification sender %s not connected; skipping todo assignment emails",
            settings.notification_sender_email,
        )
        return
    sender_user_id = sender_tokens["user_id"]

    task_url = f"{settings.frontend_url.rstrip('/')}/todo-list/{todo['id']}"
    actor_name = _first_name(actor.get("full_name"), actor.get("email", "Someone"))
    due = todo.get("due_date") or "No due date"
    description = todo.get("description") or "No description provided."
    subject = f"New task assigned: {todo['title']}"
    body = (
        f"Hi,\n\n"
        f"{actor_name} assigned you a task in Hexa:\n\n"
        f"{todo['title']}\n\n"
        f"Due: {due}\n\n"
        f"Description:\n{description}\n\n"
        f"Open the task: {task_url}\n"
    )

    for assignee in new_assignees:
        recipient = directory.get(str(assignee["id"]), {}).get("email")
        if not recipient:
            logger.warning("Skipping todo assignment email for %s: no email address", assignee["id"])
            continue
        try:
            email_service.send_direct_email(db, sender_user_id, recipient, subject, body)
        except Exception as exc:
            logger.warning("Todo assignment email failed for %s: %s", recipient, exc)


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


@router.post("/estimate-due-date", response_model=DueDateEstimateResponse)
def estimate_due_date(body: DueDateEstimateRequest, current_user: CurrentUserDep):
    """Recommend a due date for the task being typed in the create dialog.

    Synchronous and stateless: one bounded OpenAI call, nothing persisted.
    """
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="Due date estimation is not configured")

    due_date = due_date_estimator.estimate_due_date(
        settings.openai_api_key,
        body.title,
        body.description,
        model=settings.openai_model,
    )
    if not due_date:
        raise HTTPException(status_code=502, detail="Could not estimate a due date")
    return DueDateEstimateResponse(due_date=due_date)


@router.get("/{todo_id}", response_model=TodoOut)
def get_todo(todo_id: str, current_user: CurrentUserDep, db: SupabaseDep):
    todo = todo_repo.get_todo(db, todo_id)
    if not todo:
        raise HTTPException(status_code=404, detail="Task not found")
    return TodoOut(**todo)


@router.post("", response_model=TodoOut, status_code=201)
def create_todo(
    body: TodoCreate,
    current_user: CurrentUserDep,
    db: SupabaseDep,
):
    assignees = _assignee_payload(body.assignees, body.assigned_to_id, body.assigned_to_name)
    data = {
        "title": body.title,
        "description": body.description,
        "assigned_by_id": current_user["id"],
        "assigned_by_name": _first_name(current_user.get("full_name"), current_user.get("email", "")),
        "due_date": body.due_date,
        "recurrence_interval": body.recurrence_interval,
        "recurrence_unit": body.recurrence_unit,
    }
    todo = todo_repo.create_todo(db, data, assignees)
    _notify_new_assignees(db, current_user, todo, set())
    return TodoOut(**todo)


@router.patch("/{todo_id}", response_model=TodoOut)
def update_todo(todo_id: str, body: TodoUpdate, current_user: CurrentUserDep, db: SupabaseDep):
    existing = todo_repo.get_todo(db, todo_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Task not found")
    previous_assignee_ids = {str(a["id"]) for a in existing.get("assignees", [])}

    uid = str(current_user["id"])
    is_assigner = str(existing.get("assigned_by_id")) == uid
    is_assignee = any(str(a["id"]) == uid for a in existing.get("assignees", []))
    is_super = _is_super_user(current_user)

    provided = body.model_dump(exclude_unset=True)
    assignees_provided = "assignees" in provided or "assigned_to_id" in provided or "assigned_to_name" in provided
    assignees = None
    if assignees_provided:
        assignees = _assignee_payload(body.assignees, body.assigned_to_id, body.assigned_to_name)
    provided.pop("assignees", None)
    provided.pop("assigned_to_id", None)
    provided.pop("assigned_to_name", None)
    provided.pop("unassign", None)
    if body.unassign:
        assignees_provided = True
        assignees = []

    if not is_assigner and not is_assignee and not is_super:
        raise HTTPException(status_code=403, detail="Only the person who assigned or is assigned this task can change it")

    # Ticking a task off (or unticking it) is reserved for the task's creator;
    # the super user can complete anyone's task.
    if "is_done" in provided and not is_assigner and not is_super:
        raise HTTPException(status_code=403, detail="Only the person who set this task can mark it done")

    if not provided and not assignees_provided:
        return TodoOut(**existing)

    updated = todo_repo.update_todo(db, todo_id, provided, assignees)
    if not updated:
        raise HTTPException(status_code=404, detail="Task not found")
    if assignees_provided:
        _notify_new_assignees(db, current_user, updated, previous_assignee_ids)

    # Completing a recurring task spawns its next occurrence. Best-effort: a
    # failure here must not undo or hide the successful completion above.
    if provided.get("is_done") is True and not existing.get("is_done"):
        # update_todo only knows the legacy first assignee unless assignees were
        # part of this PATCH; use the fully-loaded existing row's list instead.
        source = dict(updated)
        if not assignees_provided:
            source["assignees"] = existing.get("assignees", [])
        try:
            todo_recurrence_service.spawn_next_occurrence(db, source)
        except Exception as exc:
            logger.warning("Could not create next occurrence for todo %s: %s", todo_id, exc)

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
