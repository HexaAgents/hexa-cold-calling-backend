from __future__ import annotations

from unittest.mock import patch


def test_score_website_success():
    with (
        patch("app.services.scoring_service.fetch_company_info") as mock_exa,
        patch("app.services.scoring_service.score_company") as mock_openai,
    ):
        mock_exa.return_value = ("ACME manufactures industrial valves...", True)
        mock_openai.return_value = {
            "score": 85,
            "company_type": "manufacturer",
            "rationale": "ACME is a manufacturer of industrial valves.",
            "rejection_reason": None,
        }

        from app.services.scoring_service import score_website

        result = score_website(
            exa_api_key="fake",
            openai_api_key="fake",
            openai_model="gpt-4o-mini",
            website="https://acme.com",
            company_name="ACME Corp",
            job_title="CEO",
        )

        assert result["score"] == 85
        assert result["company_type"] == "manufacturer"
        assert result["exa_scrape_success"] is True
        assert result["scoring_failed"] is False


def test_score_website_exa_failure():
    with (
        patch("app.services.scoring_service.fetch_company_info") as mock_exa,
        patch("app.services.scoring_service.score_company") as mock_openai,
    ):
        mock_exa.return_value = ("", False)
        mock_openai.return_value = {
            "score": 0,
            "company_type": "rejected",
            "rationale": "No website content available.",
            "rejection_reason": "unclear",
        }

        from app.services.scoring_service import score_website

        result = score_website(
            exa_api_key="fake",
            openai_api_key="fake",
            openai_model="gpt-4o-mini",
            website="https://broken.com",
            company_name="Broken Inc",
        )

        assert result["score"] == 0
        assert result["exa_scrape_success"] is False
