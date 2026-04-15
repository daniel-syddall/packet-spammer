"""IEEE 802.11 Disassociation frame builder."""

from scapy.layers.dot11 import RadioTap, Dot11, Dot11Disas

from app.models.config import DisassocPacketConfig


def build(cfg: DisassocPacketConfig):
    """Return a Scapy packet for repeated injection."""
    return (
        RadioTap()
        / Dot11(
            type=0,     # Management
            subtype=10, # Disassociation
            addr1=cfg.dest_mac,
            addr2=cfg.source_mac,
            addr3=cfg.bssid,
        )
        / Dot11Disas(reason=cfg.reason)
    )
