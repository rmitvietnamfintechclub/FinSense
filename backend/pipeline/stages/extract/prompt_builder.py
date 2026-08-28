import json
from functools import cache
from pathlib import Path

from backend.core.config import pipeline_settings

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_LEXICON_PATH = Path(__file__).parents[2] / "lexicon" / "vietnam_financial_lexicon.json"

# Both rubric docs carry unpopulated example slots behind this marker plus an HTML
# maintainer note. Neither is addressed to the model, so both are stripped on load;
# the Examples section starts rendering by itself once the slots hold real text.
_PENDING_EXAMPLE = "example pending real data"

@cache
def _load_template(version: str) -> str:
    return (_PROMPTS_DIR / f"{version}.txt").read_text(encoding="utf-8")

def _strip_maintainer_notes(doc: str) -> str:
    """Drop HTML comments, and the Examples section while its slots are unfilled."""
    while "<!--" in doc:
        head, _, rest = doc.partition("<!--")
        _, _, tail = rest.partition("-->")
        doc = head + tail

    head, marker, examples = doc.partition("\n## Examples")
    if marker and _PENDING_EXAMPLE in examples:
        return head.rstrip() + "\n"
    return doc.rstrip() + "\n"

@cache
def _load_rubric(name: str) -> str:
    path = _PROMPTS_DIR / "docs" / f"{name}.md"
    return _strip_maintainer_notes(path.read_text(encoding="utf-8"))

def _render_entry(term: str, fields: dict) -> str:
    """One lexicon entry as a bullet. Field names are not hardcoded so a schema
    addition in the JSON reaches the prompt without a code change."""
    detail = "; ".join(f"{key.replace('_', ' ')}: {value}" for key, value in fields.items())
    return f"- **{term}** — {detail}"

@cache
def _load_lexicon() -> str:
    data = json.loads(_LEXICON_PATH.read_text(encoding="utf-8"))
    sections = []
    for section, entries in data.items():
        lines = [f"## {section.replace('_', ' ').capitalize()}", ""]
        lines += [_render_entry(term, fields) for term, fields in entries.items()]
        sections.append("\n".join(lines))
    return "\n\n".join(sections)

def build_prompt(article_text: str) -> tuple[str, str]:
    prompt_version = pipeline_settings.PROMPT_VERSION
    template = _load_template(prompt_version)

    # References first, article last: an article quoting a placeholder string must not
    # be able to pull a reference section into itself.
    if "{lexicon}" in template:
        template = template.replace("{lexicon}", _load_lexicon())
    for placeholder, rubric in (
        ("{sentiment_rubric}", "SENTIMENT"),
        ("{confidence_rubric}", "AI_CONFIDENCE"),
    ):
        if placeholder in template:
            template = template.replace(placeholder, _load_rubric(rubric))

    return template.replace("{article_text}", article_text), prompt_version
