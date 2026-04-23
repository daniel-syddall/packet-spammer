"""Project API routes — interface pool status and task management."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import TypeAdapter, ValidationError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["spammer"])

# Injected at startup by HostRuntime._setup_api()
_pool      = None
_task_mgr  = None
_config    = None
_save_fn   = None


def init_project_routes(pool, task_mgr, config, save_config_fn) -> None:
    global _pool, _task_mgr, _config, _save_fn
    _pool      = pool
    _task_mgr  = task_mgr
    _config    = config
    _save_fn   = save_config_fn


# ======================== Interface Pool ======================== #

@router.get("/pool")
async def pool_status() -> dict[str, Any]:
    """Interface pool summary — adapter list and readiness."""
    return {
        "ready":      _pool.is_ready,
        "count":      _pool.count,
        "error":      _pool.error,
        "interfaces": _pool.status(),
    }


# ======================== Task List ======================== #

@router.get("/tasks")
async def list_tasks() -> list[dict[str, Any]]:
    """Return status for all configured tasks."""
    return _task_mgr.status()


@router.post("/tasks")
async def create_task(body: dict[str, Any]) -> dict[str, Any]:
    """Create a new task from the given config body.

    The body must contain a ``type`` field: ``standard``, ``span``, or
    ``beacon_sequence``.
    """
    from app.models.config import TaskConfig

    adapter = TypeAdapter(TaskConfig)
    try:
        task_cfg = adapter.validate_python(body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())

    _task_mgr.add_task(task_cfg)
    _save_fn()
    logger.info("Task created: %s (%s)", task_cfg.name, task_cfg.type)
    return {"status": "created", "id": task_cfg.id}


# ======================== Single Task ======================== #

@router.get("/tasks/{task_id}")
async def get_task(task_id: str) -> dict[str, Any]:
    tasks = _task_mgr.status()
    for t in tasks:
        if t["id"] == task_id:
            return t
    raise HTTPException(status_code=404, detail=f"Task {task_id!r} not found")


@router.put("/tasks/{task_id}")
async def update_task(task_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Replace a task's configuration.  The task is stopped and restarted.

    The ``type`` field must be present and match or change the task type.
    The ``id`` in the body (if any) is ignored — the URL task_id is used.
    """
    from app.models.config import TaskConfig

    body["id"] = task_id
    adapter = TypeAdapter(TaskConfig)
    try:
        new_cfg = adapter.validate_python(body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())

    try:
        _task_mgr.update_task(task_id, new_cfg)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Task {task_id!r} not found")

    _save_fn()
    logger.info("Task updated: %s (%s)", new_cfg.name, new_cfg.type)
    return {"status": "updated", "id": task_id}


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str) -> dict[str, str]:
    try:
        _task_mgr.remove_task(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Task {task_id!r} not found")
    _save_fn()
    logger.info("Task deleted: %s", task_id)
    return {"status": "deleted", "id": task_id}


# ======================== Task Control ======================== #

@router.post("/tasks/{task_id}/start")
async def start_task(task_id: str) -> dict[str, str]:
    """Enable and start a task.  503 if no interfaces are ready."""
    if not _pool.is_ready:
        raise HTTPException(
            status_code=503,
            detail=_pool.error or "No USB WiFi adapters available",
        )
    try:
        _task_mgr.start_task(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Task {task_id!r} not found")
    _save_fn()
    return {"status": "started", "id": task_id}


@router.post("/tasks/{task_id}/stop")
async def stop_task(task_id: str) -> dict[str, str]:
    """Disable and stop a task."""
    try:
        _task_mgr.stop_task(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Task {task_id!r} not found")
    _save_fn()
    return {"status": "stopped", "id": task_id}


# ======================== Full Config ======================== #

@router.get("/config")
async def get_config() -> dict[str, Any]:
    """Return the complete current configuration."""
    return _config.model_dump()
