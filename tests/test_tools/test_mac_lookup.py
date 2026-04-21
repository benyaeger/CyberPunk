"""Tests for the MAC vendor lookup tool."""

from __future__ import annotations

from unittest.mock import patch

from mac_vendor_lookup import VendorNotFoundError

from cyberpunk.tools.mac_lookup import lookup_mac_vendor


class TestMacLookup:
    def test_known_vendor(self) -> None:
        with patch(
            "cyberpunk.tools.mac_lookup._lookup.lookup",
            return_value="Apple, Inc.",
        ):
            result = lookup_mac_vendor.invoke({"mac_addresses": ["aa:bb:cc:dd:ee:ff"]})

        assert result["count"] == 1
        assert result["vendors"]["aa:bb:cc:dd:ee:ff"] == "Apple, Inc."
        assert result["unresolved"] == []

    def test_unknown_vendor(self) -> None:
        with patch(
            "cyberpunk.tools.mac_lookup._lookup.lookup",
            side_effect=VendorNotFoundError("00:00:00:00:00:00"),
        ):
            result = lookup_mac_vendor.invoke({"mac_addresses": ["00:00:00:00:00:00"]})

        assert result["vendors"]["00:00:00:00:00:00"] is None
        assert result["unresolved"] == ["00:00:00:00:00:00"]

    def test_mixed_batch(self) -> None:
        def fake_lookup(mac: str) -> str:
            if mac.startswith("aa"):
                return "Apple, Inc."
            raise VendorNotFoundError(mac)

        with patch("cyberpunk.tools.mac_lookup._lookup.lookup", side_effect=fake_lookup):
            result = lookup_mac_vendor.invoke(
                {"mac_addresses": ["aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66"]}
            )

        assert result["count"] == 2
        assert result["vendors"]["aa:bb:cc:dd:ee:ff"] == "Apple, Inc."
        assert result["vendors"]["11:22:33:44:55:66"] is None
        assert result["unresolved"] == ["11:22:33:44:55:66"]

    def test_malformed_mac(self) -> None:
        with patch(
            "cyberpunk.tools.mac_lookup._lookup.lookup",
            side_effect=ValueError("bad mac"),
        ):
            result = lookup_mac_vendor.invoke({"mac_addresses": ["not-a-mac"]})

        assert result["vendors"]["not-a-mac"] is None
        assert "not-a-mac" in result["unresolved"]
