# CURRENT_STATE.md

Living document of how the project is built right now. Claude updates this at the end of each session.

**Last updated:** 2026-04-17

## Phase Progress

| Phase | Scope | Status |
|-------|-------|--------|
| 0 | Vertical slice: `get_arp_table` + agent loop end-to-end | **Complete** |
| 1 | All 8 passive tools + config + audit logger | **In progress** (3/8 tools done) |
| 2 | Active tools (ping sweep, port scan, DNS reverse) + stealth gating | Planned |
| 3 | SQLite persistence + `map` and `diff` commands | Planned |
| 4 | mDNS, UPnP, SNMP discovery tools | Planned |
| 5 | Report generation, Rich polish, packaging | Planned |

## What Exists Now

### Implemented Components

- **CLI** (`cli.py`): Typer app with `analyze` and `tools` commands
- **Agent orchestrator** (`agent/orchestrator.py`): Full agent loop with iteration cap, stealth gate, tool result caching, Rich Live status display with streaming token preview
- **LLM client** (`agent/llm_client.py`): Ollama SDK wrapper with streaming API, `on_token` callback, health check, retries
- **Prompts** (`agent/prompts.py`): System prompt v1 + simplified task prompts
- **Tool system** (`tools/__init__.py`): `BaseTool` ABC, `ToolRegistry` with auto-discovery
- **ARP tool** (`tools/arp_scanner.py`): `get_arp_table` -- Linux (JSON + text fallback), macOS, Windows parsers
- **Interfaces tool** (`tools/interfaces.py`): `get_network_interfaces` -- Linux JSON (`ip -j addr show`), macOS (`ifconfig`), Windows (`ipconfig /all`) parsers. Returns name, IP, MAC, CIDR, subnet mask, MTU, up/down state, loopback detection.
- **Routing tool** (`tools/routing.py`): `get_routing_table` -- Linux JSON (`ip -j route show`), macOS (`netstat -rn`), Windows (`route print`) parsers. Returns routes with destination, gateway, interface, metric. Extracts default gateway. Windows destinations normalized to CIDR notation.
- **Models** (`models/__init__.py`): All Pydantic models -- enums, core models, agent models
- **Config** (`core/config.py`): YAML loader with env var overrides
- **Audit** (`core/audit.py`): Append-only JSONL audit logger
- **Utils** (`utils/system.py`): `run_command()`, `PLATFORM_COMMANDS`, `get_platform()`

### Tests

42 passing: 9 model tests, 7 ARP tool tests, 14 interfaces tool tests, 12 routing tool tests (all across Linux/macOS/Windows fixtures)

### Project Structure (as built)

```
cyberpunk/
  __init__.py
  cli.py
  agent/
    orchestrator.py
    llm_client.py
    prompts.py
  tools/
    __init__.py
    arp_scanner.py
    interfaces.py
    routing.py
  models/
    __init__.py
  core/
    config.py
    audit.py
  utils/
    system.py
tests/
  fixtures/{linux,darwin,win32}/
  test_tools/test_arp_scanner.py
  test_tools/test_interfaces.py
  test_tools/test_routing.py
  test_models.py
```

## Architecture (as implemented)

```
CLI (Typer + Rich)
    |
Predefined Command Handlers
    |
Agent Orchestrator <-> Ollama (local LLM, native tool calling)
    |                   (streaming API + on_token callback)
    +-- Safety Gate (dual-layer stealth enforcement)
    |
Tool Registry (auto-discovery from tools/)
    +-- Passive: get_arp_table, get_network_interfaces, get_routing_table
    |
Data Layer: JSONL audit log (SQLite not yet implemented)
```

## Tech Stack (installed)

| Layer | Library | Version Constraint |
|-------|---------|-------------------|
| CLI | `typer` + `rich` | >=0.12, >=13.0 |
| LLM | `ollama` SDK | >=0.4 |
| Data | `pydantic` v2 | >=2.0 |
| Config | `pyyaml` | >=6.0 |
| Dev | `pytest`, `ruff`, `mypy` | see pyproject.toml |

## Implementation Notes

Things that aren't obvious from reading the code:

- **Streaming fix:** Original `ollama.Client.chat()` was synchronous/blocking with zero visual feedback, making `analyze -s` appear to hang. Switched to `stream=True` with `on_token` callback.
- **StatusDisplay:** Claude Code-style Rich Live panel -- spinner, current phase, streaming token preview, tool results with status indicators, elapsed time.
- **Prompt simplification:** Removed hardcoded step lists that referenced nonexistent tools -- this caused the LLM to hallucinate tool calls. Prompts now tell the LLM to only use tools from its definitions.
- **Timeout:** Default LLM timeout bumped to 300s because 7B model takes ~150s for analysis responses.
- **End-to-end verified:** Stealth analyze flow works -- iteration 1 (tool call) ~13s, iteration 2 (analysis) ~150s, correct structured output.

## Known Issues

- Requires Ollama running locally with a model pulled for end-to-end testing
- Python 3.12 on dev machine (spec says 3.11+, compatible)
- 7B model analysis takes ~150s -- consider `max_tokens` reduction or faster model

## What's Next

Phase 1 work:
- 5 remaining passive tools: connections, listeners, DNS, DHCP, MAC lookup
- `cyberpunk tools` command polish
- Config command (`cyberpunk config`)
- Full stealth analysis integration test
