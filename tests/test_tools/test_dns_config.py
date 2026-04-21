"""Tests for the DNS config tool -- all 3 platforms."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from cyberpunk.tools.dns_config import get_dns_config
from cyberpunk.utils.system import CommandResult
from tests.conftest import load_fixture


def _fake_result(stdout: str) -> CommandResult:
    return CommandResult(stdout=stdout, return_code=0, execution_time_ms=10.0)


def _fake_fail() -> CommandResult:
    return CommandResult(stderr="not found", return_code=-1, execution_time_ms=1.0)


class TestDnsLinux:
    def test_parse(self) -> None:
        fixture = load_fixture("linux/resolv_conf.txt")
        with (
            patch("cyberpunk.tools.dns_config.get_platform", return_value="linux"),
            patch(
                "cyberpunk.tools.dns_config.get_platform_command",
                return_value=["cat", "/etc/resolv.conf"],
            ),
            patch(
                "cyberpunk.tools.dns_config.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_dns_config.invoke({})

        assert result["nameservers"] == ["192.168.1.1", "8.8.8.8", "1.1.1.1"]
        assert result["search_domains"] == ["home.local", "example.com"]
        assert "edns0" in result["options"]


class TestDnsDarwin:
    def test_parse(self) -> None:
        fixture = load_fixture("darwin/resolv_conf.txt")
        with (
            patch("cyberpunk.tools.dns_config.get_platform", return_value="darwin"),
            patch(
                "cyberpunk.tools.dns_config.get_platform_command",
                return_value=["cat", "/etc/resolv.conf"],
            ),
            patch(
                "cyberpunk.tools.dns_config.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_dns_config.invoke({})

        assert result["nameservers"] == ["192.168.1.1", "8.8.8.8"]
        assert "home.local" in result["search_domains"]


class TestDnsWin32:
    def test_parse(self) -> None:
        fixture = load_fixture("win32/ipconfig_all.txt")
        with (
            patch("cyberpunk.tools.dns_config.get_platform", return_value="win32"),
            patch(
                "cyberpunk.tools.dns_config.get_platform_command",
                return_value=["ipconfig", "/all"],
            ),
            patch(
                "cyberpunk.tools.dns_config.run_command",
                return_value=_fake_result(fixture),
            ),
        ):
            result = get_dns_config.invoke({})

        # Main adapter DNS: 192.168.1.1 + continuation 8.8.8.8
        assert "192.168.1.1" in result["nameservers"]
        assert "8.8.8.8" in result["nameservers"]
        assert "home.local" in result["search_domains"]


class TestDnsFailure:
    def test_raises_runtime_error(self) -> None:
        with (
            patch("cyberpunk.tools.dns_config.get_platform", return_value="linux"),
            patch(
                "cyberpunk.tools.dns_config.get_platform_command",
                return_value=["cat", "/etc/resolv.conf"],
            ),
            patch(
                "cyberpunk.tools.dns_config.run_command",
                return_value=_fake_fail(),
            ),
            pytest.raises(RuntimeError),
        ):
            get_dns_config.invoke({})
