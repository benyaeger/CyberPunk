"""Network interfaces tool: reads local network interfaces on all platforms."""

from __future__ import annotations

import json
import re
from typing import Any

from cyberpunk.models import ToolCategory, ToolDefinition
from cyberpunk.tools import BaseTool
from cyberpunk.utils.system import get_platform, get_platform_command, run_command


def _cidr_from_prefixlen(prefixlen: int) -> str:
    """Convert a prefix length to a subnet mask string.

    Args:
        prefixlen: CIDR prefix length (e.g. 24).

    Returns:
        Dotted-decimal subnet mask (e.g. "255.255.255.0").
    """
    mask = (0xFFFFFFFF << (32 - prefixlen)) & 0xFFFFFFFF
    return f"{(mask >> 24) & 0xFF}.{(mask >> 16) & 0xFF}.{(mask >> 8) & 0xFF}.{mask & 0xFF}"


def _netmask_hex_to_dotted(hex_mask: str) -> str:
    """Convert a hex netmask (e.g. 0xffffff00) to dotted decimal.

    Args:
        hex_mask: Hexadecimal netmask string.

    Returns:
        Dotted-decimal subnet mask.
    """
    val = int(hex_mask, 16)
    return f"{(val >> 24) & 0xFF}.{(val >> 16) & 0xFF}.{(val >> 8) & 0xFF}.{val & 0xFF}"


def _netmask_to_prefixlen(mask: str) -> int:
    """Convert a dotted-decimal subnet mask to CIDR prefix length.

    Args:
        mask: Dotted-decimal subnet mask (e.g. "255.255.255.0").

    Returns:
        CIDR prefix length (e.g. 24).
    """
    parts = mask.split(".")
    bits = 0
    for part in parts:
        bits = (bits << 8) | int(part)
    return bin(bits).count("1")


class NetworkInterfacesTool(BaseTool):
    """Read local network interface configuration."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="get_network_interfaces",
            description=(
                "Read local network interface configuration. "
                "Returns interface names, IP addresses, MAC addresses, "
                "CIDR notation, MTU, and link state for all interfaces."
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
            cmd = get_platform_command("interfaces")
            if cmd:
                result = run_command(cmd)
                if result.return_code == 0 and result.stdout.strip():
                    return self._parse_linux_json(result.stdout)

        # Fall back to text command
        cmd = get_platform_command("interfaces")
        if not cmd:
            raise RuntimeError(f"No interfaces command available for platform: {platform}")

        result = run_command(cmd)
        if result.return_code != 0:
            raise RuntimeError(
                f"Interfaces command failed (rc={result.return_code}): {result.stderr}"
            )

        if platform == "darwin":
            return self._parse_darwin(result.stdout)
        elif platform == "win32":
            return self._parse_win32(result.stdout)
        else:
            raise RuntimeError(f"No parser available for platform: {platform}")

    def _parse_linux_json(self, output: str) -> dict[str, Any]:
        """Parse `ip -j addr show` JSON output."""
        interfaces: list[dict[str, Any]] = []
        for item in json.loads(output):
            flags = item.get("flags", [])
            is_loopback = "LOOPBACK" in flags
            is_up = "UP" in flags

            iface: dict[str, Any] = {
                "name": item.get("ifname", ""),
                "mac": item.get("address", ""),
                "mtu": item.get("mtu"),
                "is_up": is_up,
                "is_loopback": is_loopback,
            }

            # Extract the first IPv4 address from addr_info
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

    def _parse_darwin(self, output: str) -> dict[str, Any]:
        """Parse macOS `ifconfig` output.

        Each interface block starts with a non-whitespace line like:
            en0: flags=8863<UP,...> mtu 1500
        Indented lines contain addresses and other details.
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
                name = header_match.group(1)
                flags_str = header_match.group(2)
                mtu = int(header_match.group(3))
                flags = flags_str.split(",")
                current = {
                    "name": name,
                    "mtu": mtu,
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
                hex_mask = inet_match.group(2)
                broadcast = inet_match.group(3)
                subnet_mask = _netmask_hex_to_dotted(hex_mask)
                prefixlen = _netmask_to_prefixlen(subnet_mask)
                current["ip"] = ip_addr
                current["subnet_mask"] = subnet_mask
                current["cidr"] = f"{ip_addr}/{prefixlen}"
                if broadcast:
                    current["broadcast"] = broadcast

        if current is not None:
            interfaces.append(current)

        return {"interfaces": interfaces, "count": len(interfaces)}

    def _parse_win32(self, output: str) -> dict[str, Any]:
        """Parse Windows `ipconfig /all` output.

        Each adapter block starts with a line like:
            Ethernet adapter Ethernet:
        Followed by indented key-value pairs.
        """
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
                # Strip "(Preferred)" suffix
                ip = re.sub(r"\(.*\)", "", value).strip()
                current["ip"] = ip
            elif "Subnet Mask" in key and not disconnected:
                current["subnet_mask"] = value
                if "ip" in current:
                    prefixlen = _netmask_to_prefixlen(value)
                    current["cidr"] = f"{current['ip']}/{prefixlen}"

        if current is not None:
            interfaces.append(current)

        return {"interfaces": interfaces, "count": len(interfaces)}
