from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.import_service import _map_row, COLUMN_MAP


# ---------------------------------------------------------------------------
# _map_row tests
# ---------------------------------------------------------------------------

ALL_APOLLO_HEADERS = [
    "First Name",
    "Last Name",
    "Title",
    "Company Name",
    "Person Linkedin Url",
    "Website",
    "Company Linkedin Url",
    "# Employees",
    "City",
    "Country",
    "Email",
    "Phone",
    "Mobile Phone",
    "Work Direct Phone",
    "Corporate Phone",
]


def _make_row(headers, values=None):
    if values is None:
        values = [f"val_{i}" for i in range(len(headers))]
    return dict(zip(headers, values))


class TestMapRow:
    def test_map_row_all_columns(self):
        row = _make_row(ALL_APOLLO_HEADERS, [
            "Alice", "Smith", "CEO", "ACME Corp",
            "https://linkedin.com/in/alice", "https://acme.com",
            "https://linkedin.com/company/acme", "50",
            "Berlin", "Germany", "alice@acme.com",
            "+491234", "+495678", "+499999", "+490000",
        ])
        result = _map_row(row, ALL_APOLLO_HEADERS)

        assert result["first_name"] == "Alice"
        assert result["last_name"] == "Smith"
        assert result["title"] == "CEO"
        assert result["company_name"] == "ACME Corp"
        assert result["person_linkedin_url"] == "https://linkedin.com/in/alice"
        assert result["website"] == "https://acme.com"
        assert result["company_linkedin_url"] == "https://linkedin.com/company/acme"
        assert result["employees"] == "50"
        assert result["city"] == "Berlin"
        assert result["country"] == "Germany"
        assert result["email"] == "alice@acme.com"
        assert result["mobile_phone"] == "+491234"
        assert result["work_direct_phone"] == "+499999"
        assert result["corporate_phone"] == "+490000"

    def test_map_row_unknown_columns_discarded(self):
        headers = ["Company Name", "Random Column"]
        row = {"Company Name": "ACME", "Random Column": "junk"}
        result = _map_row(row, headers)

        assert "Random Column" not in result
        assert "random_column" not in result
        assert result == {"company_name": "ACME"}

    def test_map_row_duplicate_phone_first_wins(self):
        headers = ["Phone", "Mobile Phone"]
        row = {"Phone": "+111", "Mobile Phone": "+222"}
        result = _map_row(row, headers)
        assert result["mobile_phone"] == "+111"

    def test_map_row_empty_values_skipped(self):
        row = {h: "" for h in ALL_APOLLO_HEADERS}
        result = _map_row(row, ALL_APOLLO_HEADERS)
        assert result == {}


# ---------------------------------------------------------------------------
# process_csv_upload tests
# ---------------------------------------------------------------------------

def _csv_bytes(*data_rows, headers="Company Name,Website"):
    lines = [headers] + list(data_rows)
    return ("\n".join(lines)).encode()


@pytest.fixture
def _mock_deps():
    with (
        patch("app.services.import_service.score_website") as mock_score,
        patch("app.repositories.contact_repo.get_existing_scores", return_value={}) as mock_existing,
        patch("app.repositories.contact_repo.create_contacts_batch") as mock_create,
        patch("app.repositories.import_batch_repo.update_batch") as mock_update,
    ):
        yield {
            "score_website": mock_score,
            "get_existing_scores": mock_existing,
            "create_contacts_batch": mock_create,
            "update_batch": mock_update,
        }


def _good_score(score=85):
    return {
        "score": score,
        "company_type": "manufacturer",
        "rationale": "Great fit",
        "rejection_reason": None,
        "exa_scrape_success": True,
        "scoring_failed": False,
    }


class TestProcessCsvUpload:
    def test_process_csv_score_above_zero_stored(self, _mock_deps):
        from app.services.import_service import process_csv_upload

        _mock_deps["score_website"].return_value = _good_score(85)
        csv = _csv_bytes("ACME Corp,https://acme.com")
        db = MagicMock()

        process_csv_upload(db, csv, "test.csv", "user-1", "batch-1")

        _mock_deps["create_contacts_batch"].assert_called_once()
        contacts = _mock_deps["create_contacts_batch"].call_args[0][1]
        assert len(contacts) == 1
        assert contacts[0]["score"] == 85

    def test_process_csv_score_zero_discarded(self, _mock_deps):
        from app.services.import_service import process_csv_upload

        _mock_deps["score_website"].return_value = _good_score(0)
        csv = _csv_bytes("ACME Corp,https://acme.com")
        db = MagicMock()

        process_csv_upload(db, csv, "test.csv", "user-1", "batch-1")

        _mock_deps["create_contacts_batch"].assert_not_called()

    def test_process_csv_scoring_failure_stored_with_flag(self, _mock_deps):
        from app.services.import_service import process_csv_upload

        _mock_deps["score_website"].side_effect = Exception("API down")
        csv = _csv_bytes("ACME Corp,https://acme.com")
        db = MagicMock()

        process_csv_upload(db, csv, "test.csv", "user-1", "batch-1")

        _mock_deps["create_contacts_batch"].assert_called_once()
        contacts = _mock_deps["create_contacts_batch"].call_args[0][1]
        assert contacts[0]["scoring_failed"] is True

    def test_process_csv_existing_score_reused(self, _mock_deps):
        from app.services.import_service import process_csv_upload

        cached = _good_score(90)
        _mock_deps["get_existing_scores"].return_value = {"https://acme.com": cached}
        csv = _csv_bytes("ACME Corp,https://acme.com")
        db = MagicMock()

        process_csv_upload(db, csv, "test.csv", "user-1", "batch-1")

        _mock_deps["score_website"].assert_not_called()
        contacts = _mock_deps["create_contacts_batch"].call_args[0][1]
        assert contacts[0]["score"] == 90

    def test_process_csv_no_website_discarded(self, _mock_deps):
        from app.services.import_service import process_csv_upload

        csv = _csv_bytes("ACME Corp,", headers="Company Name,Website")
        db = MagicMock()

        process_csv_upload(db, csv, "test.csv", "user-1", "batch-1")

        _mock_deps["create_contacts_batch"].assert_not_called()

    def test_process_csv_empty_csv(self, _mock_deps):
        from app.services.import_service import process_csv_upload

        csv = b"Company Name,Website\n"
        db = MagicMock()

        process_csv_upload(db, csv, "test.csv", "user-1", "batch-1")

        _mock_deps["create_contacts_batch"].assert_not_called()

    def test_process_csv_missing_company_name_filtered(self, _mock_deps):
        from app.services.import_service import process_csv_upload

        csv = _csv_bytes(",https://acme.com")
        db = MagicMock()

        process_csv_upload(db, csv, "test.csv", "user-1", "batch-1")

        _mock_deps["create_contacts_batch"].assert_not_called()
