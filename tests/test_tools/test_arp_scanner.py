"""Tests for the ARP table tool — all 3 platforms."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from cyberpunk.tools.arp_scanner import get_arp_table
from cyberpunk.utils.system import CommandResult
from tests.conftest import load_fixture


def _fake_result(stdout: str) -> CommandResult:
    return CommandResult(stdout=stdout, return_code=0, execution_time_ms=10.0)


def _fake_fail() -> CommandResult:
    return CommandResult(stderr="Command not found: ip", return_code=-1, execution_time_ms=1.0)


def _linux_platform_command(key: str) -> list[str] | None:
    cmds: dict[str, list[str]] = {
        "arp_table_json": ["ip", "-j", "neigh", "show"],
        "arp_table": ["ip", "neigh", "show"],
    }
    return cmds.get(key)


class TestArpTableLinuxJson:
    """Test ARP parsing against Linux `ip -j neigh show` JSON output."""

    def test_parse_entries(self) -> None:
        fixture = load_fixture("linux/ip_neigh.json")

        with (
            patch("cyberpunk.tools.arp_scanner.get_platform", return_value="linux"),
            patch(
                "cyberpunk.tools.arp_scanner.get_platform_command",
                side_effect=_linux_platform_command,
            ),
            patch(
                "cyberpunk.tools.arp_scanner.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_arp_table.invoke({})

        assert result["count"] == 8  # FAILED entry excluded
        assert result["entries"][0]["ip"] == "192.168.1.1"
        assert result["entries"][0]["mac"] == "aa:bb:cc:dd:ee:01"

    def test_all_entries_have_required_fields(self) -> None:
        fixture = load_fixture("linux/ip_neigh.json")

        with (
            patch("cyberpunk.tools.arp_scanner.get_platform", return_value="linux"),
            patch(
                "cyberpunk.tools.arp_scanner.get_platform_command",
                side_effect=_linux_platform_command,
            ),
            patch(
                "cyberpunk.tools.arp_scanner.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_arp_table.invoke({})

        for entry in result["entries"]:
            assert "ip" in entry
            assert "mac" in entry
            assert "interface" in entry


class TestArpTableLinuxText:
    """Test ARP parsing against Linux `ip neigh show` text output."""

    def test_parse_entries(self) -> None:
        fixture = load_fixture("linux/ip_neigh.txt")

        def mock_run(cmd: list[str], **kwargs: object) -> CommandResult:
            if "-j" in cmd:
                return _fake_fail()
            return _fake_result(fixture)

        with (
            patch("cyberpunk.tools.arp_scanner.get_platform", return_value="linux"),
            patch("cyberpunk.tools.arp_scanner.run_command", side_effect=mock_run),
            patch(
                "cyberpunk.tools.arp_scanner.get_platform_command",
                side_effect=_linux_platform_command,
            ),
        ):
            result = get_arp_table.invoke({})

        assert result["count"] == 8  # FAILED line has no lladdr, skipped
        assert result["entries"][0]["ip"] == "192.168.1.1"


class TestArpTableDarwin:
    """Test ARP parsing against macOS `arp -a` output."""

    def test_parse_entries(self) -> None:
        fixture = load_fixture("darwin/arp_a.txt")

        with (
            patch("cyberpunk.tools.arp_scanner.get_platform", return_value="darwin"),
            patch("cyberpunk.tools.arp_scanner.get_platform_command", return_value=["arp", "-a"]),
            patch(
                "cyberpunk.tools.arp_scanner.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_arp_table.invoke({})

        # Broadcast ff:ff:ff:ff:ff:ff still shows up — darwin parser doesn't filter it
        assert result["count"] == 6
        assert result["entries"][0]["ip"] == "192.168.1.1"
        assert result["entries"][0]["interface"] == "en0"


class TestArpTableWin32:
    """Test ARP parsing against Windows `arp -a` output."""

    def test_parse_entries(self) -> None:
        fixture = load_fixture("win32/arp_a.txt")

        with (
            patch("cyberpunk.tools.arp_scanner.get_platform", return_value="win32"),
            patch("cyberpunk.tools.arp_scanner.get_platform_command", return_value=["arp", "-a"]),
            patch(
                "cyberpunk.tools.arp_scanner.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_arp_table.invoke({})

        # ff-ff-ff-ff-ff-ff broadcast is filtered, 224.x multicast is kept
        assert result["count"] == 6
        assert result["entries"][0]["ip"] == "192.168.1.1"
        # MAC should be normalized to colon format
        assert result["entries"][0]["mac"] == "aa:bb:cc:dd:ee:01"

    def test_interface_captured(self) -> None:
        fixture = load_fixture("win32/arp_a.txt")

        with (
            patch("cyberpunk.tools.arp_scanner.get_platform", return_value="win32"),
            patch("cyberpunk.tools.arp_scanner.get_platform_command", return_value=["arp", "-a"]),
            patch(
                "cyberpunk.tools.arp_scanner.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_arp_table.invoke({})

        assert result["entries"][0]["interface"] == "192.168.1.5"


class TestArpTableCommandNotFound:
    """Test graceful handling when the ARP command is not available."""

    def test_raises_runtime_error(self) -> None:
        with (
            patch("cyberpunk.tools.arp_scanner.get_platform", return_value="linux"),
            patch("cyberpunk.tools.arp_scanner.run_command", return_value=_fake_fail()),
            patch(
                "cyberpunk.tools.arp_scanner.get_platform_command",
                side_effect=_linux_platform_command,
            ),
            pytest.raises(RuntimeError),
        ):
            get_arp_table.invoke({})
