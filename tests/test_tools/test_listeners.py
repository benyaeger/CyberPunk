"""Tests for the listening services tool -- all 3 platforms."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from cyberpunk.tools.listeners import get_listening_services
from cyberpunk.utils.system import CommandResult
from tests.conftest import load_fixture


def _fake_result(stdout: str) -> CommandResult:
    return CommandResult(stdout=stdout, return_code=0, execution_time_ms=10.0)


def _fake_fail() -> CommandResult:
    return CommandResult(stderr="not found", return_code=-1, execution_time_ms=1.0)


class TestListenersLinux:
    def test_parse_entries(self) -> None:
        fixture = load_fixture("linux/ss_tlnp.txt")
        with (
            patch("cyberpunk.tools.listeners.get_platform", return_value="linux"),
            patch(
                "cyberpunk.tools.listeners.get_platform_command",
                return_value=["ss", "-tlnp"],
            ),
            patch(
                "cyberpunk.tools.listeners.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_listening_services.invoke({})

        assert result["count"] == 4

    def test_sshd_entry(self) -> None:
        fixture = load_fixture("linux/ss_tlnp.txt")
        with (
            patch("cyberpunk.tools.listeners.get_platform", return_value="linux"),
            patch(
                "cyberpunk.tools.listeners.get_platform_command",
                return_value=["ss", "-tlnp"],
            ),
            patch(
                "cyberpunk.tools.listeners.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_listening_services.invoke({})

        sshd = next(
            e for e in result["listeners"] if e["port"] == "22" and e["address"] == "0.0.0.0"
        )
        assert sshd["process"] == "sshd"
        assert sshd["pid"] == 901

    def test_scope_id_stripped(self) -> None:
        fixture = load_fixture("linux/ss_tlnp.txt")
        with (
            patch("cyberpunk.tools.listeners.get_platform", return_value="linux"),
            patch(
                "cyberpunk.tools.listeners.get_platform_command",
                return_value=["ss", "-tlnp"],
            ),
            patch(
                "cyberpunk.tools.listeners.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_listening_services.invoke({})

        resolve = next(e for e in result["listeners"] if e["process"] == "systemd-resolve")
        assert resolve["address"] == "127.0.0.53"
        assert resolve["port"] == "53"


class TestListenersDarwin:
    def test_parse_entries(self) -> None:
        fixture = load_fixture("darwin/lsof_listen.txt")
        with (
            patch("cyberpunk.tools.listeners.get_platform", return_value="darwin"),
            patch(
                "cyberpunk.tools.listeners.get_platform_command",
                return_value=["lsof", "-iTCP", "-sTCP:LISTEN"],
            ),
            patch(
                "cyberpunk.tools.listeners.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_listening_services.invoke({})

        assert result["count"] == 4

    def test_process_and_port(self) -> None:
        fixture = load_fixture("darwin/lsof_listen.txt")
        with (
            patch("cyberpunk.tools.listeners.get_platform", return_value="darwin"),
            patch(
                "cyberpunk.tools.listeners.get_platform_command",
                return_value=["lsof", "-iTCP", "-sTCP:LISTEN"],
            ),
            patch(
                "cyberpunk.tools.listeners.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_listening_services.invoke({})

        rapportd = next(e for e in result["listeners"] if e["process"] == "rapportd")
        assert rapportd["port"] == "49206"
        assert rapportd["pid"] == 542


class TestListenersWin32:
    def test_parse_entries(self) -> None:
        fixture = load_fixture("win32/netstat_listen.txt")
        with (
            patch("cyberpunk.tools.listeners.get_platform", return_value="win32"),
            patch(
                "cyberpunk.tools.listeners.get_platform_command",
                return_value=["netstat", "-ano", "-p", "TCP"],
            ),
            patch(
                "cyberpunk.tools.listeners.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_listening_services.invoke({})

        # Only LISTENING rows; ESTABLISHED is skipped.
        assert result["count"] == 5

    def test_rdp_listener(self) -> None:
        fixture = load_fixture("win32/netstat_listen.txt")
        with (
            patch("cyberpunk.tools.listeners.get_platform", return_value="win32"),
            patch(
                "cyberpunk.tools.listeners.get_platform_command",
                return_value=["netstat", "-ano", "-p", "TCP"],
            ),
            patch(
                "cyberpunk.tools.listeners.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_listening_services.invoke({})

        rdp = next(e for e in result["listeners"] if e["port"] == "3389")
        assert rdp["pid"] == 1520
        assert rdp["address"] == "0.0.0.0"


class TestListenersFailure:
    def test_raises_runtime_error(self) -> None:
        with (
            patch("cyberpunk.tools.listeners.get_platform", return_value="linux"),
            patch(
                "cyberpunk.tools.listeners.get_platform_command",
                return_value=["ss", "-tlnp"],
            ),
            patch(
                "cyberpunk.tools.listeners.run_command",
                return_value=_fake_fail(),
            ),
            pytest.raises(RuntimeError),
        ):
            get_listening_services.invoke({})
