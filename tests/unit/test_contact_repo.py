"""Unit tests for contact_repo dedupe identity keys and cached-score lookup."""
from __future__ import annotations

from unittest.mock import MagicMock

from app.repositories.contact_repo import (
    _score_row_rank,
    contact_identity_key,
    get_callable_location_counts,
    get_existing_identity_keys,
    get_existing_scores,
)


# ---------------------------------------------------------------------------
# contact_identity_key
# ---------------------------------------------------------------------------


class TestContactIdentityKey:
    def test_normalizes_case_and_whitespace(self):
        key = contact_identity_key({
            "first_name": "  Alice ",
            "last_name": "SMITH",
            "person_linkedin_url": "HTTP://Linkedin.com/in/Alice",
        })
        assert key == ("alice", "smith", "http://linkedin.com/in/alice")

    def test_strips_trailing_slash_from_linkedin(self):
        with_slash = contact_identity_key({
            "first_name": "Alice",
            "last_name": "Smith",
            "person_linkedin_url": "http://linkedin.com/in/alice/",
        })
        without_slash = contact_identity_key({
            "first_name": "Alice",
            "last_name": "Smith",
            "person_linkedin_url": "http://linkedin.com/in/alice",
        })
        assert with_slash == without_slash

    def test_partial_identity_still_keyed(self):
        key = contact_identity_key({"first_name": "Alice"})
        assert key == ("alice", "", "")

    def test_no_identity_fields_returns_none(self):
        assert contact_identity_key({}) is None
        assert contact_identity_key({"first_name": "  ", "last_name": ""}) is None
        assert contact_identity_key({"company_name": "ACME"}) is None


# ---------------------------------------------------------------------------
# get_existing_identity_keys
# ---------------------------------------------------------------------------


def _identity_db(*pages):
    """Mock supabase client whose paged identity queries return the given pages."""
    db = MagicMock()
    execute = db.table.return_value.select.return_value.range.return_value.execute
    execute.side_effect = [MagicMock(data=list(page)) for page in pages]
    return db


class TestGetExistingIdentityKeys:
    def test_live_contact_is_passing(self):
        db = _identity_db([
            {"first_name": "Alice", "last_name": "Smith",
             "person_linkedin_url": "http://l/in/alice",
             "company_type": "distributor", "hidden": False},
        ])
        passing, failed_only = get_existing_identity_keys(db)
        assert passing == {("alice", "smith", "http://l/in/alice")}
        assert failed_only == set()

    def test_rejected_only_contact_is_failed_only(self):
        db = _identity_db([
            {"first_name": "Bob", "last_name": "Jones",
             "person_linkedin_url": "http://l/in/bob",
             "company_type": "rejected", "hidden": True},
        ])
        passing, failed_only = get_existing_identity_keys(db)
        assert passing == set()
        assert failed_only == {("bob", "jones", "http://l/in/bob")}

    def test_hidden_contact_is_failed_only(self):
        """A hidden contact (even typed distributor) is not a live contact."""
        db = _identity_db([
            {"first_name": "Cara", "last_name": "Lee",
             "person_linkedin_url": "http://l/in/cara",
             "company_type": "distributor", "hidden": True},
        ])
        passing, failed_only = get_existing_identity_keys(db)
        assert passing == set()
        assert failed_only == {("cara", "lee", "http://l/in/cara")}

    def test_identity_with_both_live_and_rejected_rows_is_passing(self):
        """Once any copy of the person is live, the identity is never
        re-imported — the rejected duplicate doesn't put it back in play."""
        rows = [
            {"first_name": "Dan", "last_name": "Wu",
             "person_linkedin_url": "http://l/in/dan",
             "company_type": "rejected", "hidden": True},
            {"first_name": "Dan", "last_name": "Wu",
             "person_linkedin_url": "http://l/in/dan",
             "company_type": "distributor", "hidden": False},
        ]
        db = _identity_db(rows)
        passing, failed_only = get_existing_identity_keys(db)
        assert passing == {("dan", "wu", "http://l/in/dan")}
        assert failed_only == set()

    def test_rows_without_identity_fields_skipped(self):
        db = _identity_db([
            {"first_name": "", "last_name": "", "person_linkedin_url": "",
             "company_type": "distributor", "hidden": False},
        ])
        passing, failed_only = get_existing_identity_keys(db)
        assert passing == set()
        assert failed_only == set()

    def test_paginates_until_short_page(self):
        full_page = [
            {"first_name": f"p{i}", "last_name": "x",
             "person_linkedin_url": "", "company_type": "distributor",
             "hidden": False}
            for i in range(1000)
        ]
        second_page = [
            {"first_name": "last", "last_name": "one",
             "person_linkedin_url": "", "company_type": "distributor",
             "hidden": False},
        ]
        db = _identity_db(full_page, second_page)
        passing, _ = get_existing_identity_keys(db)
        assert ("last", "one", "") in passing
        assert len(passing) == 1001
        execute = db.table.return_value.select.return_value.range.return_value.execute
        assert execute.call_count == 2


# ---------------------------------------------------------------------------
# get_existing_scores
# ---------------------------------------------------------------------------


def _scores_db(rows):
    db = MagicMock()
    chain = db.table.return_value.select.return_value.in_.return_value
    chain.not_.is_.return_value.execute.return_value = MagicMock(data=rows)
    return db


class TestGetExistingScores:
    def test_empty_websites_returns_empty_without_query(self):
        db = MagicMock()
        assert get_existing_scores(db, []) == {}
        db.table.assert_not_called()

    def test_returns_score_per_website(self):
        db = _scores_db([
            {"website": "https://a.com", "score": 80, "company_type": "distributor"},
            {"website": "https://b.com", "score": 10, "company_type": "rejected"},
        ])
        scores = get_existing_scores(db, ["https://a.com", "https://b.com"])
        assert scores["https://a.com"]["score"] == 80
        assert scores["https://b.com"]["company_type"] == "rejected"

    def test_passing_row_beats_older_rejected_row(self):
        """A re-evaluated website with both rejected and passing rows must
        surface the passing verdict so imports don't re-score it."""
        db = _scores_db([
            {"website": "https://a.com", "score": 10, "company_type": "rejected"},
            {"website": "https://a.com", "score": 45, "company_type": "distributor"},
        ])
        scores = get_existing_scores(db, ["https://a.com"])
        assert scores["https://a.com"]["score"] == 45
        assert scores["https://a.com"]["company_type"] == "distributor"

    def test_higher_score_wins_within_same_type(self):
        db = _scores_db([
            {"website": "https://a.com", "score": 55, "company_type": "distributor"},
            {"website": "https://a.com", "score": 90, "company_type": "distributor"},
        ])
        scores = get_existing_scores(db, ["https://a.com"])
        assert scores["https://a.com"]["score"] == 90

    def test_order_does_not_matter(self):
        db = _scores_db([
            {"website": "https://a.com", "score": 45, "company_type": "distributor"},
            {"website": "https://a.com", "score": 10, "company_type": "rejected"},
        ])
        scores = get_existing_scores(db, ["https://a.com"])
        assert scores["https://a.com"]["score"] == 45

    def test_websites_queried_in_chunks(self):
        websites = [f"https://site{i}.com" for i in range(120)]
        db = _scores_db([])
        get_existing_scores(db, websites)
        in_mock = db.table.return_value.select.return_value.in_
        assert in_mock.call_count == 3  # 120 websites / 50 per chunk


def _rpc_db(data):
    """Mock supabase client whose .rpc(...).execute() returns the given data."""
    db = MagicMock()
    db.rpc.return_value.execute.return_value = MagicMock(data=data)
    return db


_COUNTS_PAYLOAD = {
    "total": 3,
    "countries": [{"name": "United States", "count": 2}, {"name": "Canada", "count": 1}],
    "states": [{"name": "Texas", "count": 2}, {"name": "Ontario", "count": 1}],
    "cities": [{"name": "Houston", "count": 1}],
    "no_location": 0,
    "call_counts": {"never": 2, "once": 1, "twice": 0, "three_plus": 0},
}


class TestGetCallableLocationCounts:
    def test_returns_rpc_payload(self):
        db = _rpc_db(_COUNTS_PAYLOAD)
        res = get_callable_location_counts(db)
        db.rpc.assert_called_once_with("get_callable_location_counts")
        assert res == _COUNTS_PAYLOAD

    def test_empty_rpc_result_returns_zeroed_shape(self):
        db = _rpc_db(None)
        res = get_callable_location_counts(db)
        assert res["total"] == 0
        assert res["countries"] == []
        assert res["states"] == []
        assert res["cities"] == []
        assert res["no_location"] == 0
        assert res["call_counts"] == {"never": 0, "once": 0, "twice": 0, "three_plus": 0}


class TestGetDistinctLocations:
    def test_returns_rpc_payload(self):
        from app.repositories.contact_repo import get_distinct_locations

        payload = {"cities": ["Berlin"], "states": ["Texas"], "countries": ["US"]}
        db = _rpc_db(payload)
        res = get_distinct_locations(db)
        db.rpc.assert_called_once_with("get_distinct_locations")
        assert res == payload

    def test_empty_rpc_result_returns_empty_lists(self):
        from app.repositories.contact_repo import get_distinct_locations

        db = _rpc_db(None)
        assert get_distinct_locations(db) == {"cities": [], "states": [], "countries": []}


class TestGetContactsExistingIds:
    def test_empty_input_skips_query(self):
        from app.repositories.contact_repo import get_contacts_existing_ids

        db = MagicMock()
        assert get_contacts_existing_ids(db, []) == []
        db.table.assert_not_called()

    def test_returns_existing_ids(self):
        from app.repositories.contact_repo import get_contacts_existing_ids

        db = MagicMock()
        db.table.return_value.select.return_value.in_.return_value \
            .execute.return_value = MagicMock(data=[{"id": "c-1"}, {"id": "c-3"}])
        assert get_contacts_existing_ids(db, ["c-1", "c-2", "c-3"]) == ["c-1", "c-3"]

    def test_chunks_large_id_lists(self):
        from app.repositories.contact_repo import get_contacts_existing_ids

        db = MagicMock()
        in_mock = db.table.return_value.select.return_value.in_
        in_mock.return_value.execute.return_value = MagicMock(data=[])
        get_contacts_existing_ids(db, [f"c-{i}" for i in range(450)])
        assert in_mock.call_count == 3  # 450 ids / 200 per chunk


class TestScoreRowRank:
    def test_distributor_outranks_rejected_regardless_of_score(self):
        assert _score_row_rank({"company_type": "distributor", "score": 40}) > \
            _score_row_rank({"company_type": "rejected", "score": 99})

    def test_null_score_treated_as_zero(self):
        assert _score_row_rank({"company_type": "rejected", "score": None}) == (0, 0)
