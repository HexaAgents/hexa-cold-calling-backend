# Scoring — AI-Powered Lead Qualification

This module handles all AI-powered company scoring. When contacts are imported via CSV, the scoring pipeline runs for each unique website to determine whether the company is an industrial distributor and assigns a score from 0-100.

The pipeline has three stages:

1. **Content extraction** (`exa_client.py`) — Fetch the company's website text via the Exa API.
2. **Prompt assembly** (`prompts.py`) — Build the system prompt (classification rules + scoring rubric) and user message (company name + job title + website text).
3. **LLM scoring** (`openai_scorer.py`) — Send the assembled messages to GPT-4o-mini in JSON mode, parse and validate the structured response.

---

## Files

| File | Purpose |
|---|---|
| `prompts.py` | System prompt (classification rules, scoring rubric) and user message template |
| `exa_client.py` | Website content extraction via Exa API with search fallback |
| `openai_scorer.py` | OpenAI GPT call, retry logic, response parsing and validation |

---

## prompts.py

### `SYSTEM_PROMPT` (lines 1-48)

A single multi-line string that defines the LLM's entire scoring persona and rules. This is the most business-critical piece of text in the application — changing a single sentence here changes how every lead is scored.

**Lines 2-3 — Identity:** Establishes the LLM as a "B2B lead qualification assistant for Hexa" and describes what Hexa does (AI automation for industrial distributors — procurement, quoting, order entry, AP/AR, invoice matching, vendor management, customer service with ERP integration).

**Lines 6-9 — ACCEPT rules:** A single category of companies that are potential customers:
- **Industrial distributors** — companies whose primary business is distributing, supplying, or reselling physical industrial products. The prompt lists a comprehensive but non-exhaustive set of product categories (electrical supplies, PVF, HVAC, MRO, safety/PPE, fasteners, bearings, power transmission, cutting tools, fluid power, janitorial, welding, adhesives, industrial gases, building materials, packaging, material handling, pumps, motors, filtration, lab supplies).

**Lines 11-24 — REJECT rules with labels:**
- `"manufacturer"` — companies whose primary business is manufacturing, producing, or assembling physical products. Even if they also distribute, if manufacturing is their core identity, they are rejected.
- `"wholesaler"` — pure wholesalers of non-industrial goods (food, consumer, fashion, agricultural). Companies that distribute industrial products are classified as distributors even if they call themselves wholesalers.
- `"service_provider"` — consulting, staffing, marketing, law, accounting, IT services, managed services, engineering services, logistics-only (3PLs without inventory), cleaning, construction contractors, repair/maintenance, installation contractors.
- `"consultancy"` — management consultancies, strategy firms, advisory firms.
- `"automation_company"` — pure software, SaaS, or consulting for automation (ERP vendors, MES, supply chain SaaS, AI/ML tools). These are competitors, not customers.
- `"unclear"` — insufficient website text to determine the company's business.

**Lines 26-38 — Scoring rubric (0-100):**

| Tier | Score Range | Criteria |
|---|---|---|
| Top tier | 90-100 | Clearly an industrial distributor. Contact has an operational/leadership title (VP Ops, COO, CFO, Supply Chain Director, IT Director, GM, Owner, President, Purchasing Manager, Operations Manager, Branch Manager). |
| Strong fit | 70-89 | Clearly an industrial distributor, but the contact's title is less directly relevant (sales manager, marketing director, project manager, engineer, account manager). |
| Possible fit | 50-69 | Likely an industrial distributor but the website is ambiguous — the company may do distribution AND other activities. |
| Human review | 30-49 | Some distributor signals but significant uncertainty. Assigned in this range for human review. |
| Not a fit | 0-29 | Not an industrial distributor, manufacturer, service provider, software company, or unrelated industry. |

**Lines 40-46 — Output format:** Instructs the LLM to respond with valid JSON only, in the exact format: `score` (int 0-100), `company_type` (distributor|rejected), `rationale` (1-2 sentence explanation), `rejection_reason` (null or one of the six rejection labels), `company_description` (2-sentence sales briefing).

### `USER_MESSAGE_TEMPLATE` (lines 50-55)

```python
USER_MESSAGE_TEMPLATE = """\
Company Name: {company_name}
Contact Job Title: {job_title}

Company Website Content:
{website_text}"""
```

A Python `.format()` template with three placeholders. Filled in by `openai_scorer.score_company()` at call time. The job title is included because it influences the score within a tier — a VP of Operations at a manufacturer scores higher than a Marketing Director at the same manufacturer.

---

## exa_client.py

### Constants (lines 9-10)

```python
MAX_TEXT_LENGTH = 8000
MIN_USEFUL_LENGTH = 100
```

- `MAX_TEXT_LENGTH = 8000` — Website text is truncated to 8000 characters before being sent to OpenAI. This keeps the prompt well within GPT-4o-mini's context window while controlling token costs. 8000 characters is roughly 2000-2500 tokens, leaving ample room for the system prompt and response.
- `MIN_USEFUL_LENGTH = 100` — If the total extracted text is shorter than 100 characters, it's considered too sparse to score meaningfully. The function will report `success=False`, and the scoring pipeline will still attempt to score but the LLM will likely classify the company as `"unclear"`.

### `fetch_company_info()` (lines 13-32)

```python
def fetch_company_info(api_key: str, website: str, company_name: str) -> tuple[str, bool]:
```

The main entry point. Takes an Exa API key, a website URL, and a company name. Returns a tuple of `(extracted_text, success_bool)`.

**Line 18-19 — Early exit:** If both `website` and `company_name` are empty, there is nothing to look up. Returns `("", False)` immediately.

**Line 21 — Client creation:** Instantiates a new `Exa` client with the provided API key. A fresh client is created per call rather than reused globally because scoring runs are infrequent (batch imports, not high-frequency requests).

**Line 24-25 — Stage 1 (direct URL extraction):** If a `website` URL is available, `_extract_from_url()` attempts to fetch the content directly. This is the preferred path — it's faster and more accurate than searching.

**Lines 27-29 — Stage 2 (search fallback):** If the extracted text is shorter than `MIN_USEFUL_LENGTH` (100 chars) and a `company_name` is available, the function falls back to `_search_fallback()`. This handles cases where the direct URL extraction fails (dead links, JavaScript-heavy sites, CDN-blocked scraping). If Stage 1 returned some text but not enough, the fallback text is appended rather than replacing it.

**Line 31 — Truncation:** The combined text is truncated to `MAX_TEXT_LENGTH` (8000 chars). This is a hard cap — no matter how much content was extracted, only the first 8000 characters are sent to the LLM.

**Line 32 — Success determination:** Success is `True` only if the final text is at least `MIN_USEFUL_LENGTH` characters. This boolean is stored on the contact as `exa_scrape_success` and used in the frontend to indicate whether the score is based on real website data or sparse/missing content.

### `_extract_from_url()` (lines 35-48)

```python
def _extract_from_url(client: Exa, url: str) -> str:
```

Attempts to extract content from up to **three pages** of the website:

1. **Main page** (line 38) — `_get_page(client, url)` fetches the root URL.
2. **About page** (lines 42-45) — Tries `url/about` first, then `url/about-us` as a fallback. The `.rstrip("/")` prevents double slashes (`example.com//about`). About pages are particularly valuable because they typically contain the company description, history, and industry focus — exactly the information the scoring rubric needs.

The results from all successful pages are joined with double newlines and returned as a single string.

### `_get_page()` (lines 51-58)

```python
def _get_page(client: Exa, url: str) -> str:
```

Low-level function that fetches a single URL via Exa's `get_contents()` API.

**Line 53 — Content extraction:** `client.get_contents([url], text={"max_characters": 3000})` asks Exa to extract the text content from the page, capped at 3000 characters per page. This limit is per-page, not per-call — since `_extract_from_url` may fetch up to 3 pages, the combined result can be up to 9000 characters before the final `MAX_TEXT_LENGTH` truncation.

**Lines 54-55 — Result handling:** Exa returns results as a list (since it accepts a list of URLs). The function checks that results exist and that the first result has non-empty text, then returns the stripped text.

**Lines 56-57 — Error handling:** Any exception from the Exa API is caught, logged as a warning, and returns an empty string. This is intentionally non-fatal — a failed page extraction doesn't abort the entire scoring pipeline; the search fallback may still succeed.

### `_search_fallback()` (lines 61-75)

```python
def _search_fallback(client: Exa, company_name: str) -> str:
```

When direct URL extraction fails or yields too little text, this function searches Exa's web index for the company.

**Line 63 — Query construction:** The query is `"{company_name} industrial distributor supplier"`. The keywords are appended to bias results toward pages that describe the company's industrial distribution operations, which is exactly what the scoring rubric needs.

**Lines 64-69 — Search call:** `search_and_contents()` combines search and content extraction in one API call. Parameters:
- `type="auto"` — lets Exa choose the best search strategy.
- `category="company"` — restricts results to company-related pages.
- `num_results=3` — returns the top 3 results. More would increase cost; fewer might miss important context.
- `text={"max_characters": 3000}` — extracts up to 3000 characters per result.

**Lines 71-72 — Result assembly:** The text from all returned results is joined with double newlines into a single string.

**Lines 73-74 — Error handling:** Same pattern as `_get_page()` — catch all exceptions, log, return empty string.

---

## openai_scorer.py

### Constants (lines 13-21)

```python
DEFAULT_ERROR_RESULT: dict = {
    "score": 0,
    "company_type": "rejected",
    "rationale": "OpenAI API error",
    "rejection_reason": "unclear",
}

VALID_COMPANY_TYPES = {"distributor", "rejected"}
VALID_REJECTION_REASONS = {"manufacturer", "wholesaler", "service_provider", "consultancy", "automation_company", "unclear", None}
```

- `DEFAULT_ERROR_RESULT` — The fallback result returned when the OpenAI API fails after both retry attempts. Scores the company as 0/rejected/unclear so it doesn't appear as a qualified lead in the frontend. The rationale `"OpenAI API error"` makes it clear to human reviewers that this is a system failure, not a genuine rejection.
- `VALID_COMPANY_TYPES` — Allowlist of `company_type` values the LLM may return (`"distributor"` or `"rejected"`). Anything outside this set is corrected to `"rejected"`.
- `VALID_REJECTION_REASONS` — Allowlist of `rejection_reason` values (`"manufacturer"`, `"wholesaler"`, `"service_provider"`, `"consultancy"`, `"automation_company"`, `"unclear"`, or `None`). Includes `None` because accepted companies should have a null rejection reason. Anything outside this set is corrected to `"unclear"`.

### `score_company()` (lines 24-47)

```python
def score_company(
    api_key: str,
    company_name: str,
    job_title: str,
    website_text: str,
    model: str = "gpt-4o-mini",
) -> dict:
```

The main entry point for scoring. Takes raw inputs and returns a validated scoring dict.

**Lines 32-36 — User message assembly:** Fills the `USER_MESSAGE_TEMPLATE` with the company name, job title, and website text. Any `None` values are replaced with `"Unknown"` or a fallback string so the template never contains the literal text `"None"`.

**Lines 38-41 — Messages list:** Builds the standard OpenAI messages array with one system message (the full scoring rubric) and one user message (the company data).

**Lines 43-44 — API call:** Delegates to `_call_openai()`, which handles the actual HTTP request and retry logic. If it returns `None` (both attempts failed), the function returns a copy of `DEFAULT_ERROR_RESULT`. A copy is returned (via `dict(...)`) to prevent callers from accidentally mutating the shared default.

**Line 47 — Parse:** Passes the raw JSON string to `_parse_response()` for validation and normalization.

### `_call_openai()` (lines 50-69)

```python
def _call_openai(api_key: str, model: str, messages: list[dict]) -> str | None:
```

Handles the OpenAI API call with **one retry after a 5-second delay** (2 total attempts).

**Line 51 — Client creation:** Creates a new `OpenAI` client with the provided API key. Like the Exa client, a fresh instance per call keeps the module stateless.

**Line 53 — Retry loop:** `for attempt in range(2)` gives two iterations — attempt 0 (first try) and attempt 1 (retry).

**Lines 55-60 — API call:**
- `model=model` — defaults to `"gpt-4o-mini"`, the cheapest model in the GPT-4o family. Sufficient for structured classification tasks.
- `response_format={"type": "json_object"}` — enables JSON mode, which guarantees the response is valid JSON. Without this, the LLM might include markdown code fences or explanatory text around the JSON.
- `temperature=0.2` — low temperature for consistent, deterministic scoring. A higher temperature would introduce variance between scoring runs for the same input.

**Line 61 — Extract content:** Returns the text content of the first choice. In JSON mode, this is a raw JSON string.

**Lines 62-68 — Error handling:** On the first failure, logs a warning and sleeps 5 seconds before retrying. This handles transient issues like rate limits or brief API outages. On the second failure, logs an error and returns `None`, which causes the caller to use `DEFAULT_ERROR_RESULT`.

### `_parse_response()` (lines 72-99)

```python
def _parse_response(raw: str) -> dict:
```

Parses and validates the raw JSON string from the LLM. This function is **defensive by design** — it assumes the LLM might return malformed or out-of-spec data and corrects every field individually rather than rejecting the entire response.

**Lines 73-76 — JSON parse:** Attempts `json.loads(raw)`. If the JSON is invalid (should be rare with JSON mode enabled, but possible), returns the default error result with a `"Scoring parse error"` rationale.

**Lines 78-84 — Score validation:**
- Extracts `score` from the parsed dict, defaulting to `0`.
- If it's not an integer (e.g. the LLM returned a float or a string), attempts to cast it with `int()`. If that fails (e.g. `"high"`), falls back to `0`.
- Clamps the value to the 0-100 range with `max(0, min(100, score))`. This prevents out-of-bounds scores like `-5` or `150` that would break frontend display logic.

**Lines 86-88 — Company type validation:** Extracts `company_type`, defaulting to `"rejected"`. If the value is not in `VALID_COMPANY_TYPES` (e.g. the LLM returned `"manufacturer"` or `"wholesaler"`), it is corrected to `"rejected"`. This is a conservative default — an unknown type is treated as a rejection rather than a false acceptance.

**Lines 90-92 — Rejection reason validation:** Extracts `rejection_reason`. If the value is not in `VALID_REJECTION_REASONS` (which includes `None`), it is corrected to `"unclear"`.

**Lines 94-99 — Return normalized result:** Assembles and returns the validated dict. The `rationale` is cast to `str()` as a safety measure in case the LLM returned a non-string value. The `rejection_reason` passes through as-is (it may be `None` for accepted companies).

---

## End-to-End Scoring Flow

1. **CSV import triggers scoring** — The import service extracts unique websites from the uploaded CSV and calls `contact_repo.get_existing_scores()` to check for already-scored websites. Only cached scores where `company_type == "distributor"` are trusted; all other cached types force a re-score under the current prompt.
2. **Content extraction** — For each unscored website, `exa_client.fetch_company_info()` fetches website text (direct URL → about pages → search fallback). Text is truncated to 8000 characters.
3. **LLM scoring** — `openai_scorer.score_company()` sends the system prompt + company data to GPT-4o-mini in JSON mode with temperature 0.2.
4. **Response validation** — `_parse_response()` validates every field: clamps score to 0-100, checks company_type against `{"distributor", "rejected"}` and rejection_reason against the allowlist, casts rationale to string.
5. **Storage** — The validated scoring result (`score`, `company_type`, `rationale`, `rejection_reason`, `exa_scrape_success`) is written to the contact row via `contact_repo.create_contacts_batch()`.
6. **Phone enrichment** — Contacts scoring >= 50 (confirmed distributors) that lack a mobile phone are automatically queued for Apollo enrichment (`enrichment_status = "pending_enrichment"`).
