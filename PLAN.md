# CyberPunk — Project Specification & Development Plan

## 1. Project Definition

CyberPunk is a CLI-based network intelligence tool that uses a local LLM (via Ollama) with native tool calling to map, profile, and analyze the network around the host machine. It collects data from local OS state and network probes, feeds structured results to an LLM, and produces human-readable network analysis.

**Core principle:** The LLM is a reasoning engine — it decides which tools to call, interprets results, chains calls intelligently, and synthesizes findings. Tools collect raw data. The agent orchestrates the loop between them.

**Key constraints:**
- Fully offline — no data leaves the machine. Local LLM only.
- Plug-and-play UX — predefined commands and flags, no free-form user queries.
- Defensive only — maps and identifies, never exploits or penetrates.
- Cross-platform — Linux, macOS, Windows from day one.

---

## 2. Architecture

```
CLI (Typer + Rich)
    │
    ▼
Predefined Command Handlers (analyze, map, diff, report)
    │
    ▼
Agent Orchestrator ←→ Ollama (local LLM w/ native tool calling)
    │
    ├── Safety Gate (passive vs active enforcement)
    │
    ▼
Tool Registry (auto-discovery from tools/ directory)
    │
    ├── Passive Tools (read local OS state, zero packets)
    ├── Active Tools (send packets, require non-stealth mode)
    └── Analysis Tools (process collected data, no network)
    │
    ▼
Data Layer
    ├── Network Map (SQLite, persists between runs)
    └── Audit Log (append-only JSONL)
```

### 2.1 The Agent Loop

This is the core runtime. Every command triggers it with a predefined prompt (not user-authored).

```
1. Command handler builds a task prompt from predefined template + flags
2. Send to Ollama with: system prompt + task prompt + available tool definitions
3. LLM responds with a tool_call (structured JSON, native function calling)
4. Agent validates:
   a. Tool exists in registry
   b. Arguments match schema
   c. If tool is ACTIVE and stealth mode is on → SKIP, log why
   d. If tool is ACTIVE and stealth mode is off → execute with audit log
5. Execute tool, get structured result
6. Send tool result back to LLM as a tool-role message
7. LLM either:
   a. Returns another tool_call → go to step 3
   b. Returns final text response → proceed to output
8. Parse LLM's final response, render via Rich
9. Persist results to SQLite network map
```

**Iteration cap:** Hard max of 15 tool calls per command invocation. If the LLM hasn't converged, it must summarize what it knows and stop.

**Error handling in loop:** If a tool fails, send the error back to the LLM as the tool result. The LLM should adapt — try an alternative tool or work with partial data. If the LLM returns an invalid tool call (bad name or args), inject a correction message and retry once.

### 2.2 Stealth Mode (`-s` / `--stealth`)

Stealth mode is a global flag that restricts the agent to passive tools only.

- When ON: The tool registry filters out all ACTIVE category tools before sending definitions to the LLM. The LLM literally cannot see or call active tools. The safety gate also blocks any active tool execution as a second layer.
- When OFF: All tools are available. Active tools execute with audit logging. No interactive confirmation — the user opted into active mode by not using `-s`.
- Default: Stealth OFF (full capability). User adds `-s` to restrict.

This is enforced at TWO levels (defense in depth):
1. Tool definitions sent to LLM exclude active tools in stealth mode
2. Agent orchestrator rejects any active tool call in stealth mode (catches edge cases)

---

## 3. CLI Design — Commands & Flags

The CLI is predefined-command-only. No free-form natural language input. Each command maps to a specific task prompt template that the agent executes.

### 3.1 Primary Command

```
cyberpunk analyze [FLAGS]
```

This is the main entry point. It runs a full network analysis cycle.

**Behavior:** Collects all available data (passive, and active unless stealth), builds a device inventory, classifies devices, identifies the gateway and network infrastructure, and outputs a structured analysis.

**Flags:**
| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--stealth` | `-s` | OFF | Passive-only mode. No packets sent. |
| `--output` | `-o` | `rich` | Output format: `rich`, `json`, `plain` |
| `--verbose` | `-v` | OFF | Show tool calls and intermediate reasoning |
| `--save` | none | ON | Persist results to network map database |
| `--subnet` | none | auto-detect | Target subnet for active scans (e.g., `192.168.1.0/24`) |

**Predefined task prompt for analyze:**
```
Analyze the network environment around this host. Follow these steps:
1. Discover local network interfaces to determine our IP, subnet, and gateway.
2. Read the ARP cache to find known neighbor devices.
3. Read the routing table to understand network topology.
4. Check DNS configuration.
5. Check active connections and listening services.
6. Look up MAC vendor information for all discovered MACs.
7. [If active tools available] Perform a ping sweep of the local subnet.
8. [If active tools available] Do a light port scan on discovered devices.
9. Classify each device: type, OS family, role, confidence score.
10. Identify the network gateway, DNS servers, and any network infrastructure.
11. Produce a final structured analysis.
```

### 3.2 Secondary Commands

```
cyberpunk map [-s] [-o FORMAT]
```
Display the current persisted network map from the database. Does NOT run a new scan. If no map exists, suggest running `analyze` first.

```
cyberpunk diff [-s] [-o FORMAT]
```
Run a new analysis and compare with the most recent persisted map. Output: added devices, removed devices, changed devices (new ports, changed MACs, etc.).

```
cyberpunk report [-s] [-o FORMAT] [--format md|html]
```
Run analysis and produce a formatted report document (Markdown or HTML).

```
cyberpunk tools
```
List all registered tools, their category (passive/active), platform availability, and whether they're available in the current environment.

```
cyberpunk config [--show | --set KEY VALUE | --reset]
```
View or modify configuration.

### 3.3 Global Flags

These apply to all commands:
| Flag | Short | Description |
|------|-------|-------------|
| `--stealth` | `-s` | Restrict to passive tools only |
| `--verbose` | `-v` | Show LLM reasoning and tool calls |
| `--config` | `-c` | Path to config file |
| `--version` | none | Show version |

---

## 4. Tool System

### 4.1 Base Tool Contract

Every tool implements this interface:

```python
class BaseTool(ABC):
    @property
    def definition(self) -> ToolDefinition:
        """Name, description, category, parameters, platform support."""

    def execute(self, **kwargs) -> dict[str, Any]:
        """Run the tool. Return structured JSON-serializable dict."""

    def is_available(self) -> bool:
        """Can this tool run on the current OS?"""

    def run(self, **kwargs) -> ToolResult:
        """Public entry: wraps execute() with timing, error handling, audit."""
```

### 4.2 Tool Registry & Auto-Discovery

The registry imports all modules in `cyberpunk/tools/`, finds `BaseTool` subclasses, and registers them. To add a new tool: create a file in `tools/`, implement `BaseTool` — done. No other wiring.

### 4.3 Tool Definitions → Ollama Format

Each tool's `ToolDefinition` converts to Ollama's function-calling schema:
```json
{
  "type": "function",
  "function": {
    "name": "get_arp_table",
    "description": "Read the local ARP cache...",
    "parameters": {
      "type": "object",
      "properties": {},
      "required": []
    }
  }
}
```

### 4.4 Tool Inventory

#### Phase 1 — Passive Tools (read local OS state, zero network traffic)

| Tool Name | Data Source (Linux) | Data Source (macOS) | Data Source (Windows) | Returns |
|-----------|-------------------|--------------------|-----------------------|---------|
| `get_network_interfaces` | `ip -j addr show` | `ifconfig` | `ipconfig /all` | List of interfaces: name, IP, MAC, CIDR, MTU, link state |
| `get_arp_table` | `ip neigh show` | `arp -a` | `arp -a` | List of entries: IP, MAC, state, interface |
| `get_routing_table` | `ip -j route show` | `netstat -rn` | `route print` | Routes: destination, gateway, interface, metric |
| `get_active_connections` | `ss -tunap` | `netstat -an -p tcp` | `netstat -ano` | Active connections: local/remote addr+port, state, PID |
| `get_listening_services` | `ss -tlnp` | `lsof -iTCP -sTCP:LISTEN` | `netstat -ano -p TCP` | Listening ports: port, protocol, PID, process name |
| `get_dns_config` | `/etc/resolv.conf` + `systemd-resolve --status` | `/etc/resolv.conf` + `scutil --dns` | `ipconfig /all` (parse DNS lines) | DNS servers, search domains, MDNS config |
| `get_dhcp_lease` | `/var/lib/dhcp/` + `nmcli` | `ipconfig getpacket en0` | `ipconfig /all` (parse DHCP lines) | DHCP server, lease time, offered gateway/DNS |
| `lookup_mac_vendor` | Local OUI database (mac-vendor-lookup lib) | Same | Same | Map of MAC prefix → vendor name |

**Parsing strategy:** On Linux, prefer `ip -j` (JSON output) when available — it eliminates regex parsing. Fall back to classic commands. On macOS and Windows, parse text output with regex. Each tool handles all three platforms internally but returns an identical output schema.

#### Phase 2 — Active Tools (send packets)

| Tool Name | Technique | What It Discovers |
|-----------|-----------|-------------------|
| `ping_sweep` | ICMP echo or ARP ping via scapy to all IPs in subnet | Alive hosts that didn't appear in ARP cache |
| `port_scan_light` | TCP SYN to top 20 common ports via scapy/socket | Services running on discovered devices |
| `dns_reverse_lookup` | PTR queries for each discovered IP | Hostnames for devices |
| `mdns_discovery` | mDNS multicast query for `_services._dns-sd._udp.local` | Local services advertising via Bonjour/Avahi |
| `upnp_discovery` | SSDP M-SEARCH broadcast | Routers, IoT, media servers |
| `snmp_probe` | SNMPv2 GET with common community strings | Router/switch hardware details (if SNMP open) |

#### Phase 3 — Analysis Tools (no network, process existing data)

| Tool Name | Input | Output |
|-----------|-------|--------|
| `classify_device` | All collected data for one device | Device type, OS guess, role, confidence |
| `compare_scans` | Two scan timestamps | Added/removed/changed devices |
| `get_network_summary` | Current network map | Stats: device count, types, subnets, infrastructure |

---

## 5. Data Models (Pydantic)

All data flowing through the system is typed via Pydantic models.

### 5.1 Core Models

```
NetworkInterface:
  name, ip_address, mac_address, cidr, subnet_mask, mtu, is_up, is_loopback, broadcast

OpenPort:
  port, protocol (tcp/udp), service, banner, state

Device:
  ip_address, mac_address, hostname, vendor (from OUI),
  device_type (enum), os_family (enum), open_ports (list),
  roles (list[str]), confidence (0.0-1.0), last_seen,
  data_sources (list[str]), metadata (dict)

Subnet:
  cidr, gateway_ip, dns_servers, dhcp_server, devices (list[Device])

NetworkMap:
  subnets, local_interfaces, local_hostname,
  scan_type, scan_started, scan_finished, tool_results
```

### 5.2 Enums

```
DeviceType: router, switch, access_point, firewall, workstation, server, printer, phone, iot, unknown
OSFamily: linux, windows, macos, ios, android, freebsd, network_device, unknown
ToolCategory: passive, active, analysis
ScanType: passive, active, full
```

### 5.3 Agent Models

```
ToolDefinition:
  name, description, category, parameters (list[ToolParameter]), requires_root, platform

ToolParameter:
  name, type, description, required, default, enum

ToolCall:
  tool_name, arguments (dict), call_id

ToolResult:
  tool_name, success, data (Any), error, execution_time_ms, call_id

AgentMessage:
  role (system/user/assistant/tool), content, tool_calls, tool_result, timestamp
```

---

## 6. LLM Integration (Ollama)

### 6.1 Client Wrapper

Wraps the `ollama` Python SDK. Responsibilities:
- Connection health check on startup (is Ollama running? is the model pulled?)
- Send messages with tool definitions
- Parse tool_call responses from native function calling
- Handle timeouts and retries (max 2 retries with exponential backoff)
- Token usage tracking for debugging

### 6.2 Model Selection

Recommended models for native tool calling:
- **Primary:** `gemma4:e4b` — best tool-calling accuracy at 7B, fits 8GB VRAM
- **Lightweight:** `qwen2.5:3b` — for constrained hardware
- **Heavy:** `qwen2.5:14b` or `mistral-nemo:12b` — better reasoning if hardware allows

The model is configurable. The LLM client abstracts the model choice — no code changes needed to swap.

### 6.3 System Prompt

The system prompt is stored as a versioned template in `cyberpunk/agent/prompts.py`. It is NOT user-editable at runtime.

**Structure:**
```
ROLE: You are CyberPunk, an expert network analyst running on {hostname} ({os}).
Your job is to analyze the local network by calling tools and reasoning about results.

AVAILABLE CONTEXT:
- Platform: {platform}
- Stealth mode: {stealth_on_off}
- Target subnet: {subnet or "auto-detect from interfaces"}

TOOL USAGE RULES:
- Call one tool at a time.
- After each tool result, state: what you learned, what's still unknown.
- If a tool fails, adapt — try alternatives or work with partial data.
- Do NOT fabricate data. If you don't have info, say so with low confidence.

DEVICE CLASSIFICATION RULES:
- Assign device_type based on: open ports, MAC vendor, hostname, behavior.
- Assign confidence 0.0-1.0. Only use >0.8 when multiple signals agree.
- Gateway identification: device matching the default route, usually has DNS/DHCP.
- IoT identification: Espressif/Tuya/Shelly MAC vendors, unusual port patterns.
- Printer identification: port 9100 (RAW), 631 (IPP), HP/Canon/Epson vendor.

OUTPUT FORMAT:
Return final analysis as structured text with clear sections:
- Network Overview (subnet, gateway, DNS)
- Device Inventory (table: IP, MAC, vendor, type, hostname, confidence)
- Network Infrastructure (routers, switches, APs)
- Notable Findings (unusual devices, unexpected services, anomalies)
```

### 6.4 Task Prompts

Each CLI command uses a predefined task prompt. These are NOT user-authored.

```python
TASK_PROMPTS = {
    "analyze": "Analyze the network environment around this host. Follow these steps: ...",
    "analyze_stealth": "Analyze the network using ONLY passive data collection. ...",
    "diff": "Run a network analysis and compare with the previous scan: {previous_scan_json}. ...",
    "report": "Produce a comprehensive network assessment report. ...",
}
```

---

## 7. Safety & Audit

### 7.1 Audit Logger

Every tool execution and LLM interaction is logged to `~/.cyberpunk/audit.log` (append-only JSONL).

Each entry:
```json
{
  "timestamp": "2026-03-30T14:22:01Z",
  "event": "tool_call",
  "tool": "get_arp_table",
  "category": "passive",
  "arguments": {},
  "success": true,
  "execution_time_ms": 45.2,
  "result_summary": "Found 8 ARP entries"
}
```

Events logged: `tool_call`, `tool_error`, `llm_request`, `llm_response`, `scan_start`, `scan_end`, `stealth_block` (when an active tool is blocked by stealth mode).

### 7.2 Safety Rules (Enforced in Code, Not Prompts)

- Active tools are gated by stealth mode at the registry level (tool definitions not sent to LLM) AND at the orchestrator level (execution blocked).
- Active scans use auto-detected local subnet unless `--subnet` explicitly overrides.
- No tool performs authentication attempts, brute-forcing, or exploitation.
- Agent loop hard-capped at 15 iterations.
- All subprocess calls use `subprocess.run` with `shell=False` and explicit timeout.
- No user-supplied strings are interpolated into shell commands.

---

## 8. Persistence (SQLite)

### 8.1 Schema

```sql
CREATE TABLE scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_type TEXT NOT NULL,          -- passive | active | full
    started_at TEXT NOT NULL,         -- ISO 8601
    finished_at TEXT,
    network_map_json TEXT NOT NULL,   -- Serialized NetworkMap
    device_count INTEGER,
    subnet TEXT
);

CREATE TABLE devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER REFERENCES scans(id),
    ip_address TEXT NOT NULL,
    mac_address TEXT,
    hostname TEXT,
    vendor TEXT,
    device_type TEXT,
    os_family TEXT,
    confidence REAL,
    data_json TEXT                    -- Full Device model as JSON
);

CREATE INDEX idx_devices_scan ON devices(scan_id);
CREATE INDEX idx_devices_ip ON devices(ip_address);
CREATE INDEX idx_scans_time ON scans(started_at);
```

### 8.2 Diff Logic

The `diff` command:
1. Loads the most recent scan from `scans` table.
2. Runs a new analysis.
3. Compares device lists by MAC address (primary key for identity) and IP (secondary).
4. Outputs: NEW devices, GONE devices, CHANGED devices (IP changed, new ports, etc.).

---

## 9. Cross-Platform Strategy

### 9.1 Command Abstraction

A central mapping defines platform-specific commands:

```python
PLATFORM_COMMANDS = {
    "arp_table": {
        "linux":  ["ip", "neigh", "show"],
        "darwin": ["arp", "-a"],
        "win32":  ["arp", "-a"],
    },
    "interfaces": {
        "linux":  ["ip", "-j", "addr", "show"],
        "darwin": ["ifconfig"],
        "win32":  ["ipconfig", "/all"],
    },
    # ... etc
}
```

### 9.2 Command Execution

All commands run through a `run_command()` utility that:
- Uses `subprocess.run` with `shell=False` (security)
- Applies timeout (default 30s)
- Captures stdout/stderr
- Returns structured `CommandResult(stdout, stderr, return_code, execution_time_ms)`
- Has an async variant `run_command_async()` for concurrent probes

### 9.3 Parsing Strategy

- **Linux:** Prefer JSON output flags (`ip -j`) when available. Fall back to text parsing.
- **macOS:** Text parsing with regex. macOS commands have stable output formats.
- **Windows:** Text parsing. Windows command output is more verbose; parsers need to be more tolerant.
- **Every tool returns identical output schema regardless of OS.** The LLM never sees platform differences.

---

## 10. Project Structure

```
cyberpunk/
├── pyproject.toml
├── README.md
├── configs/
│   └── default_config.yaml
├── cyberpunk/
│   ├── __init__.py                  # __version__, __app_name__
│   ├── cli.py                       # Typer app: analyze, map, diff, report, tools, config
│   │
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── orchestrator.py          # Agent loop: LLM ↔ tool cycle, iteration cap, error handling
│   │   ├── llm_client.py            # Ollama SDK wrapper: health check, tool calling, retries
│   │   └── prompts.py               # System prompt + task prompt templates (versioned, not user-editable)
│   │
│   ├── tools/
│   │   ├── __init__.py              # BaseTool ABC, ToolRegistry (auto-discovery), ToolExecutionError
│   │   ├── arp_scanner.py           # get_arp_table (passive)
│   │   ├── interfaces.py            # get_network_interfaces (passive)
│   │   ├── routing.py               # get_routing_table (passive)
│   │   ├── connections.py           # get_active_connections (passive)
│   │   ├── listeners.py             # get_listening_services (passive)
│   │   ├── dns_config.py            # get_dns_config (passive)
│   │   ├── dhcp_lease.py            # get_dhcp_lease (passive)
│   │   ├── mac_lookup.py            # lookup_mac_vendor (passive, local OUI db)
│   │   ├── ping_sweep.py            # ping_sweep (active)
│   │   ├── port_scanner.py          # port_scan_light (active)
│   │   ├── dns_reverse.py           # dns_reverse_lookup (active)
│   │   ├── mdns_discovery.py        # mdns_discovery (active)
│   │   └── upnp_discovery.py        # upnp_discovery (active)
│   │
│   ├── models/
│   │   └── __init__.py              # All Pydantic models: Device, Subnet, NetworkMap, ToolDefinition, etc.
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py                # YAML loader, env var overrides, config schema
│   │   ├── audit.py                 # Append-only JSONL audit logger
│   │   └── database.py              # SQLite: save/load scans, diff queries
│   │
│   └── utils/
│       ├── __init__.py
│       ├── system.py                # run_command(), get_platform(), PLATFORM_COMMANDS
│       └── formatting.py            # Rich helpers: device tables, network trees, progress
│
└── tests/
    ├── conftest.py                  # Shared fixtures: mock registry, mock LLM client
    ├── fixtures/                    # Mocked command outputs per OS per tool
    │   ├── linux/
    │   │   ├── ip_neigh.txt
    │   │   ├── ip_addr.json
    │   │   ├── ip_route.json
    │   │   └── ss_tunap.txt
    │   ├── darwin/
    │   │   ├── arp_a.txt
    │   │   ├── ifconfig.txt
    │   │   └── netstat_rn.txt
    │   └── win32/
    │       ├── arp_a.txt
    │       ├── ipconfig_all.txt
    │       └── route_print.txt
    ├── test_tools/
    │   ├── test_arp_scanner.py
    │   ├── test_interfaces.py
    │   └── ...                      # One test file per tool
    ├── test_agent.py                # Orchestrator loop with mocked Ollama
    ├── test_models.py               # Pydantic model validation
    ├── test_config.py               # Config loading, merging, env overrides
    └── test_audit.py                # Audit log writing and format
```

---

## 11. Tech Stack

| Layer | Library | Why This One |
|-------|---------|-------------|
| CLI framework | `typer` + `rich` | Type-hint-driven CLI generation + beautiful terminal output. Minimal code for polished UX. |
| LLM runtime | Ollama | Local, OpenAI-compatible API, native tool calling, manages model lifecycle. If we ever swap to vLLM or a cloud provider, only the base URL changes. |
| LLM client | `ollama` (Python SDK) | First-party SDK. Handles tool call parsing natively. |
| Packet crafting | `scapy` | Gold standard for Python packet manipulation. Needed for ping sweep, port scan, packet capture. |
| MAC vendor lookup | `mac-vendor-lookup` | Offline OUI database. Maps MAC prefixes to vendor names without network calls. |
| Data validation | `pydantic` v2 | Schema enforcement at every boundary. Serialization to JSON/dict for LLM and SQLite. |
| Configuration | `pyyaml` | Human-readable config files. Pydantic validates after loading. |
| Database | `sqlite3` (stdlib) | Zero-config, file-based, ships with Python. Perfect for local persistence. |
| Testing | `pytest` + `pytest-asyncio` | Standard. Fixtures for mocked command outputs. |
| Linting | `ruff` | Fast, replaces flake8 + isort + pyupgrade. |
| Type checking | `mypy` (strict mode) | Catch type errors before runtime. |

### Python Version: 3.11+

Required for: `StrEnum`, improved `tomllib`, `TaskGroup`, better error messages. No reason to support older versions for a new project.

---

## 12. Configuration

### 12.1 Config File Format

```yaml
# ~/.cyberpunk/config.yaml
llm:
  provider: ollama
  model: gemma4:e4b
  base_url: http://localhost:11434
  temperature: 0.1
  max_tokens: 4096
  timeout: 120              # seconds per LLM call

scanning:
  target_subnet: null       # null = auto-detect from interfaces
  excluded_hosts: []        # IPs to skip during active scans
  max_concurrent_probes: 50
  probe_timeout: 3          # seconds per probe

output:
  format: rich              # rich | json | plain
  verbosity: normal         # quiet | normal | verbose

safety:
  log_all_actions: true
  audit_log_path: ~/.cyberpunk/audit.log
  max_agent_iterations: 15

database:
  path: ~/.cyberpunk/network_map.db
```

### 12.2 Loading Priority (lowest → highest)

1. Built-in defaults (hardcoded in `CyberPunkConfig` Pydantic model)
2. `configs/default_config.yaml` (project-level)
3. `~/.cyberpunk/config.yaml` (user-level)
4. Explicit `--config path` flag
5. Environment variables: `CYBERPUNK_MODEL`, `CYBERPUNK_OLLAMA_URL`

Use recursive dict merging — deeper keys override without clobbering siblings.

---

## 13. Development Phases & Milestones

### Phase 0 — Vertical Slice (Week 1)
**Goal:** One tool, end-to-end: `cyberpunk analyze -s` calls the LLM, which calls `get_arp_table`, gets results, reasons, outputs analysis.

**Build:**
- Project skeleton, pyproject.toml, CLI entry point
- Pydantic models (Device, NetworkMap, ToolDefinition, ToolResult)
- BaseTool + ToolRegistry with auto-discovery
- `get_arp_table` tool (all 3 platforms)
- Ollama client wrapper with tool calling
- Agent orchestrator (loop logic, iteration cap)
- System prompt v1
- Rich output for single-tool result

**Milestone test:** `cyberpunk analyze -s` produces output like:
```
🔍 CyberPunk Network Analysis (stealth mode)
Found 6 devices in ARP cache on 192.168.1.0/24
...
```

### Phase 1 — Passive Tool Breadth (Weeks 2–3)
**Goal:** All passive tools working. `cyberpunk analyze -s` produces a comprehensive device inventory from local data alone.

**Build:**
- All 8 passive tools (interfaces, ARP, routing, connections, listeners, DNS, DHCP, MAC lookup)
- Config loader
- Audit logger
- `cyberpunk tools` command

**Milestone test:** Stealth analysis correctly identifies gateway, DNS servers, and classifies 10+ devices by type using only passive data.

### Phase 2 — Active Tools + Safety (Weeks 4–5)
**Goal:** Active scanning with stealth gating. `cyberpunk analyze` (no `-s`) adds ping sweep and port scan data.

**Build:**
- ping_sweep (scapy-based)
- port_scan_light (top 20 ports)
- dns_reverse_lookup
- Stealth mode enforcement (dual-layer)
- `--subnet` flag for explicit targeting

**Milestone test:** Active scan discovers devices NOT in ARP cache. Stealth mode correctly blocks all active tools.

### Phase 3 — Persistence & Diff (Weeks 6–7)
**Goal:** Network map persists. `cyberpunk diff` shows changes between scans.

**Build:**
- SQLite database layer (save/load scans, query devices)
- `cyberpunk map` command (display persisted map)
- `cyberpunk diff` command (compare scans)
- Device classification improvements via prompt tuning

**Milestone test:** Run analyze twice 24h apart, `diff` correctly shows a new device that appeared.

### Phase 4 — mDNS, UPnP, SNMP Discovery (Weeks 8–9)
**Goal:** Richer active discovery for network infrastructure devices.

**Build:**
- mdns_discovery tool
- upnp_discovery tool
- snmp_probe tool
- Enhanced device classification using service discovery data

**Milestone test:** Router identified by UPnP with model name. Printer found via mDNS with service type.

### Phase 5 — Report Generation & Polish (Weeks 10–12)
**Goal:** Production-quality output. `cyberpunk report` generates a complete network assessment.

**Build:**
- `cyberpunk report` (Markdown and HTML output)
- Rich formatting: network topology tree, device tables, colored confidence indicators
- `cyberpunk config` command
- Comprehensive test suite (mocked outputs for all platforms)
- README, demo examples, packaging for PyPI

**Milestone test:** `cyberpunk report --format html` produces a self-contained HTML file with device inventory, topology diagram, and findings.

---

## 14. Coding Standards & Conventions

### 14.1 General Rules

- **Python 3.11+ only.** Use modern syntax: `X | Y` unions, `StrEnum`, f-strings, walrus operator where readable.
- **Type hints everywhere.** Every function signature, every variable where type isn't obvious. Run `mypy --strict`.
- **Pydantic for all data boundaries.** Any data entering or leaving a component (tool output, LLM messages, config, database rows) must be a Pydantic model. No raw dicts crossing module boundaries.
- **No magic strings.** Use enums for categories, device types, OS families, scan types. Use constants for repeated string values.
- **Docstrings on all public functions and classes.** Google style. Include Args, Returns, Raises sections for non-trivial functions.

### 14.2 Performance

- **Subprocess calls are expensive — don't repeat them.** Cache tool results within a single scan session. If `get_arp_table` was already called, don't call it again in the same `analyze` run. The orchestrator should track completed tool calls.
- **Use `shell=False` in all subprocess calls.** Always pass command as a list, never a string. This is both a security and performance requirement (avoids shell startup overhead).
- **Async for concurrent probes.** Active tools like ping sweep and port scan should use `asyncio` to parallelize. Passive tools run sequentially (they're fast, <100ms each).
- **Limit data sent to LLM.** Summarize large tool outputs before including in context. If ARP returns 200 entries, the LLM gets the full list. But if packet capture returns 10,000 lines, summarize to top talkers and protocol distribution. Never send raw pcap to the LLM.
- **SQLite writes are batched.** Don't write per-device; serialize the entire NetworkMap and write once per scan.

### 14.3 Security

- **Never interpolate user input into subprocess commands.** All commands use list form with `shell=False`. The `--subnet` flag is validated as a valid CIDR notation before use.
- **Validate all tool arguments.** The orchestrator validates arguments against the tool's parameter schema before execution. Reject unknown parameters.
- **Audit everything.** Every tool call, every LLM interaction, every scan start/end. The audit log is append-only and never truncated during normal operation.
- **No secrets in config.** The config file contains no API keys (Ollama is local). If cloud LLM support is added later, use environment variables, never config files.
- **Scapy runs with minimal privilege.** Document that active scanning may require root/admin. Never request elevated privileges programmatically — let the user run with sudo if needed.
- **Input validation on all Pydantic models.** Use validators for IP addresses, MAC addresses, CIDR notation, port ranges. Reject malformed data at the boundary.

### 14.4 Readability

- **One tool per file.** Each file in `tools/` contains exactly one `BaseTool` subclass. File name matches tool purpose (e.g., `arp_scanner.py` contains `ArpTableTool`).
- **Flat is better than nested.** Avoid deep inheritance. `BaseTool` is the only base class. Tools don't inherit from each other.
- **Explicit over implicit.** No `**kwargs` propagation through multiple layers. Named parameters at every interface.
- **Error messages include context.** Not "Command failed" but "Failed to read ARP table: 'ip' command not found. Are you on Linux with iproute2 installed?".
- **Rich output is optional.** Every output path supports `json` and `plain` modes. Rich formatting is a rendering concern, not embedded in business logic.
- **Test file mirrors source file.** `cyberpunk/tools/arp_scanner.py` → `tests/test_tools/test_arp_scanner.py`. One test file per source file.

### 14.5 Git & Code Style

- **Ruff** for linting and formatting. Config in `pyproject.toml`. Line length 100.
- **Conventional commits:** `feat:`, `fix:`, `refactor:`, `test:`, `docs:`.
- **Branch per phase:** `phase/0-vertical-slice`, `phase/1-passive-tools`, etc.
- **Tests must pass before merge.** No untested tool gets merged. Each tool has at least: one test per platform with mocked command output, one test for the "command not found" fallback.

### 14.6 Naming Conventions

- **Tool names:** `verb_noun` in snake_case — `get_arp_table`, `ping_sweep`, `lookup_mac_vendor`.
- **Tool classes:** PascalCase matching the tool name — `ArpTableTool`, `PingSweepTool`.
- **Module files:** snake_case matching purpose — `arp_scanner.py`, `ping_sweep.py`.
- **Config keys:** snake_case, grouped by section.
- **Constants:** UPPER_SNAKE_CASE.
- **Private methods:** Single underscore prefix `_parse_linux()`.

---

## 15. Testing Strategy

### 15.1 Tool Tests (unit)

Each tool is tested against **fixture files** — saved command outputs from real systems. This means:
- Tests run without network access.
- Tests run on any OS (a Linux tool test works on macOS CI by using the Linux fixture).
- Tests validate the parsing logic, not the OS command itself.

**Fixture structure:** `tests/fixtures/{platform}/{command_output}.txt`

**Test pattern:**
```python
def test_arp_table_linux(monkeypatch):
    """Test ARP parsing against real Linux `ip neigh show` output."""
    fixture = load_fixture("linux/ip_neigh.txt")
    monkeypatch.setattr("cyberpunk.utils.system.run_command", lambda *a, **k: fake_result(fixture))
    tool = ArpTableTool()
    result = tool.run()
    assert result.success
    assert result.data["count"] == 8
    assert result.data["entries"][0]["ip"] == "192.168.1.1"
```

### 15.2 Agent Tests (integration)

Mock the Ollama client to return predetermined tool calls. Verify:
- The orchestrator correctly executes the tool and feeds results back.
- Iteration cap is respected.
- Stealth mode blocks active tools.
- Invalid tool calls are handled gracefully.

### 15.3 Model Tests (unit)

Validate Pydantic models accept valid data and reject invalid:
- IP address validation
- MAC address format
- Confidence range 0.0-1.0
- Enum values

---

## 16. Future Considerations (Post v1.0)

Explicitly out of scope for v1.0 but worth designing for:
- **Packet capture analysis** (scapy sniffing + summarization for LLM)
- **Interactive chat mode** (`cyberpunk chat` with multi-turn conversation)
- **Scheduled scanning** (cron-like repeated scans with automatic diff alerts)
- **Plugin system for custom tools** (user drops a `.py` file in a plugins directory)
- **Cloud LLM support** (swap Ollama URL for OpenAI/Anthropic endpoint — the abstraction supports this already since Ollama is OpenAI-compatible)
- **Network diagram export** (Mermaid or Graphviz topology diagrams)
