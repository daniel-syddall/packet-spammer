"""Base API routes — health check and system status."""

import time
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["system"])

_start_time: float = 0.0
_extras_fn = None


def init_base_routes(extras_fn=None) -> None:
    """Initialise base routes with runtime-provided callbacks.

    Args:
        extras_fn: Callable returning extra fields to merge into /api/status.
    """
    global _start_time, _extras_fn
    _start_time = time.time()
    _extras_fn = extras_fn


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@router.get("/status")
async def status() -> dict[str, Any]:
    """System uptime and optional runtime extras."""
    data: dict[str, Any] = {
        "uptime": round(time.time() - _start_time, 1) if _start_time else 0,
    }
    if _extras_fn:
        data.update(_extras_fn())
    return data
