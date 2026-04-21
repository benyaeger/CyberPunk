"""Tests for the DHCP lease tool -- all 3 platforms."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from cyberpunk.tools.dhcp_lease import get_dhcp_lease
from cyberpunk.utils.system import CommandResult
from tests.conftest import load_fixture


def _fake_result(stdout: str) -> CommandResult:
    return CommandResult(stdout=stdout, return_code=0, execution_time_ms=10.0)


def _fake_fail() -> CommandResult:
    return CommandResult(stderr="not found", return_code=-1, execution_time_ms=1.0)


class TestDhcpLinux:
    def test_parse(self) -> None:
        fixture = load_fixture("linux/nmcli_dev_show.txt")
        with (
            patch("cyberpunk.tools.dhcp_lease.get_platform", return_value="linux"),
            patch(
                "cyberpunk.tools.dhcp_lease.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_dhcp_lease.invoke({})

        assert result["count"] == 1
        lease = result["leases"][0]
        assert lease["interface"] == "eth0"
        assert lease["dhcp_server"] == "192.168.1.1"
        assert lease["gateway"] == "192.168.1.1"
        assert lease["dns_servers"] == ["192.168.1.1", "8.8.8.8"]
        assert lease["lease_time_seconds"] == 86400
        assert lease["subnet_mask"] == "255.255.255.0"
        assert lease["domain_name"] == "home.local"


class TestDhcpDarwin:
    def test_parse(self) -> None:
        fixture = load_fixture("darwin/ipconfig_getpacket.txt")
        with (
            patch("cyberpunk.tools.dhcp_lease.get_platform", return_value="darwin"),
            patch(
                "cyberpunk.tools.dhcp_lease.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_dhcp_lease.invoke({})

        assert result["count"] == 1
        lease = result["leases"][0]
        assert lease["interface"] == "en0"
        assert lease["ip_address"] == "192.168.1.100"
        assert lease["dhcp_server"] == "192.168.1.1"
        assert lease["gateway"] == "192.168.1.1"
        assert lease["dns_servers"] == ["192.168.1.1", "8.8.8.8"]
        assert lease["lease_time_seconds"] == 0x15180
        assert lease["subnet_mask"] == "255.255.255.0"

    def test_explicit_interface(self) -> None:
        fixture = load_fixture("darwin/ipconfig_getpacket.txt")
        with (
            patch("cyberpunk.tools.dhcp_lease.get_platform", return_value="darwin"),
            patch(
                "cyberpunk.tools.dhcp_lease.run_command",
                return_value=_fake_result(fixture),
            ) as rc,
        ):
            result = get_dhcp_lease.invoke({"interface": "en1"})

        assert rc.call_args.args[0] == ["ipconfig", "getpacket", "en1"]
        assert result["leases"][0]["interface"] == "en1"


class TestDhcpWin32:
    def test_parse(self) -> None:
        fixture = load_fixture("win32/ipconfig_all.txt")
        with (
            patch("cyberpunk.tools.dhcp_lease.get_platform", return_value="win32"),
            patch(
                "cyberpunk.tools.dhcp_lease.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_dhcp_lease.invoke({})

        # Ethernet adapter has DHCP enabled and a DHCP server; Wi-Fi is
        # disconnected, Loopback has no DHCP Server line — so only one
        # lease should be returned.
        assert result["count"] == 1
        lease = result["leases"][0]
        assert lease["interface"] == "Ethernet"
        assert lease["dhcp_server"] == "192.168.1.1"
        assert lease["gateway"] == "192.168.1.1"
        assert lease["subnet_mask"] == "255.255.255.0"


class TestDhcpFailure:
    def test_raises_runtime_error(self) -> None:
        with (
            patch("cyberpunk.tools.dhcp_lease.get_platform", return_value="linux"),
            patch(
                "cyberpunk.tools.dhcp_lease.run_command",
                return_value=_fake_fail(),
            ),
            pytest.raises(RuntimeError),
        ):
            get_dhcp_lease.invoke({})
