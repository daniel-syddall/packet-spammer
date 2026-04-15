"""Project API routes — sender control and runtime configuration."""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, TypeAdapter, ValidationError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["spammer"])

# Injected at startup by HostRuntime._setup_api()
_engine    = None
_iface_mgr = None
_config    = None
_save_fn   = None


def init_project_routes(engine, iface_mgr, config, save_config_fn) -> None:
    global _engine, _iface_mgr, _config, _save_fn
    _engine    = engine
    _iface_mgr = iface_mgr
    _config    = config
    _save_fn   = save_config_fn


# ======================== Sender Control ======================== #

@router.get("/sender/status")
async def sender_status() -> dict[str, Any]:
    """Full sender + interface status snapshot polled by the web UI."""
    return {
        "running":           _engine.is_running,
        "packets_sent":      _engine.packets_sent,
        "session_uptime":    round(_engine.session_uptime, 1),
        "packets_per_second": _config.sender.packets_per_second,
        "channel":           _config.sender.channel,
        "autostart":         _config.sender.autostart,
        "interface":         _iface_mgr.interface,
        "interface_ready":   _iface_mgr.is_ready,
        "interface_error":   _iface_mgr.error,
        "packet_type":       _config.packet.type,
        "packet":            _config.packet.model_dump(),
    }


@router.post("/sender/start")
async def sender_start() -> dict[str, str]:
    """Begin packet injection."""
    if not _iface_mgr.is_ready:
        raise HTTPException(
            status_code=503,
            detail=_iface_mgr.error or "USB WiFi adapter not available",
        )
    if _engine.is_running:
        return {"status": "already_running"}
    _engine.start(_iface_mgr.interface)
    return {"status": "started"}


@router.post("/sender/stop")
async def sender_stop() -> dict[str, str]:
    """Stop packet injection."""
    if not _engine.is_running:
        return {"status": "already_stopped"}
    await asyncio.to_thread(_engine.stop)
    return {"status": "stopped"}


# ======================== Sender Settings ======================== #

class SenderUpdate(BaseModel):
    packets_per_second: int | None = None
    channel:            int | None = None
    autostart:          bool | None = None


@router.put("/config/sender")
async def update_sender(body: SenderUpdate) -> dict[str, Any]:
    """Update rate, channel, and/or autostart flag.

    Changes take effect immediately:
      • rate    — hot-swapped in the running send loop
      • channel — pushed to the interface via iw
      • autostart — persisted to config.toml
    """
    if body.packets_per_second is not None:
        if body.packets_per_second < 1:
            raise HTTPException(422, "packets_per_second must be ≥ 1")
        _config.sender.packets_per_second = body.packets_per_second
        _engine.update_rate(body.packets_per_second)

    if body.channel is not None:
        if not (1 <= body.channel <= 165):
            raise HTTPException(422, "channel must be between 1 and 165")
        _config.sender.channel = body.channel
        if _iface_mgr.is_ready:
            ok = await asyncio.to_thread(_iface_mgr.set_channel, body.channel)
            if not ok:
                logger.warning("Channel change to %d failed on interface", body.channel)

    if body.autostart is not None:
        _config.sender.autostart = body.autostart

    _save_fn()
    return {"status": "ok", "sender": _config.sender.model_dump()}


# ======================== Packet Config ======================== #

@router.get("/config/packet")
async def get_packet() -> dict[str, Any]:
    return _config.packet.model_dump()


@router.put("/config/packet")
async def update_packet(body: dict[str, Any]) -> dict[str, Any]:
    """Replace the active packet configuration.

    The body must contain a ``type`` field matching one of the supported
    802.11 frame types.  All other fields are validated against that type's
    Pydantic model.  The engine's frame is hot-swapped so injection of the
    new packet begins on the very next send-loop iteration.
    """
    from app.models.config import PacketConfig
    from app.sender.packets.factory import PacketFactory

    adapter = TypeAdapter(PacketConfig)
    try:
        new_packet = adapter.validate_python(body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())

    # Build the Scapy frame *before* committing so a bad config doesn't
    # leave the engine in an inconsistent state.
    try:
        new_frame = PacketFactory.build(new_packet, _config.sender.channel)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Frame build failed: {exc}")

    _config.packet = new_packet
    _engine.update_frame(new_frame)
    _save_fn()

    logger.info("Packet updated → type=%s", new_packet.type)
    return {"status": "ok", "packet": new_packet.model_dump()}


# ======================== Full Config ======================== #

@router.get("/config")
async def get_config() -> dict[str, Any]:
    """Return the complete current configuration."""
    return _config.model_dump()
