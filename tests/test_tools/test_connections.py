"""Tests for the active connections tool -- all 3 platforms."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from cyberpunk.tools.connections import get_active_connections
from cyberpunk.utils.system import CommandResult
from tests.conftest import load_fixture


def _fake_result(stdout: str) -> CommandResult:
    return CommandResult(stdout=stdout, return_code=0, execution_time_ms=10.0)


def _fake_fail() -> CommandResult:
    return CommandResult(stderr="Command not found: ss", return_code=-1, execution_time_ms=1.0)


class TestConnectionsLinux:
    def test_parse_entries(self) -> None:
        fixture = load_fixture("linux/ss_tunap.txt")
        with (
            patch("cyberpunk.tools.connections.get_platform", return_value="linux"),
            patch(
                "cyberpunk.tools.connections.get_platform_command",
                return_value=["ss", "-tunap"],
            ),
            patch(
                "cyberpunk.tools.connections.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_active_connections.invoke({})

        assert result["count"] == 6

    def test_established_entry(self) -> None:
        fixture = load_fixture("linux/ss_tunap.txt")
        with (
            patch("cyberpunk.tools.connections.get_platform", return_value="linux"),
            patch(
                "cyberpunk.tools.connections.get_platform_command",
                return_value=["ss", "-tunap"],
            ),
            patch(
                "cyberpunk.tools.connections.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_active_connections.invoke({})

        estab = next(c for c in result["connections"] if c["state"] == "ESTAB")
        assert estab["protocol"] == "tcp"
        assert estab["local_addr"] == "192.168.1.100"
        assert estab["local_port"] == "52341"
        assert estab["remote_addr"] == "93.184.216.34"
        assert estab["remote_port"] == "443"
        assert estab["process"] == "firefox"
        assert estab["pid"] == 1234

    def test_udp_entry(self) -> None:
        fixture = load_fixture("linux/ss_tunap.txt")
        with (
            patch("cyberpunk.tools.connections.get_platform", return_value="linux"),
            patch(
                "cyberpunk.tools.connections.get_platform_command",
                return_value=["ss", "-tunap"],
            ),
            patch(
                "cyberpunk.tools.connections.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_active_connections.invoke({})

        udps = [c for c in result["connections"] if c["protocol"] == "udp"]
        assert len(udps) == 2


class TestConnectionsDarwin:
    def test_parse_entries(self) -> None:
        fixture = load_fixture("darwin/netstat_an_tcp.txt")
        with (
            patch("cyberpunk.tools.connections.get_platform", return_value="darwin"),
            patch(
                "cyberpunk.tools.connections.get_platform_command",
                return_value=["netstat", "-an", "-p", "tcp"],
            ),
            patch(
                "cyberpunk.tools.connections.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_active_connections.invoke({})

        assert result["count"] == 5

    def test_listen_entry(self) -> None:
        fixture = load_fixture("darwin/netstat_an_tcp.txt")
        with (
            patch("cyberpunk.tools.connections.get_platform", return_value="darwin"),
            patch(
                "cyberpunk.tools.connections.get_platform_command",
                return_value=["netstat", "-an", "-p", "tcp"],
            ),
            patch(
                "cyberpunk.tools.connections.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_active_connections.invoke({})

        listens = [c for c in result["connections"] if c["state"] == "LISTEN"]
        assert len(listens) == 3
        assert any(c["local_port"] == "22" for c in listens)

    def test_established_entry(self) -> None:
        fixture = load_fixture("darwin/netstat_an_tcp.txt")
        with (
            patch("cyberpunk.tools.connections.get_platform", return_value="darwin"),
            patch(
                "cyberpunk.tools.connections.get_platform_command",
                return_value=["netstat", "-an", "-p", "tcp"],
            ),
            patch(
                "cyberpunk.tools.connections.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_active_connections.invoke({})

        estab = next(c for c in result["connections"] if c["state"] == "ESTABLISHED")
        assert estab["local_addr"] == "192.168.1.100"
        assert estab["local_port"] == "52341"
        assert estab["remote_addr"] == "93.184.216.34"
        assert estab["remote_port"] == "443"


class TestConnectionsWin32:
    def test_parse_entries(self) -> None:
        fixture = load_fixture("win32/netstat_ano.txt")
        with (
            patch("cyberpunk.tools.connections.get_platform", return_value="win32"),
            patch(
                "cyberpunk.tools.connections.get_platform_command",
                return_value=["netstat", "-ano"],
            ),
            patch(
                "cyberpunk.tools.connections.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_active_connections.invoke({})

        assert result["count"] == 7

    def test_tcp_listening(self) -> None:
        fixture = load_fixture("win32/netstat_ano.txt")
        with (
            patch("cyberpunk.tools.connections.get_platform", return_value="win32"),
            patch(
                "cyberpunk.tools.connections.get_platform_command",
                return_value=["netstat", "-ano"],
            ),
            patch(
                "cyberpunk.tools.connections.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_active_connections.invoke({})

        listens = [c for c in result["connections"] if c["state"] == "LISTENING"]
        assert len(listens) == 3
        assert any(c["local_port"] == "135" for c in listens)

    def test_udp_no_state(self) -> None:
        fixture = load_fixture("win32/netstat_ano.txt")
        with (
            patch("cyberpunk.tools.connections.get_platform", return_value="win32"),
            patch(
                "cyberpunk.tools.connections.get_platform_command",
                return_value=["netstat", "-ano"],
            ),
            patch(
                "cyberpunk.tools.connections.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_active_connections.invoke({})

        udps = [c for c in result["connections"] if c["protocol"] == "udp"]
        assert len(udps) == 2
        assert all(u["state"] is None for u in udps)
        assert any(u["pid"] == 567 for u in udps)


class TestConnectionsFailure:
    def test_raises_runtime_error(self) -> None:
        with (
            patch("cyberpunk.tools.connections.get_platform", return_value="linux"),
            patch(
                "cyberpunk.tools.connections.get_platform_command",
                return_value=["ss", "-tunap"],
            ),
            patch(
                "cyberpunk.tools.connections.run_command",
                return_value=_fake_fail(),
            ),
            pytest.raises(RuntimeError),
        ):
            get_active_connections.invoke({})
