"""
FIN-SENSE 2.0 — concept_dictionary seed script
"""

import json
import sys
from pathlib import Path

import certifi
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from backend.core.config import database_settings
from backend.core.enums import Concept

MONGO_URI = database_settings.MONGODB_URI
DB_NAME = database_settings.MONGODB_DB_NAME

LEXICON_PATH = (
    Path(__file__).resolve().parent.parent
    / "backend"
    / "pipeline"
    / "lexicon"
    / "concept_dictionary.json"
)


def load_lexicon() -> list[dict]:
    with open(LEXICON_PATH, encoding="utf-8") as f:
        return json.load(f)


def validate_lexicon(entries: list[dict]) -> None:
    """Fail on any mismatch between the lexicon file and the Concept enum."""
    errors = []

    seen_concepts: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append(f"Entry is not an object: {entry!r}")
            continue
        concept = entry.get("concept")
        aliases = entry.get("aliases")
        if not isinstance(concept, str) or not concept:
            errors.append(f"Entry missing a valid 'concept' string: {entry!r}")
            continue
        if concept in seen_concepts:
            errors.append(f"Duplicate concept in lexicon file: {concept}")
        seen_concepts.add(concept)
        if not isinstance(aliases, list) or not aliases or not all(
            isinstance(a, str) and a for a in aliases
        ):
            errors.append(f"'{concept}': aliases must be a non-empty list of non-empty strings")

    enum_values = {c.value for c in Concept}
    unknown = seen_concepts - enum_values
    missing = enum_values - seen_concepts
    if unknown:
        errors.append(f"Lexicon has concept(s) not in Concept enum: {sorted(unknown)}")
    if missing:
        errors.append(f"Concept enum member(s) missing from lexicon: {sorted(missing)}")

    if errors:
        print("Lexicon validation FAILED:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)


def seed_concept_dictionary(db, entries: list[dict]) -> None:
    print("Seeding concept_dictionary...")
    for entry in entries:
        db.concept_dictionary.update_one(
            {"concept": entry["concept"]},
            {"$set": {"concept": entry["concept"], "aliases": entry["aliases"]}},
            upsert=True,
        )
        print(f"  Upserted: {entry['concept']}")


def verify_collection_state(db) -> None:
    """Fail if the collection doesn't hold exactly one document per enum member."""
    errors = []
    enum_values = {c.value for c in Concept}

    total = db.concept_dictionary.count_documents({})
    if total != len(enum_values):
        errors.append(
            f"concept_dictionary has {total} document(s), expected {len(enum_values)} "
            f"(one per Concept enum member)"
        )

    for concept in enum_values:
        count = db.concept_dictionary.count_documents({"concept": concept})
        if count != 1:
            errors.append(f"concept_dictionary has {count} document(s) for '{concept}', expected 1")

    if errors:
        print("Post-seed verification FAILED:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)


if __name__ == "__main__":
    print(f"Connecting to database: {DB_NAME}")
    lexicon_entries = load_lexicon()
    validate_lexicon(lexicon_entries)

    try:
        client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
        db = client[DB_NAME]
        # Force connection now so failures surface here with a clear message,
        # rather than deep inside the first update_one() call.
        client.admin.command("ping")
    except PyMongoError as exc:
        print(f"Could not connect to MongoDB at the configured URI: {exc}")
        sys.exit(1)

    try:
        seed_concept_dictionary(db, lexicon_entries)
        verify_collection_state(db)
        print("\nDone. concept_dictionary matches the Concept enum 1:1.")
    finally:
        client.close()