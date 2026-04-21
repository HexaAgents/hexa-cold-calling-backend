from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, BackgroundTasks

from app.dependencies import SupabaseDep, CurrentUserDep, get_supabase
from app.schemas.import_batch import ImportBatchOut
from app.services import import_service
from app.repositories import import_batch_repo

router = APIRouter(prefix="/imports", tags=["imports"])


def _run_import(file_content: bytes, filename: str, user_id: str) -> None:
    """Background task to process the CSV import."""
    db = get_supabase()
    try:
        import_service.process_csv_upload(db, file_content, filename, user_id)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Import failed for %s: %s", filename, exc)


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

    background_tasks.add_task(_run_import, content, file.filename, current_user["id"])

    return {"status": "processing", "filename": file.filename}


@router.get("/{batch_id}/status", response_model=ImportBatchOut)
def get_import_status(batch_id: str, current_user: CurrentUserDep, db: SupabaseDep):
    batch = import_batch_repo.get_batch(db, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Import batch not found")
    return ImportBatchOut(**batch)


@router.get("/recent", response_model=list[ImportBatchOut])
def get_recent_imports(current_user: CurrentUserDep, db: SupabaseDep):
    batches = import_batch_repo.get_recent_batches(db)
    return [ImportBatchOut(**b) for b in batches]
