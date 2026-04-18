"""ARP table tool: reads the local ARP cache on all platforms."""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.tools import tool

from cyberpunk.utils.system import get_platform, get_platform_command, run_command

# Category marker read by ``cyberpunk.tools.collect_tools`` to classify this
# tool for stealth mode. "passive" means the tool reads local OS state without
# emitting any packets; "active" tools are filtered out in stealth mode.
CATEGORY = "passive"


@tool
def get_arp_table() -> dict[str, Any]:
    """Read the local ARP cache to find known neighbor devices.

    Returns IP addresses, MAC addresses, and interface names for devices
    the host has recently communicated with. Works on Linux, macOS, and
    Windows by dispatching to the platform-specific command.
    """
    platform = get_platform()

    # Linux: prefer ``ip -j neigh show`` for structured JSON output.
    if platform == "linux":
        json_cmd = get_platform_command("arp_table_json")
        if json_cmd:
            result = run_command(json_cmd)
            if result.return_code == 0 and result.stdout.strip():
                return _parse_linux_json(result.stdout)

    cmd = get_platform_command("arp_table")
    if not cmd:
        raise RuntimeError(f"No ARP command available for platform: {platform}")

    result = run_command(cmd)
    if result.return_code != 0:
        raise RuntimeError(f"ARP command failed (rc={result.return_code}): {result.stderr}")

    if platform == "linux":
        return _parse_linux_text(result.stdout)
    if platform == "darwin":
        return _parse_darwin(result.stdout)
    return _parse_win32(result.stdout)


def _parse_linux_json(output: str) -> dict[str, Any]:
    """Parse `ip -j neigh show` JSON output into a normalized dict."""
    entries: list[dict[str, str]] = []
    for item in json.loads(output):
        # FAILED entries have no MAC — the kernel couldn't resolve them.
        if item.get("state") == ["FAILED"]:
            continue
        entry: dict[str, str] = {
            "ip": item.get("dst", ""),
            "mac": item.get("lladdr", ""),
            "interface": item.get("dev", ""),
            "state": ",".join(item.get("state", [])),
        }
        if entry["ip"]:
            entries.append(entry)
    return {"entries": entries, "count": len(entries)}


def _parse_linux_text(output: str) -> dict[str, Any]:
    """Parse `ip neigh show` plain-text output.

    Example line: ``192.168.1.1 dev eth0 lladdr aa:bb:cc:dd:ee:ff REACHABLE``
    """
    entries: list[dict[str, str]] = []
    pattern = re.compile(r"^(\S+)\s+dev\s+(\S+)\s+lladdr\s+([0-9a-fA-F:]+)\s+(\S+)")
    for line in output.strip().splitlines():
        m = pattern.match(line.strip())
        if m:
            entries.append(
                {
                    "ip": m.group(1),
                    "interface": m.group(2),
                    "mac": m.group(3),
                    "state": m.group(4),
                }
            )
    return {"entries": entries, "count": len(entries)}


def _parse_darwin(output: str) -> dict[str, Any]:
    """Parse macOS `arp -a` output.

    Example line: ``? (192.168.1.1) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]``
    """
    entries: list[dict[str, str]] = []
    pattern = re.compile(r"\?\s+\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+([0-9a-fA-F:]+)\s+on\s+(\S+)")
    for line in output.strip().splitlines():
        m = pattern.search(line)
        if m:
            entries.append(
                {
                    "ip": m.group(1),
                    "mac": m.group(2),
                    "interface": m.group(3),
                    "state": "REACHABLE",
                }
            )
    return {"entries": entries, "count": len(entries)}


def _parse_win32(output: str) -> dict[str, Any]:
    """Parse Windows `arp -a` output.

    Example line: ``  192.168.1.1   aa-bb-cc-dd-ee-ff   dynamic``
    """
    entries: list[dict[str, str]] = []
    current_interface = ""
    iface_pattern = re.compile(r"Interface:\s+(\S+)")
    entry_pattern = re.compile(r"\s+(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]+)\s+(\S+)")
    for line in output.strip().splitlines():
        iface_match = iface_pattern.match(line)
        if iface_match:
            current_interface = iface_match.group(1)
            continue
        m = entry_pattern.match(line)
        if m:
            mac_raw = m.group(2)
            # Filter the broadcast pseudo-entry. Real ARP entries never have
            # ff:ff:ff:ff:ff:ff as the resolved MAC.
            if mac_raw in ("ff-ff-ff-ff-ff-ff",):
                continue
            entries.append(
                {
                    "ip": m.group(1),
                    # Normalize to colon-separated so downstream consumers
                    # get one canonical MAC format regardless of platform.
                    "mac": mac_raw.replace("-", ":"),
                    "interface": current_interface,
                    "state": m.group(3),
                }
            )
    return {"entries": entries, "count": len(entries)}
