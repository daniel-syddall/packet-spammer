"""Project configuration models.

Defines all packet types and task types as discriminated Pydantic models
and assembles them into the top-level ProjectConfig loaded from config.toml.
"""

import uuid
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


# ======================== Task Types ======================== #

def _new_id() -> str:
    return uuid.uuid4().hex[:8]


class StandardTaskConfig(BaseModel):
    """Single packet type, fixed channel, one or more interfaces."""
    type: Literal["standard"] = "standard"
    id: str = Field(default_factory=_new_id)
    name: str = "Standard Task"
    enabled: bool = False
    channel: int = 6
    packets_per_second: int = 10
    packet: PacketConfig = Field(default_factory=DeauthPacketConfig)


class SpanTaskConfig(BaseModel):
    """Staggered multi-channel cycling — each interface starts at a different channel offset."""
    type: Literal["span"] = "span"
    id: str = Field(default_factory=_new_id)
    name: str = "Span Task"
    enabled: bool = False
    channels: list[int] = Field(default_factory=lambda: [1, 6, 11])
    dwell_ms: int = 1000
    packets_per_second: int = 10
    packet: PacketConfig = Field(default_factory=DeauthPacketConfig)


class BeaconSequenceTaskConfig(BaseModel):
    """Cycles through a sequence of beacon SSIDs: {task_name}-{seq_num}-{pos}."""
    type: Literal["beacon_sequence"] = "beacon_sequence"
    id: str = Field(default_factory=_new_id)
    name: str = "Beacon Sequence"
    enabled: bool = False
    task_name: str = "seq"
    sequence_length: int = 100
    channel: int = 6
    packets_per_second: int = 10
    source_mac: str = "aa:bb:cc:dd:ee:ff"
    bssid: str = "aa:bb:cc:dd:ee:ff"


TaskConfig = Annotated[
    Union[
        StandardTaskConfig,
        SpanTaskConfig,
        BeaconSequenceTaskConfig,
    ],
    Field(discriminator="type"),
]


# ======================== Project Config ======================== #

class ProjectConfig(BaseHostConfig):
    """Top-level config loaded from config/config.toml.

    Inherits from BaseHostConfig:
        api    — APIConfig (host, port, enabled)

    Adds:
        tasks  — list of TaskConfig (discriminated union of all task types)
    """
    tasks: list[TaskConfig] = Field(default_factory=list)
