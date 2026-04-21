"""MAC vendor lookup tool: resolves OUI prefixes against a local vendor database."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool
from mac_vendor_lookup import MacLookup, VendorNotFoundError

CATEGORY = "passive"

# A single shared ``MacLookup`` instance — it loads the OUI table lazily on
# first query and caches it in memory for subsequent lookups. No network
# access is required after the bundled database is populated.
_lookup = MacLookup()


@tool
def lookup_mac_vendor(mac_addresses: list[str]) -> dict[str, Any]:
    """Resolve MAC addresses to vendor names using an offline OUI database.

    Args:
        mac_addresses: One or more MAC addresses in any standard format
            (``aa:bb:cc:dd:ee:ff``, ``aa-bb-cc-dd-ee-ff``, or
            ``aabbccddeeff``).

    Returns a mapping from each input MAC to its vendor name (or ``None``
    if the OUI prefix wasn't found in the local database). No network
    access is performed.
    """
    vendors: dict[str, str | None] = {}
    unresolved: list[str] = []

    for mac in mac_addresses:
        try:
            vendors[mac] = _lookup.lookup(mac)
        except (VendorNotFoundError, ValueError, KeyError):
            # ``ValueError`` / ``KeyError`` cover malformed MACs that the
            # library rejects before lookup; ``VendorNotFoundError`` is the
            # normal "no OUI match" signal.
            vendors[mac] = None
            unresolved.append(mac)

    return {
        "vendors": vendors,
        "count": len(vendors),
        "unresolved": unresolved,
    }
