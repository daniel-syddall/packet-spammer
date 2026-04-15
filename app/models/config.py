"""Project configuration models.

Defines all packet types as discriminated Pydantic models and assembles
them into the top-level ProjectConfig that is loaded from config/config.toml.
"""

from typing import Literal, Union, Annotated
from pydantic import BaseModel, Field

from base.config import BaseHostConfig


# ======================== Packet Types ======================== #

class DeauthPacketConfig(BaseModel):
    """IEEE 802.11 Deauthentication frame."""
    type: Literal["deauth"] = "deauth"
    source_mac: str = "aa:bb:cc:dd:ee:ff"
    dest_mac: str = "ff:ff:ff:ff:ff:ff"
    bssid: str = "aa:bb:cc:dd:ee:ff"
    reason: int = 7


class BeaconPacketConfig(BaseModel):
    """IEEE 802.11 Beacon frame."""
    type: Literal["beacon"] = "beacon"
    ssid: str = "FreeWifi"
    source_mac: str = "aa:bb:cc:dd:ee:ff"
    bssid: str = "aa:bb:cc:dd:ee:ff"


class ProbeReqPacketConfig(BaseModel):
    """IEEE 802.11 Probe Request frame."""
    type: Literal["probe_req"] = "probe_req"
    source_mac: str = "aa:bb:cc:dd:ee:ff"
    ssid: str = ""  # empty string = wildcard probe


class DisassocPacketConfig(BaseModel):
    """IEEE 802.11 Disassociation frame."""
    type: Literal["disassoc"] = "disassoc"
    source_mac: str = "aa:bb:cc:dd:ee:ff"
    dest_mac: str = "ff:ff:ff:ff:ff:ff"
    bssid: str = "aa:bb:cc:dd:ee:ff"
    reason: int = 3


class AuthPacketConfig(BaseModel):
    """IEEE 802.11 Authentication frame."""
    type: Literal["auth"] = "auth"
    source_mac: str = "aa:bb:cc:dd:ee:ff"
    dest_mac: str = "ff:ff:ff:ff:ff:ff"
    bssid: str = "aa:bb:cc:dd:ee:ff"
    algo: int = 0    # 0 = Open System, 1 = Shared Key
    seq: int = 1


# ======================== Discriminated Union ======================== #

PacketConfig = Annotated[
    Union[
        DeauthPacketConfig,
        BeaconPacketConfig,
        ProbeReqPacketConfig,
        DisassocPacketConfig,
        AuthPacketConfig,
    ],
    Field(discriminator="type"),
]


# ======================== Project Config ======================== #

class ProjectConfig(BaseHostConfig):
    """Top-level config loaded from config/config.toml.

    Inherits from BaseHostConfig:
        api      — APIConfig  (host, port, enabled)
        sender   — SpammerConfig  (autostart, packets_per_second, channel)

    Adds:
        packet   — PacketConfig  (discriminated union of all 802.11 frame types)
    """
    packet: PacketConfig = Field(default_factory=DeauthPacketConfig)
