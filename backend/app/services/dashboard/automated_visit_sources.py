"""Offline classification of the rotating browser crawler observed on 2026-11-09.

Require BOTH an observed browser fingerprint and an audited hosting network.
Neither a Chrome version nor cloud hosting alone is evidence of automation.
Network provenance and the counting contract are in docs/site-visitor-counting.md.
"""

from __future__ import annotations

import json
from ipaddress import IPv6Address, ip_address, ip_network
from pathlib import Path

_BROWSER_FINGERPRINTS = frozenset(
    (
        f"Mozilla/5.0 ({platform}) AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{version}.0.0.0 Safari/537.36"
    ).casefold()
    for platform in (
        "Windows NT 10.0; Win64; x64",
        "Macintosh; Intel Mac OS X 10_15_7",
    )
    for version in (148, 149, 150)
)

# Reviewed APNIC allocations plus the two source ASNs' RIPE RIS route snapshot.
# Compile once; requests never perform registry lookups or download mutable lists.
_SOURCE_NETWORKS = tuple(
    ip_network(cidr)
    for cidr in json.loads(
        Path(__file__).with_name("automated_visit_networks.json").read_text(encoding="utf-8")
    )["networks"]
)


def is_known_automated_browser(user_agent: str | None, client_ip: str | None) -> bool:
    """Accept only a client address resolved through the trusted proxy boundary."""
    if (user_agent or "").strip().casefold() not in _BROWSER_FINGERPRINTS:
        return False
    try:
        address = ip_address((client_ip or "").strip())
    except ValueError:
        return False
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return any(address in network for network in _SOURCE_NETWORKS)
