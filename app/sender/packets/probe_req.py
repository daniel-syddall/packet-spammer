"""IEEE 802.11 Probe Request frame builder."""

from scapy.layers.dot11 import (
    RadioTap,
    Dot11,
    Dot11ProbeReq,
    Dot11Elt,
)

from app.models.config import ProbeReqPacketConfig

_RATES = b"\x82\x84\x8b\x96\x0c\x12\x18\x24"


def build(cfg: ProbeReqPacketConfig):
    """Return a Scapy packet for repeated injection.

    An empty SSID field is a wildcard probe — any AP that hears it will
    respond with a Probe Response.
    """
    return (
        RadioTap()
        / Dot11(
            type=0,    # Management
            subtype=4, # Probe Request
            addr1="ff:ff:ff:ff:ff:ff",
            addr2=cfg.source_mac,
            addr3="ff:ff:ff:ff:ff:ff",
        )
        / Dot11ProbeReq()
        / Dot11Elt(ID="SSID",  info=cfg.ssid.encode())
        / Dot11Elt(ID="Rates", info=_RATES)
    )
