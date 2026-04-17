"""Routing table tool: reads the local routing table on all platforms."""

from __future__ import annotations

import json
import re
from typing import Any

from cyberpunk.models import ToolCategory, ToolDefinition
from cyberpunk.tools import BaseTool
from cyberpunk.utils.system import get_platform, get_platform_command, run_command


class RoutingTableTool(BaseTool):
    """Read the local routing table to understand network topology."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="get_routing_table",
            description=(
                "Read the local routing table. Returns routes with "
                "destination, gateway, interface, and metric. Useful for "
                "identifying the default gateway and connected subnets."
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
            cmd = get_platform_command("routing_table")
            if cmd:
                result = run_command(cmd)
                if result.return_code == 0 and result.stdout.strip():
                    return self._parse_linux_json(result.stdout)

        # Fall back to text command
        cmd = get_platform_command("routing_table")
        if not cmd:
            raise RuntimeError(f"No routing command available for platform: {platform}")

        result = run_command(cmd)
        if result.return_code != 0:
            raise RuntimeError(f"Routing command failed (rc={result.return_code}): {result.stderr}")

        if platform == "darwin":
            return self._parse_darwin(result.stdout)
        elif platform == "win32":
            return self._parse_win32(result.stdout)
        else:
            raise RuntimeError(f"No parser available for platform: {platform}")

    def _parse_linux_json(self, output: str) -> dict[str, Any]:
        """Parse `ip -j route show` JSON output."""
        routes: list[dict[str, Any]] = []
        default_gateway: str | None = None

        for item in json.loads(output):
            route: dict[str, Any] = {
                "destination": item.get("dst", ""),
                "gateway": item.get("gateway"),
                "interface": item.get("dev", ""),
                "metric": item.get("metric"),
                "protocol": item.get("protocol"),
                "scope": item.get("scope"),
            }
            routes.append(route)

            if item.get("dst") == "default" and item.get("gateway"):
                default_gateway = item["gateway"]

        return {
            "routes": routes,
            "count": len(routes),
            "default_gateway": default_gateway,
        }

    def _parse_darwin(self, output: str) -> dict[str, Any]:
        """Parse macOS `netstat -rn` output.

        Looks for the IPv4 routing table section. Each line has columns:
        Destination, Gateway, Flags, Netif, Expire
        """
        routes: list[dict[str, Any]] = []
        default_gateway: str | None = None
        in_inet_section = False

        # Match lines with: destination, gateway, flags, interface, optional expire
        route_re = re.compile(r"^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)")

        for line in output.splitlines():
            # Detect start of IPv4 section
            if line.strip() == "Internet:":
                in_inet_section = True
                continue
            # Detect start of IPv6 section (stop parsing)
            if line.strip() == "Internet6:":
                in_inet_section = False
                continue
            if not in_inet_section:
                continue
            # Skip header line
            if line.startswith("Destination"):
                continue

            m = route_re.match(line)
            if not m:
                continue

            destination = m.group(1)
            gateway = m.group(2)
            flags = m.group(3)
            interface = m.group(4)

            # Skip link-local and multicast entries that aren't useful
            # Keep them for completeness -- the LLM can decide what's relevant

            route: dict[str, Any] = {
                "destination": destination,
                "gateway": gateway,
                "flags": flags,
                "interface": interface,
            }
            routes.append(route)

            if destination == "default":
                default_gateway = gateway

        return {
            "routes": routes,
            "count": len(routes),
            "default_gateway": default_gateway,
        }

    def _parse_win32(self, output: str) -> dict[str, Any]:
        """Parse Windows `route print` output.

        Looks for the IPv4 Active Routes section. Each line has columns:
        Network Destination, Netmask, Gateway, Interface, Metric
        """
        routes: list[dict[str, Any]] = []
        default_gateway: str | None = None
        in_ipv4_section = False

        route_re = re.compile(r"^\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\d+)\s*$")

        for line in output.splitlines():
            if "IPv4 Route Table" in line:
                in_ipv4_section = True
                continue
            if "IPv6 Route Table" in line:
                in_ipv4_section = False
                continue
            if "Persistent Routes" in line:
                in_ipv4_section = False
                continue
            if not in_ipv4_section:
                continue

            m = route_re.match(line)
            if not m:
                continue

            destination = m.group(1)
            netmask = m.group(2)
            gateway = m.group(3)
            interface = m.group(4)
            metric = int(m.group(5))

            # Build a CIDR-style destination where possible
            if destination != "0.0.0.0" and netmask != "0.0.0.0":
                prefixlen = bin(
                    int.from_bytes(
                        bytes(int(x) for x in netmask.split(".")),
                        byteorder="big",
                    )
                ).count("1")
                cidr_dest = f"{destination}/{prefixlen}"
            elif destination == "0.0.0.0":
                cidr_dest = "default"
            else:
                cidr_dest = destination

            route: dict[str, Any] = {
                "destination": cidr_dest,
                "netmask": netmask,
                "gateway": gateway if gateway != "On-link" else None,
                "interface": interface,
                "metric": metric,
            }
            routes.append(route)

            if destination == "0.0.0.0" and netmask == "0.0.0.0" and gateway != "On-link":
                default_gateway = gateway

        return {
            "routes": routes,
            "count": len(routes),
            "default_gateway": default_gateway,
        }
