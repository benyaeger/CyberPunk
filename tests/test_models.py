"""Tests for Pydantic model validation."""

from __future__ import annotations

import pytest

from cyberpunk.models import (
    Device,
    DeviceType,
    NetworkMap,
    OSFamily,
    ScanType,
    ToolCategory,
    ToolDefinition,
    ToolResult,
)


class TestDevice:
    def test_valid_device(self) -> None:
        d = Device(ip_address="192.168.1.1", mac_address="aa:bb:cc:dd:ee:ff")
        assert d.ip_address == "192.168.1.1"
        assert d.device_type == DeviceType.UNKNOWN
        assert d.confidence == 0.5

    def test_invalid_ip(self) -> None:
        with pytest.raises(ValueError, match="Invalid IPv4"):
            Device(ip_address="999.999.999.999")

    def test_invalid_ip_format(self) -> None:
        with pytest.raises(ValueError):
            Device(ip_address="not-an-ip")

    def test_confidence_range(self) -> None:
        with pytest.raises(ValueError):
            Device(ip_address="10.0.0.1", confidence=1.5)
        with pytest.raises(ValueError):
            Device(ip_address="10.0.0.1", confidence=-0.1)

    def test_enums(self) -> None:
        d = Device(
            ip_address="10.0.0.1",
            device_type=DeviceType.ROUTER,
            os_family=OSFamily.LINUX,
        )
        assert d.device_type == "router"
        assert d.os_family == "linux"


class TestNetworkMap:
    def test_default_scan_type(self) -> None:
        nm = NetworkMap()
        assert nm.scan_type == ScanType.PASSIVE


class TestToolDefinition:
    def test_ollama_schema(self) -> None:
        td = ToolDefinition(
            name="get_arp_table",
            description="Read ARP cache",
            category=ToolCategory.PASSIVE,
        )
        schema = td.to_ollama_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "get_arp_table"
        assert schema["function"]["parameters"]["type"] == "object"


class TestToolResult:
    def test_success(self) -> None:
        r = ToolResult(tool_name="test", success=True, data={"count": 5})
        assert r.success
        assert r.data["count"] == 5

    def test_failure(self) -> None:
        r = ToolResult(tool_name="test", success=False, error="boom")
        assert not r.success
        assert r.error == "boom"
