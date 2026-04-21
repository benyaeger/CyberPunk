# CURRENT_STATE.md

Living document of how the project is built right now. Claude updates this at the end of each session.

**Last updated:** 2026-04-21

## Phase Progress

| Phase | Scope | Status |
|-------|-------|--------|
| 0 | Vertical slice: `get_arp_table` + agent loop end-to-end | **Complete** |
| 1 | All 8 passive tools + config + audit logger | **Complete** (8/8 passive tools done) |
| 2 | Active tools (ping sweep, port scan, DNS reverse) + stealth gating | Planned |
| 3 | SQLite persistence + `map` and `diff` commands | Planned |
| 4 | mDNS, UPnP, SNMP discovery tools | Planned |
| 5 | Report generation, Rich polish, packaging | Planned |

## What Exists Now

### Implemented Components

- **CLI** (`cli.py`): Typer app with `analyze`, `tools`, and `health` commands
- **Health checks** (`core/health.py`): Registry of external-integration probes (`ollama`, `langfuse`). `run_all(config)` runs every probe and surfaces results for the `cyberpunk health` command. Langfuse is skipped-as-OK when no keys are configured.
- **Agent runner** (`agent/agent.py`): `AgentRunner` assembles system/task prompts, wraps tools for the run, drives the LangGraph state graph via `graph.stream()`, and extracts the final text message.
- **Agent graph** (`agent/graph.py`): LangGraph `StateGraph` with `agent`, `tools` (prebuilt `ToolNode`), and `summarize` nodes. Conditional edge routes to `summarize` when iteration cap is hit, to `tools` when the last AIMessage has tool_calls, otherwise to END.
- **LLM factory** (`agent/llm.py`): `build_chat_model(config)` returns a streaming `ChatOllama`; `health_check(config)` hits the raw `ollama` SDK for a friendly startup probe.
- **Callbacks** (`agent/callbacks.py`): `AgentCallbacks(BaseCallbackHandler)` forwards streamed tokens to the Rich status panel and emits `llm_request` / `llm_response` audit events.
- **Tool wrapper** (`agent/tool_wrapper.py`): Per-run wrapper that adds caching (closure-captured dict keyed by tool name + sorted args), second-layer stealth gate, and status/audit side effects around each `@tool` function.
- **Status display** (`agent/status.py`): Rich `Live` panel — spinner, current phase, streaming token preview, tool history with ✓ / ✗ / ↺ / ⊘ glyphs, elapsed time.
- **Prompts** (`agent/prompts.py`): System prompt v1 + per-command task prompt templates.
- **Tool collection** (`tools/__init__.py`): Flat `TOOLS: list[BaseTool]` of LangChain `@tool` functions; `available_tools(stealth=False)` returns a stealth-filtered copy.
- **ARP tool** (`tools/arp_scanner.py`): `get_arp_table` (`@tool`) — Linux (JSON + text fallback), macOS, Windows parsers.
- **Interfaces tool** (`tools/interfaces.py`): `get_network_interfaces` (`@tool`) — Linux JSON (`ip -j addr show`), macOS (`ifconfig`), Windows (`ipconfig /all`) parsers. Returns name, IP, MAC, CIDR, subnet mask, MTU, up/down state, loopback detection.
- **Routing tool** (`tools/routing.py`): `get_routing_table` (`@tool`) — Linux JSON (`ip -j route show`), macOS (`netstat -rn`), Windows (`route print`) parsers. Returns routes with destination, gateway, interface, metric. Extracts default gateway. Windows destinations normalized to CIDR notation.
- **Connections tool** (`tools/connections.py`): `get_active_connections` (`@tool`) — Linux (`ss -tunap`), macOS (`netstat -an -p tcp`), Windows (`netstat -ano`) parsers. Returns protocol, local/remote addr+port, state, PID, and process name (Linux only).
- **Listeners tool** (`tools/listeners.py`): `get_listening_services` (`@tool`) — Linux (`ss -tlnp`), macOS (`lsof -iTCP -sTCP:LISTEN`), Windows (`netstat -ano -p TCP` filtered to LISTENING rows). Returns port, bind address, PID, process name. Strips `%ifname` scope IDs from Linux bind addresses.
- **DNS config tool** (`tools/dns_config.py`): `get_dns_config` (`@tool`) — Linux/macOS parse `/etc/resolv.conf`, Windows parses DNS lines out of `ipconfig /all` including multi-line continuation entries.
- **DHCP lease tool** (`tools/dhcp_lease.py`): `get_dhcp_lease(interface=None)` (`@tool`) — Linux (`nmcli -t dev show`), macOS (`ipconfig getpacket <iface>`, defaults to `en0`), Windows (`ipconfig /all` per-adapter DHCP fields). Returns server, gateway, DNS servers, lease time, subnet mask, domain name.
- **MAC vendor tool** (`tools/mac_lookup.py`): `lookup_mac_vendor(mac_addresses)` (`@tool`) — wraps `mac-vendor-lookup`'s offline OUI database. Takes a list of MACs, returns a vendor map and unresolved list. A shared `MacLookup` singleton avoids re-loading the OUI table.
- **Models** (`models/__init__.py`): Domain-only Pydantic models — enums (`DeviceType`, `OSFamily`, `ScanType`), `NetworkInterface`, `OpenPort`, `Device`, `Subnet`, `NetworkMap`. All agent-side models (`ToolDefinition`, `ToolResult`, `ToolCall`, `AgentMessage`, `ToolCategory`, `ToolParameter`) were removed — LangChain's message / tool types replace them.
- **Config** (`core/config.py`): YAML loader with env var overrides.
- **Audit** (`core/audit.py`): Append-only JSONL audit logger.
- **Utils** (`utils/system.py`): `run_command()`, `PLATFORM_COMMANDS`, `get_platform()`.

### Tests

70 passing: 6 model tests, 7 ARP, 14 interfaces, 12 routing, 10 connections, 8 listeners, 4 DNS, 5 DHCP, 4 MAC-vendor (all across Linux/macOS/Windows fixtures where relevant). Tool tests call `tool.invoke({...})` on the `@tool` function and assert on the returned dict; error paths expect `pytest.raises(RuntimeError)`. MAC-vendor tests mock `_lookup.lookup` to stay fully offline.

### Project Structure (as built)

```
cyberpunk/
  __init__.py
  cli.py
  agent/
    __init__.py       # exports AgentRunner
    agent.py          # AgentRunner.run()
    graph.py          # build_graph(): StateGraph with agent/tools/summarize nodes
    llm.py            # build_chat_model + health_check
    tool_wrapper.py   # wrap_tools_for_run(tools, *, stealth, cache, status, audit)
    callbacks.py      # AgentCallbacks(BaseCallbackHandler)
    status.py         # StatusDisplay (Rich Live panel)
    prompts.py        # system + task prompt templates
  tools/
    __init__.py       # TOOLS list, available_tools(stealth)
    arp_scanner.py
    interfaces.py
    routing.py
    connections.py
    listeners.py
    dns_config.py
    dhcp_lease.py
    mac_lookup.py
  models/
    __init__.py       # domain models only
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
  test_tools/test_connections.py
  test_tools/test_listeners.py
  test_tools/test_dns_config.py
  test_tools/test_dhcp_lease.py
  test_tools/test_mac_lookup.py
  test_models.py
```

## Architecture (as implemented)

```
CLI (Typer + Rich)
    |
AgentRunner
    |
    +-- LangGraph StateGraph
    |       agent node  → ChatOllama.invoke (streaming + tool calling)
    |       tools node  → LangGraph ToolNode over wrapped @tool functions
    |       summarize   → ChatOllama.invoke (no tools bound) at cap
    |
    +-- Per-run tool wrapper: cache + stealth gate + status/audit hooks
    +-- BaseCallbackHandler: stream tokens into Rich panel + audit LLM events
    |
Tool collection (LangChain @tool functions)
    +-- Passive: get_arp_table, get_network_interfaces, get_routing_table,
    |             get_active_connections, get_listening_services,
    |             get_dns_config, get_dhcp_lease, lookup_mac_vendor
    |
Data Layer: JSONL audit log (SQLite not yet implemented)
```

## Tech Stack (installed)

| Layer | Library | Version Constraint |
|-------|---------|-------------------|
| CLI | `typer` + `rich` | >=0.12, >=13.0 |
| Agent framework | `langchain`, `langchain-core`, `langgraph` | >=0.3, >=0.3, >=0.2 |
| LLM client | `langchain-ollama` (`ChatOllama`) | >=0.2 |
| LLM health check | `ollama` SDK | >=0.4 (one-shot probe only) |
| Data | `pydantic` v2 | >=2.0 |
| Config | `pyyaml` | >=6.0 |
| OUI db | `mac-vendor-lookup` | >=0.1.12 |
| Dev | `pytest`, `ruff`, `mypy` | see pyproject.toml |

## Implementation Notes

Things that aren't obvious from reading the code:

- **Why the status + audit callbacks live outside the graph:** LangGraph doesn't surface streamed tokens to graph-level code; the supported extension point is LangChain's `BaseCallbackHandler`. We forward `on_llm_new_token` into `StatusDisplay.add_token` and emit `llm_request`/`llm_response` audit events from the same handler so the graph itself stays a pure state machine.
- **Iteration counter is read via a closure:** The graph owns the `iteration` field on state; `AgentRunner` captures the latest value in a `current_iteration = {"value": 0}` dict that's updated on each `graph.stream()` yield. `AgentCallbacks` calls a zero-arg `iteration_provider` to read it on every LLM boundary, so audit entries reflect the iteration they were actually emitted in.
- **Two-layer stealth enforcement:** (1) `available_tools(stealth=True)` filters active tools *before* `bind_tools` so the LLM literally can't see them; (2) the per-run wrapper still checks stealth inside every invocation to catch hallucinated tool names that weren't bound. Removing either layer breaks the safety guarantee.
- **Summarize node uses the un-bound model:** `build_graph` calls `model.bind_tools(tools)` for the agent node but hands the original model to the summarize node, so once we've told the LLM "no more tool budget" it also *can't* call tools.
- **`recursion_limit` buffer:** We pass `2 * max_iterations + 4` to `graph.stream()` — enough for `agent→tools` pairs plus the final `summarize` visit, with headroom before LangGraph's `GraphRecursionError` would mask the intended cap.
- **Category marker lives on `tool.tags`:** Each tool module declares `CATEGORY = "passive"|"active"|"analysis"`; `tools/__init__.py` copies it onto `tool.tags` so the stealth filter and CLI `tools` command can introspect category without a separate enum.
- **DHCP tool bypasses `PLATFORM_COMMANDS`:** macOS needs an interface arg baked into the command (`ipconfig getpacket en0`), which doesn't fit the static mapping. `dhcp_lease.py` builds commands inline per platform and accepts an optional `interface` parameter; Linux/Windows ignore it since `nmcli`/`ipconfig` already enumerate every adapter.
- **`mac-vendor-lookup` loads the OUI db lazily:** A module-level `MacLookup()` singleton in `mac_lookup.py` is shared across calls. First lookup triggers the in-memory load of the bundled table; subsequent lookups hit the cache. Tests patch `_lookup.lookup` so no OUI table I/O happens during CI.
- **Timeout:** Default LLM timeout bumped to 300s because 7B model takes ~150s for analysis responses.
- **End-to-end verified (pre-migration):** Stealth analyze flow worked — iteration 1 (tool call) ~13s, iteration 2 (analysis) ~150s, correct structured output. Post-migration end-to-end not re-verified on this machine (no Ollama running in the test environment).

## Known Issues

- Requires Ollama running locally with a model pulled for end-to-end testing.
- Post-migration end-to-end run not executed on this worktree — unit tests, lint, and type checks pass but a live `cyberpunk analyze` invocation hasn't been confirmed yet.
- `mypy --strict` reports one pre-existing `types-PyYAML` stub warning in `cyberpunk/core/config.py`; unrelated to the migration.
- Python 3.14 on dev machine emits a warning about LangChain's Pydantic v1 compatibility; tests pass.

## What's Next

- Re-verify the end-to-end flow against a live Ollama (`cyberpunk analyze -s`) and confirm streaming + audit events still look right after the migration.
- `cyberpunk tools` command polish.
- Config command (`cyberpunk config`).
- Full stealth analysis integration test using a fake `BaseChatModel` that scripts tool-call / final-answer sequences.
- Phase 2 active tools (ping sweep, port scan, DNS reverse) + stealth gating integration test.
