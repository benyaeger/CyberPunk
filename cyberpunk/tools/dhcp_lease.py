"""DHCP lease tool: extracts the current DHCP lease details per platform."""

from __future__ import annotations

import re
from typing import Any

from langchain_core.tools import tool

from cyberpunk.utils.system import get_platform, run_command

CATEGORY = "passive"


@tool
def get_dhcp_lease(interface: str | None = None) -> dict[str, Any]:
    """Read the current DHCP lease information.

    On Linux, parses ``nmcli -t dev show`` (covers all managed interfaces).
    On macOS, parses ``ipconfig getpacket <interface>`` (defaults to ``en0``
    if no interface is given). On Windows, parses ``ipconfig /all`` and
    extracts DHCP-related fields per adapter.

    Args:
        interface: Optional interface name. On macOS this selects the
            interface queried by ``ipconfig getpacket``. On Linux/Windows
            the argument is accepted for API symmetry but the underlying
            commands already report all interfaces.

    Returns the detected DHCP server, offered gateway, DNS servers, lease
    time, and subnet mask when available.
    """
    platform = get_platform()

    if platform == "linux":
        result = run_command(["nmcli", "-t", "dev", "show"])
        if result.return_code != 0:
            raise RuntimeError(f"nmcli failed (rc={result.return_code}): {result.stderr}")
        return _parse_nmcli(result.stdout)

    if platform == "darwin":
        iface = interface or "en0"
        result = run_command(["ipconfig", "getpacket", iface])
        if result.return_code != 0:
            raise RuntimeError(
                f"ipconfig getpacket failed (rc={result.return_code}): {result.stderr}"
            )
        return _parse_darwin(result.stdout, iface)

    if platform == "win32":
        result = run_command(["ipconfig", "/all"])
        if result.return_code != 0:
            raise RuntimeError(f"ipconfig failed (rc={result.return_code}): {result.stderr}")
        return _parse_win32(result.stdout)

    raise RuntimeError(f"No parser available for platform: {platform}")


_NMCLI_DEVICE = re.compile(r"^GENERAL\.DEVICE:(.+)$")
_NMCLI_OPTION = re.compile(r"^DHCP4\.OPTION\[\d+\]:(\S+)\s*=\s*(.+)$")


def _parse_nmcli(output: str) -> dict[str, Any]:
    """Parse `nmcli -t dev show` output, grouping DHCP options per device."""
    leases: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def flush() -> None:
        if current is not None and current.get("dhcp_server"):
            leases.append(current)

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            current = None
            continue

        dev_match = _NMCLI_DEVICE.match(line)
        if dev_match:
            flush()
            current = {"interface": dev_match.group(1).strip(), "options": {}}
            continue

        if current is None:
            continue

        opt_match = _NMCLI_OPTION.match(line)
        if not opt_match:
            continue

        key, value = opt_match.group(1), opt_match.group(2).strip()
        current["options"][key] = value

        if key == "dhcp_server_identifier":
            current["dhcp_server"] = value
        elif key == "routers":
            current["gateway"] = value.split()[0]
        elif key == "domain_name_servers":
            current["dns_servers"] = value.split()
        elif key == "dhcp_lease_time":
            current["lease_time_seconds"] = int(value)
        elif key == "subnet_mask":
            current["subnet_mask"] = value
        elif key == "domain_name":
            current["domain_name"] = value

    flush()
    return {"leases": leases, "count": len(leases)}


_DARWIN_KV = re.compile(r"^(\w+)(?:\s+\([^)]+\))?\s*[:=]\s*(.+)$")


def _parse_darwin(output: str, interface: str) -> dict[str, Any]:
    """Parse `ipconfig getpacket <iface>` output."""
    lease: dict[str, Any] = {"interface": interface}

    for raw_line in output.splitlines():
        line = raw_line.strip()
        m = _DARWIN_KV.match(line)
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip()

        if key == "yiaddr":
            lease["ip_address"] = value
        elif key == "server_identifier":
            lease["dhcp_server"] = value
        elif key == "lease_time":
            lease["lease_time_seconds"] = int(value, 16) if value.startswith("0x") else int(value)
        elif key == "subnet_mask":
            lease["subnet_mask"] = value
        elif key == "router":
            lease["gateway"] = value.strip("{}").split(",")[0].strip()
        elif key == "domain_name_server":
            raw = value.strip("{}")
            lease["dns_servers"] = [ip.strip() for ip in raw.split(",") if ip.strip()]
        elif key == "domain_name":
            lease["domain_name"] = value

    has_lease = "dhcp_server" in lease
    return {"leases": [lease] if has_lease else [], "count": 1 if has_lease else 0}


_WIN_ADAPTER = re.compile(r"^(\S.*)\s+adapter\s+(.+):\s*$")
_WIN_FIELD = re.compile(r"^\s+([^.]+?)[\s\.]*:\s*(.+)$")


def _parse_win32(output: str) -> dict[str, Any]:
    """Parse `ipconfig /all` for DHCP fields per adapter."""
    leases: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def flush() -> None:
        if current is not None and current.get("dhcp_enabled") and current.get("dhcp_server"):
            leases.append(current)

    for line in output.splitlines():
        adapter_match = _WIN_ADAPTER.match(line)
        if adapter_match:
            flush()
            current = {"interface": adapter_match.group(2).strip()}
            continue

        if current is None:
            continue

        field_match = _WIN_FIELD.match(line)
        if not field_match:
            continue

        key = field_match.group(1).strip().rstrip(".")
        value = field_match.group(2).strip()

        if key == "DHCP Enabled":
            current["dhcp_enabled"] = value.lower() == "yes"
        elif key == "DHCP Server":
            current["dhcp_server"] = value
        elif key == "Default Gateway" and value:
            current["gateway"] = value
        elif key == "Subnet Mask":
            current["subnet_mask"] = value
        elif key == "DNS Servers":
            current["dns_servers"] = [value]
        elif key == "Lease Obtained":
            current["lease_obtained"] = value
        elif key == "Lease Expires":
            current["lease_expires"] = value

    flush()
    return {"leases": leases, "count": len(leases)}
