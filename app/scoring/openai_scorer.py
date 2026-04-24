from __future__ import annotations

import json
import logging
import time

from openai import OpenAI

from app.scoring.prompts import SYSTEM_PROMPT, USER_MESSAGE_TEMPLATE

logger = logging.getLogger(__name__)

DEFAULT_ERROR_RESULT: dict = {
    "score": 0,
    "company_type": "rejected",
    "rationale": "OpenAI API error",
    "rejection_reason": "unclear",
}

VALID_COMPANY_TYPES = {"distributor", "rejected"}
VALID_REJECTION_REASONS = {
    "non_industrial_distributor", "manufacturer", "manufacturers_rep",
    "fuel_distributor", "wholesaler", "service_provider", "consultancy",
    "automation_company", "data_mismatch", "unclear", None,
}


def score_company(
    api_key: str,
    company_name: str,
    job_title: str,
    website_text: str,
    model: str = "gpt-4o-mini",
) -> dict:
    """Score a company using OpenAI GPT with JSON mode."""
    user_message = USER_MESSAGE_TEMPLATE.format(
        company_name=company_name or "Unknown",
        job_title=job_title or "Unknown",
        website_text=website_text or "(No website content available)",
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    raw = _call_openai(api_key, model, messages)
    if raw is None:
        return dict(DEFAULT_ERROR_RESULT)

    return _parse_response(raw)


def _call_openai(api_key: str, model: str, messages: list[dict]) -> str | None:
    client = OpenAI(api_key=api_key, timeout=30.0)

    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            return response.choices[0].message.content
        except Exception as exc:
            if attempt == 0:
                logger.warning("OpenAI call failed (attempt 1), retrying in 2s: %s", exc)
                time.sleep(2)
            else:
                logger.error("OpenAI call failed (attempt 2), giving up: %s", exc)

    return None


def _parse_response(raw: str) -> dict:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {**DEFAULT_ERROR_RESULT, "rationale": "Scoring parse error"}

    score = data.get("score", 0)
    if not isinstance(score, int):
        try:
            score = int(score)
        except (ValueError, TypeError):
            score = 0
    score = max(0, min(100, score))

    company_type = data.get("company_type", "rejected")
    if company_type not in VALID_COMPANY_TYPES:
        company_type = "rejected"

    rejection_reason = data.get("rejection_reason")
    if rejection_reason not in VALID_REJECTION_REASONS:
        rejection_reason = "unclear"

    return {
        "score": score,
        "company_type": company_type,
        "rationale": str(data.get("rationale", "")),
        "rejection_reason": rejection_reason,
        "company_description": str(data.get("company_description", "")) or None,
        "industry_tag": str(data.get("industry_tag", "")) or None,
    }
