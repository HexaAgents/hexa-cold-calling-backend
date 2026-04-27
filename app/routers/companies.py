from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.dependencies import SupabaseDep, CurrentUserDep
from app.repositories import contact_repo
from app.schemas.contact import ContactOut

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("")
def list_companies(
    current_user: CurrentUserDep,
    db: SupabaseDep,
    search: str | None = Query(None),
):
    """Return distinct companies with aggregated stats."""
    return contact_repo.get_all_companies(db, search=search)


@router.get("/detail")
def get_company_detail(
    current_user: CurrentUserDep,
    db: SupabaseDep,
    company_name: str = Query(...),
):
    """Return company info and all contacts for a given company name."""
    contacts = contact_repo.get_contacts_by_company(db, company_name)
    if not contacts:
        raise HTTPException(status_code=404, detail="Company not found")

    first = contacts[0]
    company_info = {
        "company_name": company_name,
        "website": None,
        "company_linkedin_url": None,
        "company_description": None,
        "employees": None,
        "industry_tag": None,
        "city": None,
        "state": None,
        "country": None,
    }
    for c in contacts:
        for field in company_info:
            if field == "company_name":
                continue
            if not company_info[field] and c.get(field):
                company_info[field] = c[field]

    return {
        "company": company_info,
        "contacts": [ContactOut(**c).model_dump() for c in contacts],
    }
