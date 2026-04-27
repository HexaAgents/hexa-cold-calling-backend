from __future__ import annotations

import logging

from exa_py import Exa

logger = logging.getLogger(__name__)

MAX_TEXT_LENGTH = 8000
MIN_USEFUL_LENGTH = 100
EXA_REQUEST_TIMEOUT = 30


def fetch_company_info(api_key: str, website: str, company_name: str) -> tuple[str, bool]:
    """Fetch company info via Exa content extraction with search fallback.

    Returns (extracted_text, success_bool).
    """
    if not website and not company_name:
        return ("", False)

    client = Exa(api_key=api_key)
    _apply_timeout(client, EXA_REQUEST_TIMEOUT)
    text = ""

    if website:
        text = _extract_from_url(client, website)

    if len(text) < MIN_USEFUL_LENGTH and company_name:
        fallback = _search_fallback(client, company_name)
        text = (text + "\n\n" + fallback).strip() if text else fallback

    text = text[:MAX_TEXT_LENGTH]
    return (text, len(text) >= MIN_USEFUL_LENGTH)


def _apply_timeout(client: Exa, timeout: int) -> None:
    """Set a default timeout on the Exa client's underlying requests session."""
    session = getattr(client, "request_session", None) or getattr(client, "_session", None)
    if session is not None:
        from requests.adapters import HTTPAdapter

        class _TimeoutAdapter(HTTPAdapter):
            def send(self, request, **kwargs):
                kwargs.setdefault("timeout", timeout)
                return super().send(request, **kwargs)

        session.mount("https://", _TimeoutAdapter())
        session.mount("http://", _TimeoutAdapter())


def _extract_from_url(client: Exa, url: str) -> str:
    text = _get_page(client, url)
    if len(text) >= MIN_USEFUL_LENGTH:
        return text

    about_text = _get_page(client, url.rstrip("/") + "/about")
    if about_text:
        return (text + "\n\n" + about_text).strip() if text else about_text

    return text


def _get_page(client: Exa, url: str) -> str:
    try:
        result = client.get_contents([url], text={"max_characters": 3000})
        if result.results and result.results[0].text:
            return result.results[0].text.strip()
    except Exception as exc:
        logger.warning("Exa content extraction failed for %s: %s", url, exc)
    return ""


def _search_fallback(client: Exa, company_name: str) -> str:
    try:
        # Neutral query: avoid biasing retrieved snippets with "distributor" keywords
        # (would confuse the model for vendors who sell *to* distributors).
        query = f"{company_name} company about products customers"
        result = client.search_and_contents(
            query,
            type="auto",
            category="company",
            num_results=3,
            text={"max_characters": 3000},
        )
        parts = [r.text.strip() for r in result.results if r.text]
        return "\n\n".join(parts)
    except Exception as exc:
        logger.warning("Exa search fallback failed for '%s': %s", company_name, exc)
    return ""
