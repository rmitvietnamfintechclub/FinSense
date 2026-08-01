"""Tests for scripts/seed_concept_dictionary.py.

Runs against a mongomock in-memory database — never the real MONGODB_URI.
"""

from copy import deepcopy

import mongomock
import pytest

from backend.core.enums import Concept
from scripts import seed_concept_dictionary as seed_mod


def _valid_entries() -> list[dict]:
    """One well-formed lexicon entry per Concept enum member, derived from the
    live enum so this fixture can never drift from what validate_lexicon()
    actually checks against."""
    return [
        {"concept": c.value, "aliases": [c.value.title().replace("_", " ")]}
        for c in Concept
    ]


def _db():
    return mongomock.MongoClient()["test_db"]


# --- concept_dictionary.json structural checks ------------------------------


class TestLexiconJsonFile:
    @classmethod
    @pytest.fixture(scope="class")
    def entries(cls):
        return seed_mod.load_lexicon()

    def test_file_is_a_list_of_dicts(self, entries):
        assert isinstance(entries, list)
        assert entries, "lexicon file is empty"
        assert all(isinstance(e, dict) for e in entries)

    def test_each_entry_matches_schema(self, entries):
        for entry in entries:
            assert set(entry.keys()) == {"concept", "aliases"}
            assert isinstance(entry["concept"], str)
            assert isinstance(entry["aliases"], list)
            assert all(isinstance(a, str) for a in entry["aliases"])

    def test_no_duplicate_concept_keys(self, entries):
        concepts = [e["concept"] for e in entries]
        assert len(concepts) == len(set(concepts))

    def test_every_enum_member_has_exactly_one_entry(self, entries):
        concepts = [e["concept"] for e in entries]
        enum_values = {c.value for c in Concept}
        assert set(concepts) == enum_values
        for value in enum_values:
            assert concepts.count(value) == 1

    def test_no_entry_has_concept_outside_enum(self, entries):
        enum_values = {c.value for c in Concept}
        for entry in entries:
            assert entry["concept"] in enum_values

    def test_no_empty_alias_lists(self, entries):
        for entry in entries:
            assert len(entry["aliases"]) > 0, f"{entry['concept']} has an empty aliases list"

    def test_no_empty_string_aliases(self, entries):
        for entry in entries:
            for alias in entry["aliases"]:
                assert alias != "", f"{entry['concept']} has an empty-string alias"

    def test_file_passes_validate_lexicon(self, entries):
        seed_mod.validate_lexicon(entries)  # must not sys.exit


# --- validate_lexicon() ------------------------------------------------------


class TestValidateLexicon:
    def test_valid_lexicon_passes_silently(self, capsys):
        seed_mod.validate_lexicon(_valid_entries())
        assert capsys.readouterr().out == ""

    def test_unknown_concept_rejected(self):
        entries = _valid_entries()
        entries[0]["concept"] = "NOT_A_REAL_CONCEPT"
        with pytest.raises(SystemExit) as exc_info:
            seed_mod.validate_lexicon(entries)
        assert exc_info.value.code == 1

    def test_missing_concept_rejected(self):
        entries = _valid_entries()[:-1]  # one enum member has no entry at all
        with pytest.raises(SystemExit):
            seed_mod.validate_lexicon(entries)

    def test_duplicate_concept_rejected(self):
        entries = _valid_entries()
        entries.append(deepcopy(entries[0]))
        with pytest.raises(SystemExit):
            seed_mod.validate_lexicon(entries)

    @pytest.mark.parametrize(
        "bad_aliases",
        [
            None,
            "not a list",
            [],
            [""],
            [123],
            ["ok", ""],
            ["ok", None],
        ],
        ids=["none", "string", "empty-list", "empty-string", "non-string", "trailing-empty", "trailing-none"],
    )
    def test_malformed_aliases_rejected(self, bad_aliases):
        entries = _valid_entries()
        entries[0]["aliases"] = bad_aliases
        with pytest.raises(SystemExit):
            seed_mod.validate_lexicon(entries)

    def test_entry_missing_concept_key_rejected(self):
        entries = _valid_entries()
        del entries[0]["concept"]
        with pytest.raises(SystemExit):
            seed_mod.validate_lexicon(entries)

    def test_entry_with_non_string_concept_rejected(self):
        entries = _valid_entries()
        entries[0]["concept"] = 123
        with pytest.raises(SystemExit):
            seed_mod.validate_lexicon(entries)

    def test_non_dict_entry_rejected_cleanly_not_crashed(self):
        # A malformed lexicon file (e.g. a bare string in the list instead of
        # {"concept": ..., "aliases": ...}) must fail validation, not raise
        # an unhandled AttributeError from entry.get().
        entries = _valid_entries()
        entries[0] = "not-a-dict-at-all"
        with pytest.raises(SystemExit):
            seed_mod.validate_lexicon(entries)

    def test_error_output_names_the_bad_concept(self, capsys):
        entries = _valid_entries()
        entries[0]["concept"] = "BOGUS_CONCEPT"
        with pytest.raises(SystemExit):
            seed_mod.validate_lexicon(entries)
        out = capsys.readouterr().out
        assert "BOGUS_CONCEPT" in out


# --- seed_concept_dictionary() ----------------------------------------------


class TestSeedConceptDictionary:
    def test_seeds_all_entries(self):
        db = _db()
        entries = _valid_entries()
        seed_mod.seed_concept_dictionary(db, entries)

        assert db.concept_dictionary.count_documents({}) == len(entries)
        for entry in entries:
            doc = db.concept_dictionary.find_one({"concept": entry["concept"]})
            assert doc is not None
            assert doc["aliases"] == entry["aliases"]

    def test_idempotent_on_repeated_run_with_same_data(self):
        db = _db()
        entries = _valid_entries()

        seed_mod.seed_concept_dictionary(db, entries)
        seed_mod.seed_concept_dictionary(db, entries)

        assert db.concept_dictionary.count_documents({}) == len(entries)
        for entry in entries:
            assert db.concept_dictionary.count_documents({"concept": entry["concept"]}) == 1

    def test_rerun_with_changed_aliases_updates_in_place(self):
        db = _db()
        entries = _valid_entries()
        seed_mod.seed_concept_dictionary(db, entries)

        updated = deepcopy(entries)
        updated[0]["aliases"] = ["a brand new alias"]
        seed_mod.seed_concept_dictionary(db, updated)

        assert db.concept_dictionary.count_documents({}) == len(entries)
        doc = db.concept_dictionary.find_one({"concept": updated[0]["concept"]})
        assert doc["aliases"] == ["a brand new alias"]

    def test_seeding_real_lexicon_file_is_idempotent_and_verifies(self):
        db = _db()
        entries = seed_mod.load_lexicon()
        seed_mod.validate_lexicon(entries)

        seed_mod.seed_concept_dictionary(db, entries)
        seed_mod.seed_concept_dictionary(db, entries)

        seed_mod.verify_collection_state(db)  # must not sys.exit


# --- verify_collection_state() ----------------------------------------------


class TestVerifyCollectionState:
    def test_passes_when_collection_matches_enum_1to1(self):
        db = _db()
        seed_mod.seed_concept_dictionary(db, _valid_entries())
        seed_mod.verify_collection_state(db)  # must not sys.exit

    def test_fails_when_a_concept_is_missing(self):
        db = _db()
        seed_mod.seed_concept_dictionary(db, _valid_entries()[:-1])
        with pytest.raises(SystemExit):
            seed_mod.verify_collection_state(db)

    def test_fails_when_a_concept_has_duplicate_documents(self):
        db = _db()
        entries = _valid_entries()
        seed_mod.seed_concept_dictionary(db, entries)

        dup = db.concept_dictionary.find_one({"concept": entries[0]["concept"]})
        dup.pop("_id")
        db.concept_dictionary.insert_one(dup)  # bypass upsert's key uniqueness

        with pytest.raises(SystemExit):
            seed_mod.verify_collection_state(db)

    def test_fails_when_collection_has_extra_unrelated_document(self):
        db = _db()
        seed_mod.seed_concept_dictionary(db, _valid_entries())
        db.concept_dictionary.insert_one({"concept": "NOT_A_CONCEPT", "aliases": ["x"]})

        with pytest.raises(SystemExit):
            seed_mod.verify_collection_state(db)

    def test_error_output_names_the_missing_concept(self, capsys):
        db = _db()
        entries = _valid_entries()
        missing_concept = entries[-1]["concept"]
        seed_mod.seed_concept_dictionary(db, entries[:-1])

        with pytest.raises(SystemExit):
            seed_mod.verify_collection_state(db)

        assert missing_concept in capsys.readouterr().out
