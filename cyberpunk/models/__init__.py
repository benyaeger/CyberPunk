"""Pydantic data models for CyberPunk.

Agent/runtime concerns (tool calls, LLM messages, tool results) are owned by
LangChain + LangGraph now, so this module only holds the domain data models
— devices, interfaces, subnets, and the enums that describe them.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

# ── Enums ──────────────────────────────────────────────────────────────────


class DeviceType(StrEnum):
    ROUTER = "router"
    SWITCH = "switch"
    ACCESS_POINT = "access_point"
    FIREWALL = "firewall"
    WORKSTATION = "workstation"
    SERVER = "server"
    PRINTER = "printer"
    PHONE = "phone"
    IOT = "iot"
    UNKNOWN = "unknown"


class OSFamily(StrEnum):
    LINUX = "linux"
    WINDOWS = "windows"
    MACOS = "macos"
    IOS = "ios"
    ANDROID = "android"
    FREEBSD = "freebsd"
    NETWORK_DEVICE = "network_device"
    UNKNOWN = "unknown"


class ScanType(StrEnum):
    PASSIVE = "passive"
    ACTIVE = "active"
    FULL = "full"


# ── Core Models ────────────────────────────────────────────────────────────


class NetworkInterface(BaseModel):
    name: str
    ip_address: str | None = None
    mac_address: str | None = None
    cidr: str | None = None
    subnet_mask: str | None = None
    mtu: int | None = None
    is_up: bool = True
    is_loopback: bool = False
    broadcast: str | None = None


class OpenPort(BaseModel):
    port: int = Field(ge=1, le=65535)
    protocol: str = "tcp"
    service: str | None = None
    banner: str | None = None
    state: str = "open"


class Device(BaseModel):
    ip_address: str
    mac_address: str | None = None
    hostname: str | None = None
    vendor: str | None = None
    device_type: DeviceType = DeviceType.UNKNOWN
    os_family: OSFamily = OSFamily.UNKNOWN
    open_ports: list[OpenPort] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    last_seen: datetime = Field(default_factory=datetime.now)
    data_sources: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ip_address")
    @classmethod
    def validate_ip(cls, v: str) -> str:
        parts = v.split(".")
        if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
            raise ValueError(f"Invalid IPv4 address: {v}")
        return v


class Subnet(BaseModel):
    cidr: str
    gateway_ip: str | None = None
    dns_servers: list[str] = Field(default_factory=list)
    dhcp_server: str | None = None
    devices: list[Device] = Field(default_factory=list)


class NetworkMap(BaseModel):
    subnets: list[Subnet] = Field(default_factory=list)
    local_interfaces: list[NetworkInterface] = Field(default_factory=list)
    local_hostname: str | None = None
    scan_type: ScanType = ScanType.PASSIVE
    scan_started: datetime = Field(default_factory=datetime.now)
    scan_finished: datetime | None = None
    tool_results: dict[str, Any] = Field(default_factory=dict)
