"""CyberPunk tool collection.

Every tool is a LangChain ``BaseTool`` (produced by the ``@tool`` decorator
in the module that defines it). The module-level ``CATEGORY`` string on each
tool module marks the tool as ``"passive"`` or ``"active"``; that marker is
attached to the ``BaseTool`` as a tag so the agent can filter active tools
out of stealth-mode runs.
"""

from __future__ import annotations

from types import ModuleType

from langchain_core.tools import BaseTool

from cyberpunk.tools import (
    arp_scanner,
    connections,
    dhcp_lease,
    dns_config,
    interfaces,
    listeners,
    mac_lookup,
    routing,
)


def _register(module: ModuleType, attr: str) -> BaseTool:
    """Pull the tool off its module and stamp it with the category tag.

    LangChain's ``@tool`` decorator returns a ``StructuredTool`` whose
    ``tags`` default to ``None``. Setting ``tags`` here means the agent can
    do one-liner stealth filtering (``"active" not in tool.tags``) without
    the tool module needing to know anything about the filter.
    """
    tool: BaseTool = getattr(module, attr)
    tool.tags = [module.CATEGORY]
    return tool


# The full tool catalog. Adding a new tool: drop a file in this package that
# exports a ``@tool``-decorated function and a ``CATEGORY`` constant, then
# add a line here.
TOOLS: list[BaseTool] = [
    _register(arp_scanner, "get_arp_table"),
    _register(interfaces, "get_network_interfaces"),
    _register(routing, "get_routing_table"),
    _register(connections, "get_active_connections"),
    _register(listeners, "get_listening_services"),
    _register(dns_config, "get_dns_config"),
    _register(dhcp_lease, "get_dhcp_lease"),
    _register(mac_lookup, "lookup_mac_vendor"),
]


def available_tools(stealth: bool = False) -> list[BaseTool]:
    """Return tools visible to the agent for a given run.

    Args:
        stealth: If ``True``, filter out anything tagged ``"active"``.
            Tools without the ``"active"`` tag — i.e. passive and analysis
            tools — are always included.

    Returns:
        A list of LangChain ``BaseTool`` instances ready to be bound to the
        chat model via ``bind_tools(...)``.
    """
    if not stealth:
        return list(TOOLS)
    return [t for t in TOOLS if "active" not in (t.tags or [])]
