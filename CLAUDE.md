# CLAUDE.md

Project guidance for Claude Code sessions.

## Project Summary

CyberPunk is a CLI network intelligence tool (Python 3.11+) using a local LLM (Ollama) with native tool calling to map and analyze the local network. Fully offline, defensive only, cross-platform (Linux/macOS/Windows).

## Key Files

| File | Purpose | Who updates it |
|------|---------|---------------|
| `PLAN.md` | End goal -- architecture, features, logic, vision. The spec. | Human |
| `CURRENT_STATE.md` | What's built now -- implemented components, phase progress, known issues, implementation notes. | Claude (every session) |
| `CLAUDE.md` | How to work in this repo -- workflow, commands, standards. | Either |

## Session Workflow

### Starting a Session

1. Read this file, `CURRENT_STATE.md`, and skim `PLAN.md` for context.
2. Check `CURRENT_STATE.md` for what's done, in progress, and blocked.
3. If picking up previous work, check memory files for non-obvious decisions.

### During a Session

- **Building something new?** Check `PLAN.md` for the spec (tool inventory, data models, CLI design, etc.)
- **Understanding what exists?** Check `CURRENT_STATE.md` for implementation details.
- Run `pytest` before and after changes.
- Run `ruff check . && ruff format --check .` to verify style.

### Ending a Session

1. **Update `CURRENT_STATE.md`** -- mark completed items, update phase progress, add implementation notes for non-obvious decisions, note new blockers.
2. **Write a memory file** if you hit a non-obvious decision, tradeoff, or bug worth remembering across sessions.
3. Do not skip this, even for small changes.

## Dev Commands

```bash
pip install -e ".[dev]"                         # install
cyberpunk analyze [-s] [-v] [-o rich|json|plain] # run
pytest                                           # test all
pytest tests/test_tools/test_arp_scanner.py      # test one file
ruff check . && ruff format .                    # lint + format
mypy --strict cyberpunk/                         # type check
```

Config: `~/.cyberpunk/config.yaml` | env vars: `CYBERPUNK_MODEL`, `CYBERPUNK_OLLAMA_URL`

## Coding Standards

- **Python 3.11+** -- `X | Y` unions, `StrEnum`, modern syntax
- **`mypy --strict`** -- type hints on every function signature
- **Pydantic at all boundaries** -- no raw dicts crossing modules
- **`shell=False` always** -- commands as lists, never strings
- **One tool per file** -- `tools/arp_scanner.py` -> `get_arp_table` `@tool` function
- **Tool names:** `verb_noun` snake_case (`get_arp_table`, `ping_sweep`)
- **One test file per source file** -- fixture-based, no real network needed
- **Fixtures:** `tests/fixtures/{linux,darwin,win32}/`
- **Cache tool results** per scan session -- no duplicate calls
- Ruff linting, 100-char lines, Google-style docstrings, conventional commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`)

## Key Patterns

**Adding a new tool:** Create a file in `cyberpunk/tools/`, declare a module-level `CATEGORY = "passive"|"active"|"analysis"`, write a `@tool`-decorated function, and append it to the `TOOLS` list in `cyberpunk/tools/__init__.py`.

**Adding a new external integration:** Every integration with an external service (LLM backend, observability, cloud API, etc.) MUST register a health probe in `cyberpunk/core/health.py`. Write a `check_<name>(config) -> HealthResult` function and append a `HealthCheck` entry to `CHECKS`. The probe must never raise — catch broad exceptions and surface them in `message`. `cyberpunk health` is the single source of truth for "is everything wired up".

**Cross-platform commands:** All go through `run_command()` in `utils/system.py`. Map commands via `PLATFORM_COMMANDS`. Linux prefers `ip -j` (JSON). macOS/Windows use regex parsing. Every tool returns identical output schema regardless of OS.

**Stealth mode:** Enforced at TWO layers -- (1) `available_tools(stealth=True)` filters active tools out before `bind_tools`, (2) the per-run tool wrapper re-checks stealth inside every invocation. Both must hold.

**Agent loop:** LangGraph `StateGraph` — `START → agent → (tool_calls? → tools → agent) | (iteration ≥ max → summarize) | END`. `ChatOllama` streams tokens via a `BaseCallbackHandler` into the Rich status panel; tool results are cached per-run and surfaced through `StatusDisplay`.
