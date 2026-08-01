# CLAUDE.md

Standing rules for this repo. They apply to every task here, not just the one
in front of you — read before making changes.

For folder-by-folder purpose, see `docs/FOLDER_STRUCTURE_GUIDANCE.md` and
`docs/ARCHITECTURE.md`. This file is rules, not a map — don't duplicate those.

## Config structure

`backend/core/config.py` currently defines exactly three settings classes:
`DatabaseSettings`, `PipelineSettings`, `APISettings` (instantiated as
`database_settings`, `pipeline_settings`, `api_settings`). A new settings
field belongs in whichever of these three already owns its domain — DB config
→ `DatabaseSettings`, pipeline/LLM config → `PipelineSettings`, API config →
`APISettings`. **Never create a new settings class without asking first.** A
prior PR added a redundant settings class instead of extending an existing
one; extend, don't multiply.

## External identifiers belong in config, not code

Any value naming a specific version of an external dependency — LLM model
name, prompt version, pinned library version, API endpoint — must be a field
in `config.py` (or an env var it reads), never a literal inside application
logic. `PipelineSettings.LLM_MODEL_NAME` and `PipelineSettings.PROMPT_VERSION`
are the pattern to follow: `extract/client.py` and `extract/prompt_builder.py`
both read them from `pipeline_settings` instead of hardcoding at the call site.

## Verify before hardcoding

Before writing any external identifier into code or config for the first time
— LLM model name, package version, API endpoint, SDK method — verify it is
currently valid via web search or official docs. Do not rely on training data
alone: it has a cutoff, and these values change on schedules outside this
repo. This is not optional: `gemini-1.5-flash` was hardcoded from stale
training data, Google fully shut that model down, and nothing caught it
before merge — a real production outage, not a hypothetical.

## Read before you write

Before modifying or extending any existing file, read its actual current
contents in full. Don't assume its structure from a task description alone —
descriptions can predate the file or describe intent rather than current state.

## If uncertain, ask

If a task's instructions conflict with what you find by reading the actual
repo state, stop and flag the conflict rather than silently picking an
interpretation.
