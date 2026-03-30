"""System utilities: command execution, platform detection."""

from __future__ import annotations

import subprocess
import sys
import time
from typing import Any

from pydantic import BaseModel


class CommandResult(BaseModel):
    """Result of a subprocess execution."""

    stdout: str = ""
    stderr: str = ""
    return_code: int = 0
    execution_time_ms: float = 0.0


def get_platform() -> str:
    """Return the current platform identifier: linux, darwin, or win32."""
    return sys.platform


PLATFORM_COMMANDS: dict[str, dict[str, list[str]]] = {
    "arp_table": {
        "linux": ["ip", "neigh", "show"],
        "darwin": ["arp", "-a"],
        "win32": ["arp", "-a"],
    },
    "arp_table_json": {
        "linux": ["ip", "-j", "neigh", "show"],
    },
    "interfaces": {
        "linux": ["ip", "-j", "addr", "show"],
        "darwin": ["ifconfig"],
        "win32": ["ipconfig", "/all"],
    },
    "routing_table": {
        "linux": ["ip", "-j", "route", "show"],
        "darwin": ["netstat", "-rn"],
        "win32": ["route", "print"],
    },
    "active_connections": {
        "linux": ["ss", "-tunap"],
        "darwin": ["netstat", "-an", "-p", "tcp"],
        "win32": ["netstat", "-ano"],
    },
    "listening_services": {
        "linux": ["ss", "-tlnp"],
        "darwin": ["lsof", "-iTCP", "-sTCP:LISTEN"],
        "win32": ["netstat", "-ano", "-p", "TCP"],
    },
    "dns_config": {
        "linux": ["cat", "/etc/resolv.conf"],
        "darwin": ["cat", "/etc/resolv.conf"],
        "win32": ["ipconfig", "/all"],
    },
}


def run_command(
    command: list[str],
    timeout: int = 30,
    **kwargs: Any,
) -> CommandResult:
    """Execute a subprocess command safely.

    Args:
        command: Command as a list of strings (shell=False).
        timeout: Max execution time in seconds.

    Returns:
        CommandResult with stdout, stderr, return code, and timing.
    """
    start = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            **kwargs,
        )
        elapsed = (time.perf_counter() - start) * 1000
        return CommandResult(
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.returncode,
            execution_time_ms=elapsed,
        )
    except FileNotFoundError:
        elapsed = (time.perf_counter() - start) * 1000
        return CommandResult(
            stderr=f"Command not found: {command[0]}",
            return_code=-1,
            execution_time_ms=elapsed,
        )
    except subprocess.TimeoutExpired:
        elapsed = (time.perf_counter() - start) * 1000
        return CommandResult(
            stderr=f"Command timed out after {timeout}s: {' '.join(command)}",
            return_code=-2,
            execution_time_ms=elapsed,
        )


def get_platform_command(tool_key: str) -> list[str] | None:
    """Get the platform-specific command for a tool key.

    Returns:
        Command list, or None if not available on this platform.
    """
    platform = get_platform()
    commands = PLATFORM_COMMANDS.get(tool_key, {})
    return commands.get(platform)
