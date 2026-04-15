"""Packet factory.

Dispatches to the correct builder module based on the discriminated
`type` field of a PacketConfig and returns a fully-assembled Scapy
frame ready for injection via sendp().
"""

import logging

from app.models.config import (
    PacketConfig,
    DeauthPacketConfig,
    BeaconPacketConfig,
    ProbeReqPacketConfig,
    DisassocPacketConfig,
    AuthPacketConfig,
)
from app.sender.packets import deauth, beacon, probe_req, disassoc, auth

logger = logging.getLogger(__name__)


class PacketFactory:

    @staticmethod
    def build(cfg: PacketConfig, channel: int = 6):
        """Build and return a Scapy frame from a packet config.

        Args:
            cfg:     A validated PacketConfig (any concrete subtype).
            channel: Current operating channel — passed to builders that
                     embed it in the frame (e.g. Beacon DS Parameter Set).

        Returns:
            A Scapy packet object suitable for passing to sendp().

        Raises:
            ValueError: If the packet type is unrecognised.
        """
        match cfg:
            case DeauthPacketConfig():
                frame = deauth.build(cfg)
            case BeaconPacketConfig():
                frame = beacon.build(cfg, channel=channel)
            case ProbeReqPacketConfig():
                frame = probe_req.build(cfg)
            case DisassocPacketConfig():
                frame = disassoc.build(cfg)
            case AuthPacketConfig():
                frame = auth.build(cfg)
            case _:
                raise ValueError(f"Unknown packet type: {cfg.type!r}")

        logger.debug("Built %s frame (%d bytes)", cfg.type, len(bytes(frame)))
        return frame
