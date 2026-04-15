"""IEEE 802.11 Beacon frame builder."""

from scapy.layers.dot11 import (
    RadioTap,
    Dot11,
    Dot11Beacon,
    Dot11Elt,
)

from app.models.config import BeaconPacketConfig

# Standard 802.11b/g supported rates encoded as per the spec.
# Each byte = rate * 2, with the MSB set if the rate is 'basic' (mandatory).
_RATES = b"\x82\x84\x8b\x96\x0c\x12\x18\x24"


def build(cfg: BeaconPacketConfig, channel: int = 6):
    """Return a Scapy packet for repeated injection.

    Args:
        cfg:     BeaconPacketConfig with SSID, source MAC, and BSSID.
        channel: Current operating channel — embedded in the DS Parameter Set
                 element so receiving devices know which channel they heard this on.
    """
    return (
        RadioTap()
        / Dot11(
            type=0,    # Management
            subtype=8, # Beacon
            addr1="ff:ff:ff:ff:ff:ff",  # Broadcast destination
            addr2=cfg.source_mac,
            addr3=cfg.bssid,
        )
        / Dot11Beacon(cap="ESS")
        / Dot11Elt(ID="SSID",  info=cfg.ssid.encode())
        / Dot11Elt(ID="Rates", info=_RATES)
        / Dot11Elt(ID="DSset", info=bytes([channel]))
    )
