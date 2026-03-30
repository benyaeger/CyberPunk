# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Session Protocol (read this first, every session)

At the **end of every session** where code was written or changed, you must:

1. **Update `## Current Status`** below — mark completed phases/tasks, add what's in progress, note what's broken or blocked.
2. **Write a memory file** for any significant addition or change:
   - Path: `C:\Users\Ben Yaeger\.claude\projects\C--Users-Ben-Yaeger-Documents-Github-CyberPunk\memory\`
   - File naming: `project_<topic>.md` (e.g., `project_agent_loop.md`, `project_tool_arp.md`)
   - Add a pointer line to `MEMORY.md` in that same directory
   - Only write memory for things not derivable from reading the code — decisions made, tradeoffs chosen, bugs hit, non-obvious patterns used
3. **Do not skip this** even for small changes. A one-line status update takes 30 seconds and saves the next session 10 minutes of re-orientation.

---

## Current Status

**Phase:** Phase 0 complete — vertical slice implemented.

**Completed:**

- `CyberPunk Plan.md` — full specification written
- `CLAUDE.md` — project guidance initialized
- Project skeleton + `pyproject.toml` (editable install works)
- Pydantic models: all enums, core models, agent models
- `utils/system.py`: `run_command()`, `PLATFORM_COMMANDS`, `get_platform()`
- `BaseTool` ABC + `ToolRegistry` with auto-discovery
- `get_arp_table` tool — Linux (JSON + text), macOS, Windows parsers
- `core/config.py` — YAML loader with env var overrides
- `core/audit.py` — append-only JSONL audit logger
- `agent/llm_client.py` — Ollama SDK wrapper with health check + retries
- `agent/prompts.py` — system prompt v1 + task prompts
- `agent/orchestrator.py` — agent loop with iteration cap, stealth gate, caching
- `cli.py` — Typer app with `analyze` and `tools` commands
- Tests: 16 passing (9 model tests, 7 ARP tool tests across all platforms)

**In Progress:**

- Claude Code-style live status display added to orchestrator (streaming + Rich Live panel)
- LLM client refactored to use Ollama streaming API with `on_token` callback
- Task prompts simplified to avoid referencing tools that don't exist yet
- Default LLM timeout bumped from 120s → 300s (7B model can take ~150s for analysis response)

**What was done this session:**

- **Fixed `analyze -s` appearing to hang**: root cause was blocking synchronous `ollama.Client.chat()` with zero visual feedback. Switched to streaming API.
- **Added `StatusDisplay` class** (`orchestrator.py`): Claude Code-style Rich Live panel showing spinner, current phase, streaming token preview, tool results with ✓/✗/↺/⊘ indicators, and elapsed time.
- **Refactored `OllamaClient.chat()`**: now uses `stream=True` with an `on_token` callback so the UI updates in real time as the LLM generates.
- **Simplified task prompts** (`prompts.py`): removed hardcoded step lists that referenced nonexistent tools (caused LLM to hallucinate tool calls). Now tells LLM to only use tools in its definitions.
- **Verified end-to-end**: manually confirmed full stealth analyze flow works — iteration 1 (tool call) ~13s, iteration 2 (analysis) ~150s, produces correct structured output.

**Up Next (Phase 1):**

- Remaining 7 passive tools (interfaces, routing, connections, listeners, DNS, DHCP, MAC lookup)
- `cyberpunk tools` command polish
- Config command
- Full stealth analysis integration test

**Known Issues / Blockers:**

- Requires Ollama running locally with a model pulled to test `analyze` end-to-end
- Python 3.12 on this machine (spec says 3.11+, compatible)
- 7B model analysis response takes ~150s — consider reducing `max_tokens` or using a faster model for quicker iteration

---

## Project Overview

CyberPunk is a CLI-based network intelligence tool (Python) that uses a local LLM (Ollama) with native tool calling to map and analyze the local network. Key constraints: fully offline, predefined commands only (no free-form user queries), defensive only, cross-platform (Linux/macOS/Windows).

**Status:** Phase 0 complete, live status display added. `CyberPunk Plan.md` is the authoritative specification.

## Commands

Once implemented, the project uses these development commands:

```bash
# Install (from pyproject.toml)
pip install -e ".[dev]"

# Run
cyberpunk analyze [-s] [-v] [-o rich|json|plain]
cyberpunk map | diff | report | tools | config

# Test
pytest
pytest tests/test_tools/test_arp_scanner.py   # single test file

# Lint / format
ruff check .
ruff format .

# Type check
mypy --strict cyberpunk/
```

Config: `~/.cyberpunk/config.yaml` — LLM model, Ollama URL, subnet, scan settings.

## Architecture

```
CLI (Typer + Rich)
    ↓
Predefined Command Handlers
    ↓
Agent Orchestrator ←→ Ollama (local LLM, native tool calling)
    │
    ├── Safety Gate (passive vs. active enforcement — TWO layers)
    ↓
Tool Registry (auto-discovery from tools/ directory)
    ├── Passive Tools — read local OS state, zero packets
    ├── Active Tools — send packets, blocked in stealth mode
    └── Analysis Tools — process data, no network I/O
    ↓
Data Layer: SQLite (persisted NetworkMap) + JSONL audit log
```

### Agent Loop

1. Command handler builds task prompt from predefined template + flags
2. Send to Ollama: system prompt + task prompt + tool definitions
3. LLM returns a `tool_call` → orchestrator validates and executes
4. Tool result fed back to LLM; repeat up to **15 iterations** (hard cap)
5. LLM returns final text → render via Rich, persist to SQLite

### Stealth Mode (`-s`)

Enforced at **two independent layers**:

1. Tool registry filters active tool definitions before sending to LLM (LLM can't see them)
2. Orchestrator blocks execution of any active tool call regardless

Default is stealth OFF (full capability).

### Tool System

`BaseTool` ABC lives in `cyberpunk/tools/__init__.py`. Auto-discovery: drop a `BaseTool` subclass anywhere in `tools/` and it registers automatically. Each tool implements `definition`, `execute(**kwargs)`, `is_available()`, and `run(**kwargs) → ToolResult`.

Tool names: `verb_noun` snake_case (`get_arp_table`, `ping_sweep`). Tool classes: PascalCase (`ArpTableTool`). One tool per file.

### Cross-Platform

All subprocess commands go through `run_command()` in `utils/system.py` using `shell=False` + explicit timeout. `PLATFORM_COMMANDS` dict maps tool → per-OS command list. Every tool returns the same output schema regardless of OS — the LLM never sees platform differences.

On Linux, prefer `ip -j` (JSON output) over text parsing. macOS/Windows use regex text parsing.

## Key Files (planned)

| Path                              | Purpose                                                              |
| --------------------------------- | -------------------------------------------------------------------- |
| `cyberpunk/cli.py`                | Typer app: all commands and flags                                    |
| `cyberpunk/agent/orchestrator.py` | Agent loop, iteration cap, error handling                            |
| `cyberpunk/agent/llm_client.py`   | Ollama SDK wrapper: health check, retries, tool call parsing         |
| `cyberpunk/agent/prompts.py`      | System prompt + task prompt templates (versioned, not user-editable) |
| `cyberpunk/tools/__init__.py`     | `BaseTool` ABC, `ToolRegistry`, `ToolExecutionError`                 |
| `cyberpunk/models/__init__.py`    | All Pydantic models                                                  |
| `cyberpunk/core/config.py`        | YAML config loader, Pydantic validation, env override                |
| `cyberpunk/core/audit.py`         | Append-only JSONL audit logger                                       |
| `cyberpunk/core/database.py`      | SQLite: save/load scans, diff queries                                |
| `cyberpunk/utils/system.py`       | `run_command()`, `PLATFORM_COMMANDS`                                 |

## Coding Standards

- **Python 3.11+** — use `X | Y` unions, `StrEnum`, modern syntax
- **`mypy --strict`** — type hints on every function signature
- **Pydantic for all data boundaries** — no raw dicts crossing module boundaries
- **`shell=False` always** — pass commands as lists, never strings; validate `--subnet` as CIDR before use
- **One test file per source file** — `tools/arp_scanner.py` → `tests/test_tools/test_arp_scanner.py`
- **Tool tests use fixture files** in `tests/fixtures/{linux,darwin,win32}/` — mocked command output, no real network needed
- **Cache tool results** within a single scan session — don't call `get_arp_table` twice per `analyze` run
- **SQLite writes are batched** — serialize full `NetworkMap` once per scan, not per device
- Ruff linting, 100-character line length, Google-style docstrings, conventional commits

## Data Models

Core Pydantic models: `NetworkInterface`, `Device`, `OpenPort`, `Subnet`, `NetworkMap`. Agent models: `ToolDefinition`, `ToolParameter`, `ToolCall`, `ToolResult`, `AgentMessage`. Key enums: `DeviceType`, `OSFamily`, `ToolCategory`, `ScanType`.

## LLM Configuration

Recommended model: `qwen2.5:7b` (best tool-calling accuracy at 7B). Configurable via `~/.cyberpunk/config.yaml` or `CYBERPUNK_MODEL` / `CYBERPUNK_OLLAMA_URL` env vars. Temperature: 0.1. Max agent iterations: 15.

## Development Phases

- **Phase 0:** Vertical slice — one tool (`get_arp_table`) + agent loop end-to-end
- **Phase 1:** All 8 passive tools + config + audit logger
- **Phase 2:** Active tools (ping sweep, port scan, DNS reverse) + stealth gating
- **Phase 3:** SQLite persistence + `map` and `diff` commands
- **Phase 4:** mDNS, UPnP, SNMP discovery tools
- **Phase 5:** Report generation, Rich polish, packaging
