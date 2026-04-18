"""Tests for the network interfaces tool -- all 3 platforms."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from cyberpunk.tools.interfaces import get_network_interfaces
from cyberpunk.utils.system import CommandResult
from tests.conftest import load_fixture


def _fake_result(stdout: str) -> CommandResult:
    return CommandResult(stdout=stdout, return_code=0, execution_time_ms=10.0)


def _fake_fail() -> CommandResult:
    return CommandResult(stderr="Command not found: ip", return_code=-1, execution_time_ms=1.0)


class TestInterfacesLinuxJson:
    """Test interface parsing against Linux `ip -j addr show` JSON output."""

    def test_parse_entries(self) -> None:
        fixture = load_fixture("linux/ip_addr.json")

        with (
            patch("cyberpunk.tools.interfaces.get_platform", return_value="linux"),
            patch(
                "cyberpunk.tools.interfaces.get_platform_command",
                return_value=["ip", "-j", "addr", "show"],
            ),
            patch(
                "cyberpunk.tools.interfaces.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_network_interfaces.invoke({})

        assert result["count"] == 4
        # lo, eth0, wlan0, docker0

    def test_loopback_detected(self) -> None:
        fixture = load_fixture("linux/ip_addr.json")

        with (
            patch("cyberpunk.tools.interfaces.get_platform", return_value="linux"),
            patch(
                "cyberpunk.tools.interfaces.get_platform_command",
                return_value=["ip", "-j", "addr", "show"],
            ),
            patch(
                "cyberpunk.tools.interfaces.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_network_interfaces.invoke({})

        lo = result["interfaces"][0]
        assert lo["name"] == "lo"
        assert lo["is_loopback"] is True

    def test_ethernet_details(self) -> None:
        fixture = load_fixture("linux/ip_addr.json")

        with (
            patch("cyberpunk.tools.interfaces.get_platform", return_value="linux"),
            patch(
                "cyberpunk.tools.interfaces.get_platform_command",
                return_value=["ip", "-j", "addr", "show"],
            ),
            patch(
                "cyberpunk.tools.interfaces.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_network_interfaces.invoke({})

        eth0 = result["interfaces"][1]
        assert eth0["name"] == "eth0"
        assert eth0["ip"] == "192.168.1.10"
        assert eth0["mac"] == "aa:bb:cc:dd:ee:01"
        assert eth0["cidr"] == "192.168.1.10/24"
        assert eth0["subnet_mask"] == "255.255.255.0"
        assert eth0["mtu"] == 1500
        assert eth0["is_up"] is True
        assert eth0["is_loopback"] is False

    def test_down_interface(self) -> None:
        fixture = load_fixture("linux/ip_addr.json")

        with (
            patch("cyberpunk.tools.interfaces.get_platform", return_value="linux"),
            patch(
                "cyberpunk.tools.interfaces.get_platform_command",
                return_value=["ip", "-j", "addr", "show"],
            ),
            patch(
                "cyberpunk.tools.interfaces.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_network_interfaces.invoke({})

        # docker0 has NO-CARRIER and operstate DOWN but UP in flags
        docker0 = result["interfaces"][3]
        assert docker0["name"] == "docker0"

    def test_all_entries_have_required_fields(self) -> None:
        fixture = load_fixture("linux/ip_addr.json")

        with (
            patch("cyberpunk.tools.interfaces.get_platform", return_value="linux"),
            patch(
                "cyberpunk.tools.interfaces.get_platform_command",
                return_value=["ip", "-j", "addr", "show"],
            ),
            patch(
                "cyberpunk.tools.interfaces.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_network_interfaces.invoke({})

        for iface in result["interfaces"]:
            assert "name" in iface
            assert "is_up" in iface
            assert "is_loopback" in iface


class TestInterfacesDarwin:
    """Test interface parsing against macOS `ifconfig` output."""

    def test_parse_entries(self) -> None:
        fixture = load_fixture("darwin/ifconfig.txt")

        with (
            patch("cyberpunk.tools.interfaces.get_platform", return_value="darwin"),
            patch(
                "cyberpunk.tools.interfaces.get_platform_command",
                return_value=["ifconfig"],
            ),
            patch(
                "cyberpunk.tools.interfaces.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_network_interfaces.invoke({})

        assert result["count"] == 4  # lo0, en0, en1, utun0

    def test_en0_details(self) -> None:
        fixture = load_fixture("darwin/ifconfig.txt")

        with (
            patch("cyberpunk.tools.interfaces.get_platform", return_value="darwin"),
            patch(
                "cyberpunk.tools.interfaces.get_platform_command",
                return_value=["ifconfig"],
            ),
            patch(
                "cyberpunk.tools.interfaces.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_network_interfaces.invoke({})

        en0 = result["interfaces"][1]
        assert en0["name"] == "en0"
        assert en0["ip"] == "192.168.1.42"
        assert en0["mac"] == "aa:bb:cc:dd:ee:01"
        assert en0["subnet_mask"] == "255.255.255.0"
        assert en0["cidr"] == "192.168.1.42/24"
        assert en0["broadcast"] == "192.168.1.255"
        assert en0["is_up"] is True
        assert en0["is_loopback"] is False

    def test_loopback_detected(self) -> None:
        fixture = load_fixture("darwin/ifconfig.txt")

        with (
            patch("cyberpunk.tools.interfaces.get_platform", return_value="darwin"),
            patch(
                "cyberpunk.tools.interfaces.get_platform_command",
                return_value=["ifconfig"],
            ),
            patch(
                "cyberpunk.tools.interfaces.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_network_interfaces.invoke({})

        lo0 = result["interfaces"][0]
        assert lo0["name"] == "lo0"
        assert lo0["is_loopback"] is True


class TestInterfacesWin32:
    """Test interface parsing against Windows `ipconfig /all` output."""

    def test_parse_entries(self) -> None:
        fixture = load_fixture("win32/ipconfig_all.txt")

        with (
            patch("cyberpunk.tools.interfaces.get_platform", return_value="win32"),
            patch(
                "cyberpunk.tools.interfaces.get_platform_command",
                return_value=["ipconfig", "/all"],
            ),
            patch(
                "cyberpunk.tools.interfaces.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_network_interfaces.invoke({})

        assert result["count"] == 3  # Ethernet, Wi-Fi, Loopback

    def test_ethernet_details(self) -> None:
        fixture = load_fixture("win32/ipconfig_all.txt")

        with (
            patch("cyberpunk.tools.interfaces.get_platform", return_value="win32"),
            patch(
                "cyberpunk.tools.interfaces.get_platform_command",
                return_value=["ipconfig", "/all"],
            ),
            patch(
                "cyberpunk.tools.interfaces.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_network_interfaces.invoke({})

        eth = result["interfaces"][0]
        assert eth["name"] == "Ethernet"
        assert eth["ip"] == "192.168.1.5"
        assert eth["mac"] == "AA:BB:CC:DD:EE:01"
        assert eth["subnet_mask"] == "255.255.255.0"
        assert eth["cidr"] == "192.168.1.5/24"
        assert eth["is_up"] is True

    def test_disconnected_interface(self) -> None:
        fixture = load_fixture("win32/ipconfig_all.txt")

        with (
            patch("cyberpunk.tools.interfaces.get_platform", return_value="win32"),
            patch(
                "cyberpunk.tools.interfaces.get_platform_command",
                return_value=["ipconfig", "/all"],
            ),
            patch(
                "cyberpunk.tools.interfaces.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_network_interfaces.invoke({})

        wifi = result["interfaces"][1]
        assert wifi["name"] == "Wi-Fi"
        assert wifi["is_up"] is False
        assert "ip" not in wifi  # Disconnected, no IP assigned

    def test_loopback_detected(self) -> None:
        fixture = load_fixture("win32/ipconfig_all.txt")

        with (
            patch("cyberpunk.tools.interfaces.get_platform", return_value="win32"),
            patch(
                "cyberpunk.tools.interfaces.get_platform_command",
                return_value=["ipconfig", "/all"],
            ),
            patch(
                "cyberpunk.tools.interfaces.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_network_interfaces.invoke({})

        loopback = result["interfaces"][2]
        assert loopback["is_loopback"] is True

    def test_mac_normalized(self) -> None:
        fixture = load_fixture("win32/ipconfig_all.txt")

        with (
            patch("cyberpunk.tools.interfaces.get_platform", return_value="win32"),
            patch(
                "cyberpunk.tools.interfaces.get_platform_command",
                return_value=["ipconfig", "/all"],
            ),
            patch(
                "cyberpunk.tools.interfaces.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_network_interfaces.invoke({})

        # MAC should use colons, not dashes
        eth = result["interfaces"][0]
        assert ":" in eth["mac"]
        assert "-" not in eth["mac"]


class TestInterfacesCommandNotFound:
    """Test graceful handling when the interfaces command is not available."""

    def test_raises_runtime_error(self) -> None:
        with (
            patch("cyberpunk.tools.interfaces.get_platform", return_value="linux"),
            patch(
                "cyberpunk.tools.interfaces.get_platform_command",
                return_value=["ip", "-j", "addr", "show"],
            ),
            patch(
                "cyberpunk.tools.interfaces.run_command",
                return_value=_fake_fail(),
            ),
            pytest.raises(RuntimeError),
        ):
            get_network_interfaces.invoke({})
