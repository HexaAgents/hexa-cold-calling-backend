from __future__ import annotations

import logging

from app.scoring.exa_client import fetch_company_info
from app.scoring.openai_scorer import score_company

logger = logging.getLogger(__name__)


def score_website(
    exa_api_key: str,
    openai_api_key: str,
    openai_model: str,
    website: str,
    company_name: str,
    job_title: str = "",
) -> dict:
    """Fetch website content and score a company. Returns scoring dict + exa_scrape_success."""
    website_text, exa_success = fetch_company_info(exa_api_key, website, company_name)

    score_data = score_company(
        api_key=openai_api_key,
        company_name=company_name,
        job_title=job_title,
        website_text=website_text,
        model=openai_model,
    )

    return {
        **score_data,
        "exa_scrape_success": exa_success,
        "scoring_failed": False,
    }
