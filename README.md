# CyberPunk

CLI-based network intelligence tool powered by a local LLM. Uses Ollama with native tool calling to map, profile, and analyze your local network -- fully offline, no data leaves your machine.

## What It Does

CyberPunk collects data from your OS (ARP cache, routing tables, network interfaces, active connections, etc.), feeds structured results to a local LLM, and produces human-readable network analysis. The LLM decides which tools to call, interprets results, and synthesizes findings.

**Key principles:**
- **Fully offline** -- local LLM via Ollama, no cloud APIs
- **Defensive only** -- maps and identifies, never exploits
- **Cross-platform** -- Linux, macOS, Windows
- **Predefined commands** -- no free-form queries, reproducible results

## Quick Start

### Prerequisites

- Python 3.11+
- [Ollama](https://ollama.ai) running locally
- A model with tool-calling support pulled (recommended: `gemma4:e4b`)

```bash
ollama pull gemma4:e4b
```

### Install

```bash
pip install ".[dev]"
```

> **Note:** Editable installs (`pip install -e`) are broken on Python 3.14 due to a `.pth` file handling change. Use a regular install and re-run after code changes, or use `python -m cyberpunk` during development.

### Run

```bash
# Stealth analysis (passive only, no packets sent)
cyberpunk analyze -s

# Full analysis (includes active scanning)
cyberpunk analyze

# Verbose mode (show LLM reasoning and tool calls)
cyberpunk analyze -s -v

# JSON output
cyberpunk analyze -s -o json

# List available tools
cyberpunk tools
```

### macOS Usage Notes

CyberPunk works out of the box on macOS with no extra dependencies -- it uses built-in system commands (`arp`, `ifconfig`, `netstat`, `lsof`).

**Permissions:** Some network tools require elevated privileges on macOS. If you see incomplete results or permission errors:

```bash
# Run with sudo for full visibility into network state
sudo cyberpunk analyze -s
```

Specifically, `lsof` (used for listing listening services) and `netstat` (used for active connections and routing) may return limited output without root. ARP cache and interface listing work fine as a regular user.

**Ollama setup on macOS:**

1. Install Ollama from [ollama.ai](https://ollama.ai) (download the macOS app or use Homebrew):
   ```bash
   brew install ollama
   ```
2. Start the Ollama service -- the macOS app runs it automatically, or launch manually:
   ```bash
   ollama serve
   ```
3. Pull a model:
   ```bash
   ollama pull gemma4:e4b
   ```
4. Verify it's running:
   ```bash
   curl http://localhost:11434/api/tags
   ```

**Python on macOS:** The system Python on macOS is outdated. Use [Homebrew](https://brew.sh) or [pyenv](https://github.com/pyenv/pyenv) to get Python 3.11+:

```bash
brew install python@3.13
```

Then install CyberPunk in a virtual environment to avoid conflicts:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install ".[dev]"
```

## Commands

| Command | Description |
|---------|-------------|
| `cyberpunk analyze` | Run a full network analysis |
| `cyberpunk map` | Display the persisted network map |
| `cyberpunk diff` | Compare current scan with previous |
| `cyberpunk report` | Generate a formatted report |
| `cyberpunk tools` | List registered tools and their status |
| `cyberpunk config` | View or modify configuration |

### Key Flags

| Flag | Short | Description |
|------|-------|-------------|
| `--stealth` | `-s` | Passive-only mode -- no packets sent |
| `--output` | `-o` | Output format: `rich`, `json`, `plain` |
| `--verbose` | `-v` | Show tool calls and LLM reasoning |
| `--subnet` | | Target subnet for active scans |

## How It Works

```
CLI (Typer + Rich)
    |
Predefined Command Handlers
    |
Agent Orchestrator <-> Ollama (local LLM with tool calling)
    |
Tool Registry (auto-discovered)
    +-- Passive Tools (read OS state, zero packets)
    +-- Active Tools (send packets, blocked in stealth mode)
    +-- Analysis Tools (process data, no network I/O)
    |
Data Layer: SQLite + JSONL audit log
```

The agent loop: command triggers a predefined prompt -> LLM calls tools -> orchestrator validates and executes -> results fed back -> repeat (max 15 iterations) -> final analysis rendered.

**Stealth mode** (`-s`) restricts to passive tools only, enforced at two independent layers for defense in depth.

## Configuration

Config file: `~/.cyberpunk/config.yaml`

```yaml
llm:
  model: gemma4:e4b
  base_url: http://localhost:11434
  temperature: 0.1

scanning:
  target_subnet: null  # auto-detect
```

Environment variable overrides: `CYBERPUNK_MODEL`, `CYBERPUNK_OLLAMA_URL`

## Development

```bash
pytest                        # run tests
ruff check . && ruff format . # lint + format
mypy --strict cyberpunk/      # type check
```

See `CURRENT_STATE.md` for current implementation details and `PLAN.md` for the full specification.

## Project Status

**Phase 0 complete** -- vertical slice with ARP tool + full agent loop working end-to-end.

Currently building Phase 1: all passive tools, config command, and integration tests.

## License

MIT
