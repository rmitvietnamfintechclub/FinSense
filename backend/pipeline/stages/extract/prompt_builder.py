from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent / "llm" / "prompts"

# only v1 right now, later evolutions will select the latest version
# configurable instead of hardcoding it here.
_ACTIVE_PROMPT_VERSION = "v1"

def build_prompt(article_text: str) -> str:
    template = (_PROMPTS_DIR / f"{_ACTIVE_PROMPT_VERSION}.txt").read_text(encoding="utf-8")
    return template.format(article_text=article_text)
