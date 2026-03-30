"""Tests for the ARP table tool — all 3 platforms."""

from __future__ import annotations

from unittest.mock import patch

from tests.conftest import load_fixture

from cyberpunk.tools.arp_scanner import ArpTableTool
from cyberpunk.utils.system import CommandResult


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
        tool = ArpTableTool()

        with (
            patch("cyberpunk.tools.arp_scanner.get_platform", return_value="linux"),
            patch("cyberpunk.tools.arp_scanner.get_platform_command", side_effect=_linux_platform_command),
            patch(
                "cyberpunk.tools.arp_scanner.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = tool.run()

        assert result.success
        assert result.data["count"] == 8  # FAILED entry excluded
        assert result.data["entries"][0]["ip"] == "192.168.1.1"
        assert result.data["entries"][0]["mac"] == "aa:bb:cc:dd:ee:01"

    def test_all_entries_have_required_fields(self) -> None:
        fixture = load_fixture("linux/ip_neigh.json")
        tool = ArpTableTool()

        with (
            patch("cyberpunk.tools.arp_scanner.get_platform", return_value="linux"),
            patch("cyberpunk.tools.arp_scanner.get_platform_command", side_effect=_linux_platform_command),
            patch(
                "cyberpunk.tools.arp_scanner.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = tool.run()

        for entry in result.data["entries"]:
            assert "ip" in entry
            assert "mac" in entry
            assert "interface" in entry


class TestArpTableLinuxText:
    """Test ARP parsing against Linux `ip neigh show` text output."""

    def test_parse_entries(self) -> None:
        fixture = load_fixture("linux/ip_neigh.txt")
        tool = ArpTableTool()

        # Make JSON command fail so it falls back to text
        call_count = 0

        def mock_run(cmd: list[str], **kwargs: object) -> CommandResult:
            nonlocal call_count
            call_count += 1
            if "-j" in cmd:
                return _fake_fail()
            return _fake_result(fixture)

        with (
            patch("cyberpunk.tools.arp_scanner.get_platform", return_value="linux"),
            patch("cyberpunk.tools.arp_scanner.run_command", side_effect=mock_run),
            patch(
                "cyberpunk.tools.arp_scanner.get_platform_command",
                side_effect=lambda k: ["ip", "-j", "neigh", "show"]
                if k == "arp_table_json"
                else ["ip", "neigh", "show"],
            ),
        ):
            result = tool.run()

        assert result.success
        assert result.data["count"] == 8  # FAILED line has no lladdr, skipped
        assert result.data["entries"][0]["ip"] == "192.168.1.1"


class TestArpTableDarwin:
    """Test ARP parsing against macOS `arp -a` output."""

    def test_parse_entries(self) -> None:
        fixture = load_fixture("darwin/arp_a.txt")
        tool = ArpTableTool()

        with (
            patch("cyberpunk.tools.arp_scanner.get_platform", return_value="darwin"),
            patch("cyberpunk.tools.arp_scanner.get_platform_command", return_value=["arp", "-a"]),
            patch(
                "cyberpunk.tools.arp_scanner.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = tool.run()

        assert result.success
        # Broadcast ff:ff:ff:ff:ff:ff still shows up — darwin parser doesn't filter it
        assert result.data["count"] == 6
        assert result.data["entries"][0]["ip"] == "192.168.1.1"
        assert result.data["entries"][0]["interface"] == "en0"


class TestArpTableWin32:
    """Test ARP parsing against Windows `arp -a` output."""

    def test_parse_entries(self) -> None:
        fixture = load_fixture("win32/arp_a.txt")
        tool = ArpTableTool()

        with (
            patch("cyberpunk.tools.arp_scanner.get_platform", return_value="win32"),
            patch("cyberpunk.tools.arp_scanner.get_platform_command", return_value=["arp", "-a"]),
            patch(
                "cyberpunk.tools.arp_scanner.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = tool.run()

        assert result.success
        # ff-ff-ff-ff-ff-ff broadcast is filtered, 224.x multicast is kept
        assert result.data["count"] == 6
        assert result.data["entries"][0]["ip"] == "192.168.1.1"
        # MAC should be normalized to colon format
        assert result.data["entries"][0]["mac"] == "aa:bb:cc:dd:ee:01"

    def test_interface_captured(self) -> None:
        fixture = load_fixture("win32/arp_a.txt")
        tool = ArpTableTool()

        with (
            patch("cyberpunk.tools.arp_scanner.get_platform", return_value="win32"),
            patch("cyberpunk.tools.arp_scanner.get_platform_command", return_value=["arp", "-a"]),
            patch(
                "cyberpunk.tools.arp_scanner.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = tool.run()

        assert result.data["entries"][0]["interface"] == "192.168.1.5"


class TestArpTableCommandNotFound:
    """Test graceful handling when the ARP command is not available."""

    def test_returns_error(self) -> None:
        tool = ArpTableTool()

        with (
            patch("cyberpunk.tools.arp_scanner.get_platform", return_value="linux"),
            patch("cyberpunk.tools.arp_scanner.run_command", return_value=_fake_fail()),
            patch(
                "cyberpunk.tools.arp_scanner.get_platform_command",
                side_effect=lambda k: ["ip", "-j", "neigh", "show"]
                if k == "arp_table_json"
                else ["ip", "neigh", "show"],
            ),
        ):
            result = tool.run()

        assert not result.success
        assert result.error is not None
