"""Network interfaces tool: reads local interface configuration on all platforms."""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.tools import tool

from cyberpunk.utils.system import get_platform, get_platform_command, run_command

CATEGORY = "passive"


def _cidr_from_prefixlen(prefixlen: int) -> str:
    """Convert a prefix length (e.g. 24) to a dotted-decimal mask."""
    mask = (0xFFFFFFFF << (32 - prefixlen)) & 0xFFFFFFFF
    return f"{(mask >> 24) & 0xFF}.{(mask >> 16) & 0xFF}.{(mask >> 8) & 0xFF}.{mask & 0xFF}"


def _netmask_hex_to_dotted(hex_mask: str) -> str:
    """Convert a hex netmask (e.g. 0xffffff00) to dotted decimal."""
    val = int(hex_mask, 16)
    return f"{(val >> 24) & 0xFF}.{(val >> 16) & 0xFF}.{(val >> 8) & 0xFF}.{val & 0xFF}"


def _netmask_to_prefixlen(mask: str) -> int:
    """Convert a dotted-decimal subnet mask to CIDR prefix length."""
    parts = mask.split(".")
    bits = 0
    for part in parts:
        bits = (bits << 8) | int(part)
    return bin(bits).count("1")


@tool
def get_network_interfaces() -> dict[str, Any]:
    """Read local network interface configuration.

    Returns interface names, IP addresses, MAC addresses, CIDR notation,
    MTU, and link state for all interfaces on this host. Works on Linux,
    macOS, and Windows.
    """
    platform = get_platform()

    cmd = get_platform_command("interfaces")
    if not cmd:
        raise RuntimeError(f"No interfaces command available for platform: {platform}")

    result = run_command(cmd)
    if result.return_code != 0:
        raise RuntimeError(f"Interfaces command failed (rc={result.return_code}): {result.stderr}")

    if platform == "linux":
        return _parse_linux_json(result.stdout)
    if platform == "darwin":
        return _parse_darwin(result.stdout)
    if platform == "win32":
        return _parse_win32(result.stdout)
    raise RuntimeError(f"No parser available for platform: {platform}")


def _parse_linux_json(output: str) -> dict[str, Any]:
    """Parse `ip -j addr show` JSON output."""
    interfaces: list[dict[str, Any]] = []
    for item in json.loads(output):
        flags = item.get("flags", [])
        iface: dict[str, Any] = {
            "name": item.get("ifname", ""),
            "mac": item.get("address", ""),
            "mtu": item.get("mtu"),
            "is_up": "UP" in flags,
            "is_loopback": "LOOPBACK" in flags,
        }

        # Take the first IPv4 address. Multiple addresses per interface are
        # rare and the LLM is better served with one canonical value.
        for addr in item.get("addr_info", []):
            if addr.get("family") == "inet":
                prefixlen = addr.get("prefixlen", 0)
                iface["ip"] = addr.get("local", "")
                iface["cidr"] = f"{addr.get('local', '')}/{prefixlen}"
                iface["subnet_mask"] = _cidr_from_prefixlen(prefixlen)
                iface["broadcast"] = addr.get("broadcast")
                break

        interfaces.append(iface)

    return {"interfaces": interfaces, "count": len(interfaces)}


def _parse_darwin(output: str) -> dict[str, Any]:
    """Parse macOS `ifconfig` output.

    Each interface block starts with a non-indented header like
    ``en0: flags=8863<UP,...> mtu 1500`` and indented lines below carry
    addresses and details.
    """
    interfaces: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    header_re = re.compile(r"^(\S+):\s+flags=\d+<([^>]*)>\s+mtu\s+(\d+)")
    ether_re = re.compile(r"^\s+ether\s+([0-9a-fA-F:]+)")
    inet_re = re.compile(
        r"^\s+inet\s+(\d+\.\d+\.\d+\.\d+)\s+netmask\s+(0x[0-9a-fA-F]+)"
        r"(?:\s+broadcast\s+(\d+\.\d+\.\d+\.\d+))?"
    )

    for line in output.splitlines():
        header_match = header_re.match(line)
        if header_match:
            if current is not None:
                interfaces.append(current)
            flags = header_match.group(2).split(",")
            current = {
                "name": header_match.group(1),
                "mtu": int(header_match.group(3)),
                "is_up": "UP" in flags,
                "is_loopback": "LOOPBACK" in flags,
            }
            continue

        if current is None:
            continue

        ether_match = ether_re.match(line)
        if ether_match:
            current["mac"] = ether_match.group(1)
            continue

        inet_match = inet_re.match(line)
        if inet_match:
            ip_addr = inet_match.group(1)
            subnet_mask = _netmask_hex_to_dotted(inet_match.group(2))
            prefixlen = _netmask_to_prefixlen(subnet_mask)
            current["ip"] = ip_addr
            current["subnet_mask"] = subnet_mask
            current["cidr"] = f"{ip_addr}/{prefixlen}"
            if inet_match.group(3):
                current["broadcast"] = inet_match.group(3)

    if current is not None:
        interfaces.append(current)

    return {"interfaces": interfaces, "count": len(interfaces)}


def _parse_win32(output: str) -> dict[str, Any]:
    """Parse Windows `ipconfig /all` output."""
    interfaces: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    adapter_re = re.compile(r"^(\S.*)\s+adapter\s+(.+):\s*$")
    kv_re = re.compile(r"^\s+(.+?)\s*[\.\s]*:\s+(.+)$")
    media_disconnected_re = re.compile(
        r"^\s+Media State\s*[\.\s]*:\s+Media disconnected", re.IGNORECASE
    )

    disconnected = False

    for line in output.splitlines():
        adapter_match = adapter_re.match(line)
        if adapter_match:
            if current is not None:
                interfaces.append(current)
            adapter_type = adapter_match.group(1).strip()
            adapter_name = adapter_match.group(2).strip()
            current = {
                "name": adapter_name,
                "is_up": True,
                "is_loopback": "loopback" in adapter_type.lower()
                or "loopback" in adapter_name.lower(),
            }
            disconnected = False
            continue

        if current is None:
            continue

        if media_disconnected_re.match(line):
            current["is_up"] = False
            disconnected = True
            continue

        kv_match = kv_re.match(line)
        if not kv_match:
            continue

        key = kv_match.group(1).strip().rstrip(".")
        value = kv_match.group(2).strip()

        if "Physical Address" in key:
            current["mac"] = value.replace("-", ":")
        elif "IPv4 Address" in key and not disconnected:
            # Windows appends "(Preferred)" or similar — strip it.
            current["ip"] = re.sub(r"\(.*\)", "", value).strip()
        elif "Subnet Mask" in key and not disconnected:
            current["subnet_mask"] = value
            if "ip" in current:
                prefixlen = _netmask_to_prefixlen(value)
                current["cidr"] = f"{current['ip']}/{prefixlen}"

    if current is not None:
        interfaces.append(current)

    return {"interfaces": interfaces, "count": len(interfaces)}
