from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.dependencies import SupabaseDep, CurrentUserDep
from app.repositories import company_flag_repo, contact_repo
from app.schemas.company_flag import CompanyFlagCreate, CompanyFlagOut
from app.schemas.contact import ContactOut

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("/flag", response_model=CompanyFlagOut | None)
def get_company_flag(
    current_user: CurrentUserDep,
    db: SupabaseDep,
    company_name: str = Query(...),
):
    """Return the flag for a company, or null if it isn't flagged.

    Flags are informational warnings (e.g. already has an AI provider, too
    large to service) shown on the call tracker; they never remove contacts
    from the calling pool.
    """
    flag = company_flag_repo.get_flag(db, company_name)
    return CompanyFlagOut(**flag) if flag else None


@router.put("/flag", response_model=CompanyFlagOut)
def set_company_flag(
    body: CompanyFlagCreate,
    current_user: CurrentUserDep,
    db: SupabaseDep,
):
    """Create or replace the flag for a company (one flag per company)."""
    flag = company_flag_repo.upsert_flag(
        db,
        company_name=body.company_name,
        reason=body.reason,
        details=body.details,
        flagged_by=current_user["id"],
        flagged_by_name=current_user.get("full_name"),
    )
    return CompanyFlagOut(**flag)


@router.delete("/flag")
def remove_company_flag(
    current_user: CurrentUserDep,
    db: SupabaseDep,
    company_name: str = Query(...),
):
    """Remove a company's flag."""
    deleted = company_flag_repo.delete_flag(db, company_name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Company is not flagged")
    return {"detail": "Flag removed"}


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
