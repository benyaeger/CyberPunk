"""DNS configuration tool: reads system resolver settings on all platforms."""

from __future__ import annotations

import re
from typing import Any

from langchain_core.tools import tool

from cyberpunk.utils.system import get_platform, get_platform_command, run_command

CATEGORY = "passive"


@tool
def get_dns_config() -> dict[str, Any]:
    """Read the system DNS resolver configuration.

    Returns the list of DNS servers, search domains, and resolver options
    from ``/etc/resolv.conf`` (Linux/macOS) or ``ipconfig /all`` (Windows).
    Works on Linux, macOS, and Windows.
    """
    platform = get_platform()

    cmd = get_platform_command("dns_config")
    if not cmd:
        raise RuntimeError(f"No DNS command available for platform: {platform}")

    result = run_command(cmd)
    if result.return_code != 0:
        raise RuntimeError(f"DNS command failed (rc={result.return_code}): {result.stderr}")

    if platform in ("linux", "darwin"):
        return _parse_resolv_conf(result.stdout)
    if platform == "win32":
        return _parse_ipconfig(result.stdout)
    raise RuntimeError(f"No parser available for platform: {platform}")


def _parse_resolv_conf(output: str) -> dict[str, Any]:
    """Parse ``/etc/resolv.conf`` contents."""
    nameservers: list[str] = []
    search: list[str] = []
    options: list[str] = []

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if not parts:
            continue
        directive = parts[0].lower()
        if directive == "nameserver" and len(parts) >= 2:
            nameservers.append(parts[1])
        elif directive == "search":
            search.extend(parts[1:])
        elif directive == "domain" and len(parts) >= 2:
            # ``domain`` is a legacy single-value form of ``search``; merge.
            search.append(parts[1])
        elif directive == "options":
            options.extend(parts[1:])

    return {
        "nameservers": nameservers,
        "search_domains": search,
        "options": options,
    }


_WIN_DNS_LINE = re.compile(r"^\s+DNS Servers[\s\.]*:\s+(\S+)")
_WIN_SUFFIX_LINE = re.compile(r"^\s+Connection-specific DNS Suffix[\s\.]*:\s+(\S+)")
_WIN_CONT_LINE = re.compile(r"^\s{20,}(\S+)\s*$")


def _parse_ipconfig(output: str) -> dict[str, Any]:
    """Parse DNS block out of Windows ``ipconfig /all`` output.

    ``ipconfig`` emits DNS servers as one per line; the first appears on
    ``DNS Servers . . . : <addr>`` and subsequent ones are heavily-indented
    continuation lines. We track a boolean so only lines that follow the
    DNS header get treated as extra nameservers.
    """
    nameservers: list[str] = []
    search: list[str] = []
    in_dns_block = False

    for line in output.splitlines():
        dns_match = _WIN_DNS_LINE.match(line)
        if dns_match:
            value = dns_match.group(1)
            if _looks_like_ip(value):
                nameservers.append(value)
            in_dns_block = True
            continue

        if in_dns_block:
            cont = _WIN_CONT_LINE.match(line)
            if cont and _looks_like_ip(cont.group(1)):
                nameservers.append(cont.group(1))
                continue
            # Any non-continuation line closes the DNS block.
            in_dns_block = False

        suffix_match = _WIN_SUFFIX_LINE.match(line)
        if suffix_match:
            search.append(suffix_match.group(1))

    return {
        "nameservers": nameservers,
        "search_domains": search,
        "options": [],
    }


def _looks_like_ip(value: str) -> bool:
    """Cheap IPv4/IPv6 guard so we don't capture stray suffix text."""
    return bool(re.match(r"^(\d+\.\d+\.\d+\.\d+|[0-9a-fA-F:]+:[0-9a-fA-F:]+)$", value))
