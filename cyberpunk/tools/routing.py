"""Routing table tool: reads the local routing table on all platforms."""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.tools import tool

from cyberpunk.utils.system import get_platform, get_platform_command, run_command

CATEGORY = "passive"


@tool
def get_routing_table() -> dict[str, Any]:
    """Read the local routing table.

    Returns routes with destination, gateway, interface, and metric, plus
    the detected default gateway. Useful for identifying the default route
    and connected subnets. Works on Linux, macOS, and Windows.
    """
    platform = get_platform()

    cmd = get_platform_command("routing_table")
    if not cmd:
        raise RuntimeError(f"No routing command available for platform: {platform}")

    result = run_command(cmd)
    if result.return_code != 0:
        raise RuntimeError(f"Routing command failed (rc={result.return_code}): {result.stderr}")

    if platform == "linux":
        return _parse_linux_json(result.stdout)
    if platform == "darwin":
        return _parse_darwin(result.stdout)
    if platform == "win32":
        return _parse_win32(result.stdout)
    raise RuntimeError(f"No parser available for platform: {platform}")


def _parse_linux_json(output: str) -> dict[str, Any]:
    """Parse `ip -j route show` JSON output."""
    routes: list[dict[str, Any]] = []
    default_gateway: str | None = None

    for item in json.loads(output):
        routes.append(
            {
                "destination": item.get("dst", ""),
                "gateway": item.get("gateway"),
                "interface": item.get("dev", ""),
                "metric": item.get("metric"),
                "protocol": item.get("protocol"),
                "scope": item.get("scope"),
            }
        )
        if item.get("dst") == "default" and item.get("gateway"):
            default_gateway = item["gateway"]

    return {"routes": routes, "count": len(routes), "default_gateway": default_gateway}


def _parse_darwin(output: str) -> dict[str, Any]:
    """Parse macOS `netstat -rn` output.

    Only the IPv4 (``Internet:``) section is parsed — the IPv6 section is
    skipped to keep the output focused and avoid schema surprises downstream.
    """
    routes: list[dict[str, Any]] = []
    default_gateway: str | None = None
    in_inet_section = False

    route_re = re.compile(r"^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)")

    for line in output.splitlines():
        if line.strip() == "Internet:":
            in_inet_section = True
            continue
        if line.strip() == "Internet6:":
            in_inet_section = False
            continue
        if not in_inet_section:
            continue
        if line.startswith("Destination"):
            continue

        m = route_re.match(line)
        if not m:
            continue

        destination = m.group(1)
        gateway = m.group(2)
        routes.append(
            {
                "destination": destination,
                "gateway": gateway,
                "flags": m.group(3),
                "interface": m.group(4),
            }
        )
        if destination == "default":
            default_gateway = gateway

    return {"routes": routes, "count": len(routes), "default_gateway": default_gateway}


def _parse_win32(output: str) -> dict[str, Any]:
    """Parse Windows `route print` output.

    Only the IPv4 Active Routes block is parsed. Destinations are normalized:
    ``0.0.0.0`` with ``0.0.0.0`` netmask becomes the literal ``default``, and
    other destinations get CIDR notation from the netmask.
    """
    routes: list[dict[str, Any]] = []
    default_gateway: str | None = None
    in_ipv4_section = False

    route_re = re.compile(r"^\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\d+)\s*$")

    for line in output.splitlines():
        if "IPv4 Route Table" in line:
            in_ipv4_section = True
            continue
        if "IPv6 Route Table" in line or "Persistent Routes" in line:
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

        if destination != "0.0.0.0" and netmask != "0.0.0.0":
            prefixlen = bin(
                int.from_bytes(bytes(int(x) for x in netmask.split(".")), byteorder="big")
            ).count("1")
            cidr_dest = f"{destination}/{prefixlen}"
        elif destination == "0.0.0.0":
            cidr_dest = "default"
        else:
            cidr_dest = destination

        routes.append(
            {
                "destination": cidr_dest,
                "netmask": netmask,
                # "On-link" is Windows-speak for "no gateway needed" — we
                # normalize it to None so the LLM sees a consistent schema.
                "gateway": gateway if gateway != "On-link" else None,
                "interface": m.group(4),
                "metric": int(m.group(5)),
            }
        )

        if destination == "0.0.0.0" and netmask == "0.0.0.0" and gateway != "On-link":
            default_gateway = gateway

    return {"routes": routes, "count": len(routes), "default_gateway": default_gateway}
