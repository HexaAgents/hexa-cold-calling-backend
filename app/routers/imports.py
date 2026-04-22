from __future__ import annotations

import csv
import io

from fastapi import APIRouter, HTTPException, UploadFile, BackgroundTasks

from app.dependencies import SupabaseDep, CurrentUserDep, get_supabase
from app.schemas.import_batch import ImportBatchOut
from app.services import import_service
from app.repositories import contact_repo, import_batch_repo

router = APIRouter(prefix="/imports", tags=["imports"])


def _run_import(batch_id: str, file_content: bytes, filename: str, user_id: str) -> None:
    """Background task to process the CSV import."""
    db = get_supabase()
    try:
        import_service.process_csv_upload(db, file_content, filename, user_id, batch_id)
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error("Import failed for %s: %s", filename, exc)
        try:
            import_batch_repo.update_batch(db, batch_id, {"status": "failed"})
        except Exception:
            logger.error("Failed to mark batch %s as failed", batch_id)


def _count_csv_rows(content: bytes) -> int:
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    return sum(1 for row in reader if (row.get("Company Name") or "").strip())


@router.post("/upload")
async def upload_csv(
    file: UploadFile,
    current_user: CurrentUserDep,
    db: SupabaseDep,
    background_tasks: BackgroundTasks,
):
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a CSV")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="File is empty")

    total_rows = _count_csv_rows(content)

    batch = import_batch_repo.create_batch(db, {
        "user_id": current_user["id"],
        "filename": file.filename,
        "total_rows": total_rows,
        "status": "processing",
    })

    background_tasks.add_task(_run_import, batch["id"], content, file.filename, current_user["id"])

    return {"batch_id": batch["id"], "total_rows": total_rows, "status": "processing"}


@router.get("/{batch_id}/status", response_model=ImportBatchOut)
def get_import_status(batch_id: str, current_user: CurrentUserDep, db: SupabaseDep):
    batch = import_batch_repo.get_batch(db, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Import batch not found")
    if import_batch_repo.is_stale(batch):
        import_batch_repo.update_batch(db, batch_id, {"status": "failed"})
        batch["status"] = "failed"
    return ImportBatchOut(**batch)


@router.get("/recent", response_model=list[ImportBatchOut])
def get_recent_imports(current_user: CurrentUserDep, db: SupabaseDep):
    batches = import_batch_repo.get_recent_batches(db)
    return [ImportBatchOut(**b) for b in batches]


@router.delete("/{batch_id}")
def delete_import_batch(batch_id: str, current_user: CurrentUserDep, db: SupabaseDep):
    """Delete a failed/completed batch and all its contacts."""
    batch = import_batch_repo.get_batch(db, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Import batch not found")
    if batch["status"] == "processing":
        raise HTTPException(status_code=409, detail="Cannot delete a batch that is still processing")

    deleted_count = contact_repo.delete_contacts_by_batch(db, batch_id)
    import_batch_repo.delete_batch(db, batch_id)
    return {"deleted_contacts": deleted_count, "batch_id": batch_id}
