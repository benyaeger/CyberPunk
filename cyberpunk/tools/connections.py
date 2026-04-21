"""Active connections tool: reads the open socket table on all platforms."""

from __future__ import annotations

import re
from typing import Any

from langchain_core.tools import tool

from cyberpunk.utils.system import get_platform, get_platform_command, run_command

CATEGORY = "passive"


@tool
def get_active_connections() -> dict[str, Any]:
    """Read active network connections from the local socket table.

    Returns entries with protocol, local address/port, remote address/port,
    connection state, and owning PID (when available). Works on Linux,
    macOS, and Windows.
    """
    platform = get_platform()

    cmd = get_platform_command("active_connections")
    if not cmd:
        raise RuntimeError(f"No connections command available for platform: {platform}")

    result = run_command(cmd)
    if result.return_code != 0:
        raise RuntimeError(f"Connections command failed (rc={result.return_code}): {result.stderr}")

    if platform == "linux":
        return _parse_linux(result.stdout)
    if platform == "darwin":
        return _parse_darwin(result.stdout)
    if platform == "win32":
        return _parse_win32(result.stdout)
    raise RuntimeError(f"No parser available for platform: {platform}")


_SS_LINE = re.compile(
    r"^(tcp|udp)\s+(\S+)\s+\d+\s+\d+\s+(\S+)\s+(\S+)(?:\s+(.*))?$",
    re.IGNORECASE,
)
_SS_PROC = re.compile(r'"([^"]+)",pid=(\d+)')


def _split_addr_port(raw: str) -> tuple[str, str]:
    """Split an address:port string, tolerating IPv6 brackets and '*' wildcards."""
    if raw in ("*", "*:*"):
        return ("*", "*")
    if raw.startswith("["):
        host, _, port = raw.rpartition("]:")
        return (host.lstrip("["), port)
    host, _, port = raw.rpartition(":")
    return (host, port) if port else (raw, "")


def _parse_linux(output: str) -> dict[str, Any]:
    """Parse `ss -tunap` output."""
    entries: list[dict[str, Any]] = []
    for line in output.splitlines():
        m = _SS_LINE.match(line.strip())
        if not m:
            continue
        proto, state, local, peer, proc = m.groups()
        local_addr, local_port = _split_addr_port(local)
        peer_addr, peer_port = _split_addr_port(peer)

        pid: int | None = None
        process: str | None = None
        if proc:
            p = _SS_PROC.search(proc)
            if p:
                process = p.group(1)
                pid = int(p.group(2))

        entries.append(
            {
                "protocol": proto.lower(),
                "state": state.upper(),
                "local_addr": local_addr,
                "local_port": local_port,
                "remote_addr": peer_addr,
                "remote_port": peer_port,
                "pid": pid,
                "process": process,
            }
        )
    return {"connections": entries, "count": len(entries)}


_DARWIN_LINE = re.compile(r"^(tcp\d*|udp\d*)\s+\d+\s+\d+\s+(\S+)\s+(\S+)(?:\s+(\S+))?\s*$")


def _split_darwin_addr(raw: str) -> tuple[str, str]:
    """macOS uses ``host.port`` (dot) instead of ``host:port``."""
    if raw == "*.*":
        return ("*", "*")
    host, _, port = raw.rpartition(".")
    return (host if host else raw, port)


def _parse_darwin(output: str) -> dict[str, Any]:
    """Parse macOS `netstat -an -p tcp` output."""
    entries: list[dict[str, Any]] = []
    for line in output.splitlines():
        m = _DARWIN_LINE.match(line)
        if not m:
            continue
        proto, local, foreign, state = m.groups()
        local_addr, local_port = _split_darwin_addr(local)
        remote_addr, remote_port = _split_darwin_addr(foreign)

        # netstat's "proto" column carries the IP family too (tcp4/tcp6); the
        # LLM only cares about transport, so strip the family suffix.
        transport = "tcp" if proto.startswith("tcp") else "udp"

        entries.append(
            {
                "protocol": transport,
                "state": (state or "").upper() or None,
                "local_addr": local_addr,
                "local_port": local_port,
                "remote_addr": remote_addr,
                "remote_port": remote_port,
            }
        )
    return {"connections": entries, "count": len(entries)}


_WIN_LINE = re.compile(r"^\s+(TCP|UDP)\s+(\S+)\s+(\S+)(?:\s+(\S+))?\s+(\d+)\s*$")


def _parse_win32(output: str) -> dict[str, Any]:
    """Parse Windows `netstat -ano` output.

    TCP rows have a state column; UDP rows omit it. The regex makes that
    field optional and the PID always sits at the end of the line.
    """
    entries: list[dict[str, Any]] = []
    for line in output.splitlines():
        m = _WIN_LINE.match(line)
        if not m:
            continue
        proto, local, foreign, state_or_pid, pid_str = m.groups()
        # If state is missing (UDP), state_or_pid is actually the PID's
        # preceding whitespace-captured token and pid_str holds the PID.
        state = state_or_pid if proto == "TCP" else None
        pid = int(pid_str)

        local_addr, local_port = _split_addr_port(local)
        remote_addr, remote_port = _split_addr_port(foreign)

        entries.append(
            {
                "protocol": proto.lower(),
                "state": state,
                "local_addr": local_addr,
                "local_port": local_port,
                "remote_addr": remote_addr,
                "remote_port": remote_port,
                "pid": pid,
            }
        )
    return {"connections": entries, "count": len(entries)}
