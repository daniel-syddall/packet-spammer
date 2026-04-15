"""IEEE 802.11 Authentication frame builder."""

from scapy.layers.dot11 import RadioTap, Dot11, Dot11Auth

from app.models.config import AuthPacketConfig


def build(cfg: AuthPacketConfig):
    """Return a Scapy packet for repeated injection.

    algo=0 is Open System (no credential exchange).
    algo=1 is Shared Key (uses WEP challenge, rarely used today).
    """
    return (
        RadioTap()
        / Dot11(
            type=0,     # Management
            subtype=11, # Authentication
            addr1=cfg.dest_mac,
            addr2=cfg.source_mac,
            addr3=cfg.bssid,
        )
        / Dot11Auth(
            algo=cfg.algo,
            seqnum=cfg.seq,
            status=0,
        )
    )
