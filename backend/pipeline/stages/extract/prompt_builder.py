from pathlib import Path
from functools import lru_cache
from backend.core.config import pipeline_settings

_PROMPTS_DIR = Path(__file__).parent / "prompts"

@lru_cache(maxsize=None)
def _load_template(version: str) -> str:
    return (_PROMPTS_DIR / f"{version}.txt").read_text(encoding="utf-8")

def build_prompt(article_text: str) -> tuple[str, str]:
    prompt_version = pipeline_settings.PROMPT_VERSION
    template = _load_template(prompt_version)
    return template.replace("{article_text}", article_text), prompt_version
