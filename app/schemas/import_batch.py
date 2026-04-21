from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class ImportBatchOut(BaseModel):
    id: str
    user_id: str
    filename: str
    total_rows: int
    processed_rows: int
    stored_rows: int
    discarded_rows: int
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
