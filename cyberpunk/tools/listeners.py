"""Listening services tool: enumerates TCP listen sockets on all platforms."""

from __future__ import annotations

import re
from typing import Any

from langchain_core.tools import tool

from cyberpunk.utils.system import get_platform, get_platform_command, run_command

CATEGORY = "passive"


@tool
def get_listening_services() -> dict[str, Any]:
    """Enumerate TCP services listening on this host.

    Returns each listening socket with its port, bind address, protocol,
    owning PID, and process name when available. Works on Linux, macOS,
    and Windows.
    """
    platform = get_platform()

    cmd = get_platform_command("listening_services")
    if not cmd:
        raise RuntimeError(f"No listeners command available for platform: {platform}")

    result = run_command(cmd)
    if result.return_code != 0:
        raise RuntimeError(f"Listeners command failed (rc={result.return_code}): {result.stderr}")

    if platform == "linux":
        return _parse_linux(result.stdout)
    if platform == "darwin":
        return _parse_darwin(result.stdout)
    if platform == "win32":
        return _parse_win32(result.stdout)
    raise RuntimeError(f"No parser available for platform: {platform}")


_SS_LISTEN = re.compile(
    r"^LISTEN\s+\d+\s+\d+\s+(\S+)\s+\S+(?:\s+(.*))?$",
)
_SS_PROC = re.compile(r'"([^"]+)",pid=(\d+)')


def _split_addr_port(raw: str) -> tuple[str, str]:
    """Split an address:port string, tolerating IPv6 brackets and trailing scope ids."""
    # ``ss`` occasionally suffixes the bind address with ``%ifname`` (e.g.
    # ``127.0.0.53%lo:53``). Strip the scope — but only the scope token, not
    # the trailing port — before splitting host from port.
    addr_core = re.sub(r"%[^:\]]+", "", raw)
    if addr_core.startswith("["):
        host, _, port = addr_core.rpartition("]:")
        return (host.lstrip("["), port)
    host, _, port = addr_core.rpartition(":")
    return (host, port)


def _parse_linux(output: str) -> dict[str, Any]:
    """Parse `ss -tlnp` output."""
    entries: list[dict[str, Any]] = []
    for line in output.splitlines():
        m = _SS_LISTEN.match(line.strip())
        if not m:
            continue
        local, proc = m.groups()
        addr, port = _split_addr_port(local)

        pid: int | None = None
        process: str | None = None
        if proc:
            p = _SS_PROC.search(proc)
            if p:
                process = p.group(1)
                pid = int(p.group(2))

        entries.append(
            {
                "protocol": "tcp",
                "address": addr,
                "port": port,
                "pid": pid,
                "process": process,
            }
        )
    return {"listeners": entries, "count": len(entries)}


_LSOF_LINE = re.compile(
    r"^(\S+)\s+(\d+)\s+\S+\s+\S+\s+(IPv\d)\s+\S+\s+\S+\s+\S+\s+(\S+)\s+\(LISTEN\)",
)


def _parse_darwin(output: str) -> dict[str, Any]:
    """Parse macOS `lsof -iTCP -sTCP:LISTEN` output."""
    entries: list[dict[str, Any]] = []
    for line in output.splitlines():
        m = _LSOF_LINE.match(line)
        if not m:
            continue
        process, pid, _family, name = m.groups()

        # ``name`` looks like ``*:ssh`` or ``localhost:ipp``. Keep it simple —
        # the service name (``ssh``, ``ipp``) is more useful to the LLM than
        # the numeric port, which ``lsof`` only emits for unknown services.
        addr, _, port = name.rpartition(":")
        entries.append(
            {
                "protocol": "tcp",
                "address": addr or "*",
                "port": port,
                "pid": int(pid),
                "process": process,
            }
        )
    return {"listeners": entries, "count": len(entries)}


_WIN_LISTEN = re.compile(r"^\s+TCP\s+(\S+)\s+\S+\s+LISTENING\s+(\d+)\s*$")


def _parse_win32(output: str) -> dict[str, Any]:
    """Parse `netstat -ano -p TCP` output, keeping only LISTENING rows."""
    entries: list[dict[str, Any]] = []
    for line in output.splitlines():
        m = _WIN_LISTEN.match(line)
        if not m:
            continue
        local, pid = m.groups()
        addr, port = _split_addr_port(local)
        entries.append(
            {
                "protocol": "tcp",
                "address": addr,
                "port": port,
                "pid": int(pid),
            }
        )
    return {"listeners": entries, "count": len(entries)}
