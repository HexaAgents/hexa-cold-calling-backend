from __future__ import annotations

from unittest.mock import MagicMock, call, patch

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
        patch("app.services.import_service.settings") as mock_settings,
    ):
        mock_settings.exa_api_key = "fake"
        mock_settings.openai_api_key = "fake"
        mock_settings.openai_model = "gpt-4o-mini"
        mock_settings.apollo_api_key = ""
        mock_create.return_value = []
        yield {
            "score_website": mock_score,
            "get_existing_scores": mock_existing,
            "create_contacts_batch": mock_create,
            "update_batch": mock_update,
            "settings": mock_settings,
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

    def test_process_csv_no_phone_marks_pending_enrichment(self, _mock_deps):
        from app.services.import_service import process_csv_upload

        _mock_deps["score_website"].return_value = _good_score(85)
        csv = _csv_bytes("ACME Corp,https://acme.com")
        db = MagicMock()

        process_csv_upload(db, csv, "test.csv", "user-1", "batch-1")

        contacts = _mock_deps["create_contacts_batch"].call_args[0][1]
        assert contacts[0]["enrichment_status"] == "pending_enrichment"

    def test_process_csv_with_phone_no_enrichment_status(self, _mock_deps):
        from app.services.import_service import process_csv_upload

        _mock_deps["score_website"].return_value = _good_score(85)
        csv = _csv_bytes(
            "ACME Corp,https://acme.com,+15551234567",
            headers="Company Name,Website,Mobile Phone",
        )
        db = MagicMock()

        process_csv_upload(db, csv, "test.csv", "user-1", "batch-1")

        contacts = _mock_deps["create_contacts_batch"].call_args[0][1]
        assert "enrichment_status" not in contacts[0]

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


# ---------------------------------------------------------------------------
# Streaming batch scoring tests
# ---------------------------------------------------------------------------


class TestStreamingScoring:
    def test_each_unique_website_scored_once(self, _mock_deps):
        """Three rows sharing two websites: score_website called exactly twice."""
        from app.services.import_service import process_csv_upload

        _mock_deps["score_website"].return_value = _good_score(80)
        csv_data = _csv_bytes(
            "Alpha Inc,https://alpha.com",
            "Alpha LLC,https://alpha.com",
            "Beta Corp,https://beta.com",
        )
        db = MagicMock()

        process_csv_upload(db, csv_data, "test.csv", "user-1", "batch-1")

        scored_websites = {
            c.kwargs["website"] for c in _mock_deps["score_website"].call_args_list
        }
        assert scored_websites == {"https://alpha.com", "https://beta.com"}
        assert _mock_deps["score_website"].call_count == 2

    def test_single_failure_does_not_block_others(self, _mock_deps):
        """One website fails scoring; the other succeeds and is stored."""
        from app.services.import_service import process_csv_upload

        def _side_effect(**kwargs):
            if kwargs["website"] == "https://bad.com":
                raise Exception("Exa timeout")
            return _good_score(75)

        _mock_deps["score_website"].side_effect = _side_effect
        csv_data = _csv_bytes(
            "Good Co,https://good.com",
            "Bad Co,https://bad.com",
        )
        db = MagicMock()

        process_csv_upload(db, csv_data, "test.csv", "user-1", "batch-1")

        _mock_deps["create_contacts_batch"].assert_called()
        all_contacts = []
        for c in _mock_deps["create_contacts_batch"].call_args_list:
            all_contacts.extend(c[0][1])

        good = [c for c in all_contacts if c["company_name"] == "Good Co"]
        bad = [c for c in all_contacts if c["company_name"] == "Bad Co"]
        assert len(good) == 1
        assert good[0]["score"] == 75
        assert len(bad) == 1
        assert bad[0]["scoring_failed"] is True

        final_update = _mock_deps["update_batch"].call_args_list[-1]
        assert final_update[0][2] == {"status": "completed"}

    def test_all_failures_still_completes(self, _mock_deps):
        """Every score_website call raises; batch still reaches 'completed'."""
        from app.services.import_service import process_csv_upload

        _mock_deps["score_website"].side_effect = Exception("API down")
        csv_data = _csv_bytes(
            "A Corp,https://a.com",
            "B Corp,https://b.com",
        )
        db = MagicMock()

        process_csv_upload(db, csv_data, "test.csv", "user-1", "batch-1")

        all_contacts = []
        for c in _mock_deps["create_contacts_batch"].call_args_list:
            all_contacts.extend(c[0][1])
        assert all(c["scoring_failed"] is True for c in all_contacts)

        final_update = _mock_deps["update_batch"].call_args_list[-1]
        assert final_update[0][2] == {"status": "completed"}

    def test_progress_updated_per_batch(self, _mock_deps):
        """Progress updates include stored_rows and discarded_rows."""
        from app.services.import_service import process_csv_upload

        _mock_deps["score_website"].return_value = _good_score(60)

        rows = [f"Company {i},https://site{i}.com" for i in range(10)]
        csv_data = _csv_bytes(*rows)
        db = MagicMock()

        process_csv_upload(db, csv_data, "test.csv", "user-1", "batch-1")

        progress_calls = [
            c[0][2] for c in _mock_deps["update_batch"].call_args_list
            if "stored_rows" in c[0][2]
        ]
        assert len(progress_calls) >= 1
        assert progress_calls[-1]["stored_rows"] == 10

    def test_score_cache_reused_across_batches(self, _mock_deps):
        """Website scored in batch 1 is not re-scored in batch 2."""
        from app.services.import_service import process_csv_upload

        _mock_deps["score_website"].return_value = _good_score(80)

        rows = []
        for i in range(15):
            rows.append(f"Company {i},https://shared.com")
        csv_data = _csv_bytes(*rows)
        db = MagicMock()

        process_csv_upload(db, csv_data, "test.csv", "user-1", "batch-1")

        assert _mock_deps["score_website"].call_count == 1

    def test_auto_enrichment_triggered_when_apollo_configured(self, _mock_deps):
        """When apollo_api_key is set and contacts lack phones, enrichment is called."""
        from app.services.import_service import process_csv_upload

        _mock_deps["settings"].apollo_api_key = "test-key"
        _mock_deps["score_website"].return_value = _good_score(85)
        _mock_deps["create_contacts_batch"].return_value = [
            {"id": "c-1", "enrichment_status": "pending_enrichment"},
        ]
        csv = _csv_bytes("ACME Corp,https://acme.com")
        db = MagicMock()

        with patch("app.services.apollo_service.enrich_contacts") as mock_enrich:
            process_csv_upload(db, csv, "test.csv", "user-1", "batch-1")
            mock_enrich.assert_called_once_with(db, ["c-1"])

    def test_no_enrichment_when_apollo_not_configured(self, _mock_deps):
        """When apollo_api_key is empty, enrichment is skipped."""
        from app.services.import_service import process_csv_upload

        _mock_deps["settings"].apollo_api_key = ""
        _mock_deps["score_website"].return_value = _good_score(85)
        _mock_deps["create_contacts_batch"].return_value = [
            {"id": "c-1", "enrichment_status": "pending_enrichment"},
        ]
        csv = _csv_bytes("ACME Corp,https://acme.com")
        db = MagicMock()

        with patch("app.services.apollo_service.enrich_contacts") as mock_enrich:
            process_csv_upload(db, csv, "test.csv", "user-1", "batch-1")
            mock_enrich.assert_not_called()


# ---------------------------------------------------------------------------
# Total import timeout tests
# ---------------------------------------------------------------------------


class TestImportTimeout:
    def test_timeout_marks_failed(self, _mock_deps):
        """If elapsed time exceeds MAX_IMPORT_SECONDS, batch is failed."""
        from app.services.import_service import process_csv_upload

        _mock_deps["score_website"].return_value = _good_score(85)
        csv_data = _csv_bytes("ACME Corp,https://acme.com")
        db = MagicMock()

        call_count = 0

        def advancing_clock():
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return 0.0
            return 999.0

        with patch("app.services.import_service.time") as mock_time:
            mock_time.monotonic = advancing_clock
            process_csv_upload(db, csv_data, "test.csv", "user-1", "batch-1")

        statuses = [
            c[0][2]["status"]
            for c in _mock_deps["update_batch"].call_args_list
            if "status" in c[0][2]
        ]
        assert "failed" in statuses

    def test_timeout_during_batch_processing(self, _mock_deps):
        """If timeout hits mid-batch-loop, batch is marked failed and stops."""
        from app.services.import_service import process_csv_upload

        _mock_deps["score_website"].return_value = _good_score(70)
        rows = [f"Company {i},https://site{i}.com" for i in range(30)]
        csv_data = _csv_bytes(*rows)
        db = MagicMock()

        monotonic_values = iter([0.0, 0.0, 999.0, 999.0, 999.0])

        with patch("app.services.import_service.time") as mock_time:
            mock_time.monotonic = lambda: next(monotonic_values)
            process_csv_upload(db, csv_data, "test.csv", "user-1", "batch-1")

        statuses = [
            c[0][2]["status"]
            for c in _mock_deps["update_batch"].call_args_list
            if "status" in c[0][2]
        ]
        assert "failed" in statuses
        assert "completed" not in statuses
