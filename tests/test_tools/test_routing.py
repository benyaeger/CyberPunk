"""Tests for the routing table tool -- all 3 platforms."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from cyberpunk.tools.routing import get_routing_table
from cyberpunk.utils.system import CommandResult
from tests.conftest import load_fixture


def _fake_result(stdout: str) -> CommandResult:
    return CommandResult(stdout=stdout, return_code=0, execution_time_ms=10.0)


def _fake_fail() -> CommandResult:
    return CommandResult(stderr="Command not found: ip", return_code=-1, execution_time_ms=1.0)


class TestRoutingLinuxJson:
    """Test routing table parsing against Linux `ip -j route show` JSON output."""

    def test_parse_entries(self) -> None:
        fixture = load_fixture("linux/ip_route.json")

        with (
            patch("cyberpunk.tools.routing.get_platform", return_value="linux"),
            patch(
                "cyberpunk.tools.routing.get_platform_command",
                return_value=["ip", "-j", "route", "show"],
            ),
            patch(
                "cyberpunk.tools.routing.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_routing_table.invoke({})

        assert result["count"] == 4

    def test_default_gateway(self) -> None:
        fixture = load_fixture("linux/ip_route.json")

        with (
            patch("cyberpunk.tools.routing.get_platform", return_value="linux"),
            patch(
                "cyberpunk.tools.routing.get_platform_command",
                return_value=["ip", "-j", "route", "show"],
            ),
            patch(
                "cyberpunk.tools.routing.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_routing_table.invoke({})

        assert result["default_gateway"] == "192.168.1.1"

    def test_route_details(self) -> None:
        fixture = load_fixture("linux/ip_route.json")

        with (
            patch("cyberpunk.tools.routing.get_platform", return_value="linux"),
            patch(
                "cyberpunk.tools.routing.get_platform_command",
                return_value=["ip", "-j", "route", "show"],
            ),
            patch(
                "cyberpunk.tools.routing.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_routing_table.invoke({})

        default_route = result["routes"][0]
        assert default_route["destination"] == "default"
        assert default_route["gateway"] == "192.168.1.1"
        assert default_route["interface"] == "eth0"
        assert default_route["metric"] == 100

    def test_all_entries_have_required_fields(self) -> None:
        fixture = load_fixture("linux/ip_route.json")

        with (
            patch("cyberpunk.tools.routing.get_platform", return_value="linux"),
            patch(
                "cyberpunk.tools.routing.get_platform_command",
                return_value=["ip", "-j", "route", "show"],
            ),
            patch(
                "cyberpunk.tools.routing.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_routing_table.invoke({})

        for route in result["routes"]:
            assert "destination" in route
            assert "interface" in route


class TestRoutingDarwin:
    """Test routing table parsing against macOS `netstat -rn` output."""

    def test_parse_entries(self) -> None:
        fixture = load_fixture("darwin/netstat_rn.txt")

        with (
            patch("cyberpunk.tools.routing.get_platform", return_value="darwin"),
            patch(
                "cyberpunk.tools.routing.get_platform_command",
                return_value=["netstat", "-rn"],
            ),
            patch(
                "cyberpunk.tools.routing.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_routing_table.invoke({})

        # Should only parse IPv4 section, not IPv6
        assert result["count"] == 8

    def test_default_gateway(self) -> None:
        fixture = load_fixture("darwin/netstat_rn.txt")

        with (
            patch("cyberpunk.tools.routing.get_platform", return_value="darwin"),
            patch(
                "cyberpunk.tools.routing.get_platform_command",
                return_value=["netstat", "-rn"],
            ),
            patch(
                "cyberpunk.tools.routing.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_routing_table.invoke({})

        assert result["default_gateway"] == "192.168.1.1"

    def test_route_details(self) -> None:
        fixture = load_fixture("darwin/netstat_rn.txt")

        with (
            patch("cyberpunk.tools.routing.get_platform", return_value="darwin"),
            patch(
                "cyberpunk.tools.routing.get_platform_command",
                return_value=["netstat", "-rn"],
            ),
            patch(
                "cyberpunk.tools.routing.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_routing_table.invoke({})

        default_route = result["routes"][0]
        assert default_route["destination"] == "default"
        assert default_route["gateway"] == "192.168.1.1"
        assert default_route["interface"] == "en0"
        assert default_route["flags"] == "UGScg"


class TestRoutingWin32:
    """Test routing table parsing against Windows `route print` output."""

    def test_parse_entries(self) -> None:
        fixture = load_fixture("win32/route_print.txt")

        with (
            patch("cyberpunk.tools.routing.get_platform", return_value="win32"),
            patch(
                "cyberpunk.tools.routing.get_platform_command",
                return_value=["route", "print"],
            ),
            patch(
                "cyberpunk.tools.routing.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_routing_table.invoke({})

        assert result["count"] == 8  # All IPv4 active routes

    def test_default_gateway(self) -> None:
        fixture = load_fixture("win32/route_print.txt")

        with (
            patch("cyberpunk.tools.routing.get_platform", return_value="win32"),
            patch(
                "cyberpunk.tools.routing.get_platform_command",
                return_value=["route", "print"],
            ),
            patch(
                "cyberpunk.tools.routing.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_routing_table.invoke({})

        assert result["default_gateway"] == "192.168.1.1"

    def test_cidr_normalization(self) -> None:
        fixture = load_fixture("win32/route_print.txt")

        with (
            patch("cyberpunk.tools.routing.get_platform", return_value="win32"),
            patch(
                "cyberpunk.tools.routing.get_platform_command",
                return_value=["route", "print"],
            ),
            patch(
                "cyberpunk.tools.routing.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_routing_table.invoke({})

        # Default route should be normalized to "default"
        default_route = result["routes"][0]
        assert default_route["destination"] == "default"

        # Subnet route should have CIDR notation
        subnet_route = result["routes"][1]
        assert subnet_route["destination"] == "10.0.0.0/16"

    def test_on_link_gateway_is_none(self) -> None:
        fixture = load_fixture("win32/route_print.txt")

        with (
            patch("cyberpunk.tools.routing.get_platform", return_value="win32"),
            patch(
                "cyberpunk.tools.routing.get_platform_command",
                return_value=["route", "print"],
            ),
            patch(
                "cyberpunk.tools.routing.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_routing_table.invoke({})

        # On-link entries should have gateway=None
        loopback_route = result["routes"][2]
        assert loopback_route["gateway"] is None


class TestRoutingCommandNotFound:
    """Test graceful handling when the routing command is not available."""

    def test_raises_runtime_error(self) -> None:
        with (
            patch("cyberpunk.tools.routing.get_platform", return_value="linux"),
            patch(
                "cyberpunk.tools.routing.get_platform_command",
                return_value=["ip", "-j", "route", "show"],
            ),
            patch(
                "cyberpunk.tools.routing.run_command",
                return_value=_fake_fail(),
            ),
            pytest.raises(RuntimeError),
        ):
            get_routing_table.invoke({})
