"""IEEE 802.11 Deauthentication frame builder."""

from scapy.layers.dot11 import RadioTap, Dot11, Dot11Deauth

from app.models.config import DeauthPacketConfig


def build(cfg: DeauthPacketConfig):
    """Return a Scapy packet for repeated injection."""
    return (
        RadioTap()
        / Dot11(
            type=0,     # Management
            subtype=12, # Deauthentication
            addr1=cfg.dest_mac,
            addr2=cfg.source_mac,
            addr3=cfg.bssid,
        )
        / Dot11Deauth(reason=cfg.reason)
    )
