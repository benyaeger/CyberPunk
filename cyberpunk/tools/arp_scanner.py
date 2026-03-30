"""ARP table tool: reads the local ARP cache on all platforms."""

from __future__ import annotations

import json
import re
from typing import Any

from cyberpunk.models import ToolCategory, ToolDefinition
from cyberpunk.tools import BaseTool
from cyberpunk.utils.system import get_platform, get_platform_command, run_command


class ArpTableTool(BaseTool):
    """Read the local ARP cache to discover neighbor devices."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="get_arp_table",
            description=(
                "Read the local ARP cache to find known neighbor devices. "
                "Returns IP addresses, MAC addresses, and interface names "
                "for devices the host has recently communicated with."
            ),
            category=ToolCategory.PASSIVE,
            parameters=[],
            requires_root=False,
            platform=["linux", "darwin", "win32"],
        )

    def is_available(self) -> bool:
        return get_platform() in ("linux", "darwin", "win32")

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        platform = get_platform()

        # On Linux, try JSON output first
        if platform == "linux":
            json_cmd = get_platform_command("arp_table_json")
            if json_cmd:
                result = run_command(json_cmd)
                if result.return_code == 0 and result.stdout.strip():
                    return self._parse_linux_json(result.stdout)

        # Fall back to text command
        cmd = get_platform_command("arp_table")
        if not cmd:
            raise RuntimeError(f"No ARP command available for platform: {platform}")

        result = run_command(cmd)
        if result.return_code != 0:
            raise RuntimeError(
                f"ARP command failed (rc={result.return_code}): {result.stderr}"
            )

        if platform == "linux":
            return self._parse_linux_text(result.stdout)
        elif platform == "darwin":
            return self._parse_darwin(result.stdout)
        else:
            return self._parse_win32(result.stdout)

    def _parse_linux_json(self, output: str) -> dict[str, Any]:
        """Parse `ip -j neigh show` JSON output."""
        entries: list[dict[str, str]] = []
        for item in json.loads(output):
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

    def _parse_linux_text(self, output: str) -> dict[str, Any]:
        """Parse `ip neigh show` text output.

        Example line: 192.168.1.1 dev eth0 lladdr aa:bb:cc:dd:ee:ff REACHABLE
        """
        entries: list[dict[str, str]] = []
        pattern = re.compile(
            r"^(\S+)\s+dev\s+(\S+)\s+lladdr\s+([0-9a-fA-F:]+)\s+(\S+)"
        )
        for line in output.strip().splitlines():
            m = pattern.match(line.strip())
            if m:
                entries.append({
                    "ip": m.group(1),
                    "interface": m.group(2),
                    "mac": m.group(3),
                    "state": m.group(4),
                })
        return {"entries": entries, "count": len(entries)}

    def _parse_darwin(self, output: str) -> dict[str, Any]:
        """Parse macOS `arp -a` output.

        Example line: ? (192.168.1.1) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]
        """
        entries: list[dict[str, str]] = []
        pattern = re.compile(
            r"\?\s+\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+([0-9a-fA-F:]+)\s+on\s+(\S+)"
        )
        for line in output.strip().splitlines():
            m = pattern.search(line)
            if m:
                entries.append({
                    "ip": m.group(1),
                    "mac": m.group(2),
                    "interface": m.group(3),
                    "state": "REACHABLE",
                })
        return {"entries": entries, "count": len(entries)}

    def _parse_win32(self, output: str) -> dict[str, Any]:
        """Parse Windows `arp -a` output.

        Example line:   192.168.1.1     aa-bb-cc-dd-ee-ff     dynamic
        """
        entries: list[dict[str, str]] = []
        current_interface = ""
        iface_pattern = re.compile(r"Interface:\s+(\S+)")
        entry_pattern = re.compile(
            r"\s+(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]+)\s+(\S+)"
        )
        for line in output.strip().splitlines():
            iface_match = iface_pattern.match(line)
            if iface_match:
                current_interface = iface_match.group(1)
                continue
            m = entry_pattern.match(line)
            if m:
                mac_raw = m.group(2)
                # Skip broadcast / incomplete
                if mac_raw in ("ff-ff-ff-ff-ff-ff",):
                    continue
                entries.append({
                    "ip": m.group(1),
                    "mac": mac_raw.replace("-", ":"),
                    "interface": current_interface,
                    "state": m.group(3),
                })
        return {"entries": entries, "count": len(entries)}
