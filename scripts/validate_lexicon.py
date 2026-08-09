import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.core.enums import Concept, Ticker


STATIC_ONTOLOGY_PATH = REPO_ROOT / "backend" / "pipeline" / "lexicon" / "static_ontology.json"


def validate_static_ontology() -> None:
    with STATIC_ONTOLOGY_PATH.open(encoding="utf-8") as ontology_file:
        ontology = json.load(ontology_file)

    expected_tickers = {ticker.value for ticker in Ticker}
    allowed_concepts = {concept.value for concept in Concept}
    actual_tickers = set(ontology)

    missing_tickers = expected_tickers - actual_tickers
    extra_tickers = actual_tickers - expected_tickers
    if missing_tickers or extra_tickers:
        raise ValueError(
            "static_ontology ticker mismatch. "
            f"Missing: {sorted(missing_tickers)}. Extra: {sorted(extra_tickers)}."
        )

    for ticker, concept_weights in sorted(ontology.items()):
        if not isinstance(concept_weights, list) or not concept_weights:
            raise ValueError(f"{ticker} must map to a non-empty list")

        seen_concepts = set()
        for item in concept_weights:
            concept = item.get("concept")
            weight = item.get("weight")

            if concept not in allowed_concepts:
                raise ValueError(f"{ticker} uses invalid concept: {concept}")
            if concept in seen_concepts:
                raise ValueError(f"{ticker} has duplicate concept: {concept}")
            if not isinstance(weight, float) or not 0.0 <= weight <= 1.0:
                raise ValueError(f"{ticker}/{concept} weight must be a float in [0, 1]")

            seen_concepts.add(concept)


if __name__ == "__main__":
    validate_static_ontology()
    print("static_ontology validation passed")
