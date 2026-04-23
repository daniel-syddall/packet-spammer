"""Task manager — coordinates the interface pool and all task engines.

Any structural change (add / remove / enable / disable a task) triggers
rebalance(), which:
  1. Stops all running engines.
  2. Splits the interface pool evenly among enabled tasks.
  3. Re-starts each enabled task on its newly allocated interfaces.

This "stop-all → reallocate → start-all" approach keeps the code simple
at the cost of a brief pause on reconfiguration — acceptable for a tool
with a small number of tasks.
"""

import logging
import threading
from typing import Any

from app.models.config import (
    ProjectConfig,
    TaskConfig,
    StandardTaskConfig,
    SpanTaskConfig,
    BeaconSequenceTaskConfig,
)
from app.sender.pool import InterfacePool, ManagedInterface
from app.sender.tasks.base import BaseTaskEngine
from app.sender.tasks.standard import StandardTaskEngine
from app.sender.tasks.span import SpanTaskEngine
from app.sender.tasks.beacon_seq import BeaconSequenceEngine
from app.sender.packets.factory import PacketFactory

logger = logging.getLogger(__name__)


class TaskManager:
    """Manages the full lifecycle of all task engines.

    Usage::

        mgr = TaskManager(pool, config)
        mgr.start_all()          # create engines + start enabled tasks
        ...
        mgr.start_task("abc1")   # enable + start one task
        mgr.stop_task("abc1")    # disable + stop one task
        mgr.stop_all()           # stop everything
    """

    def __init__(self, pool: InterfacePool, config: ProjectConfig) -> None:
        self._pool = pool
        self._config = config
        self._engines: dict[str, BaseTaskEngine] = {}
        self._lock = threading.Lock()

    # ======================== Bulk Lifecycle ======================== #

    def start_all(self) -> None:
        """Create engines for every configured task; start enabled ones."""
        with self._lock:
            for task_cfg in self._config.tasks:
                self._engines[task_cfg.id] = self._make_engine(task_cfg)
            self._rebalance_locked()

    def stop_all(self) -> None:
        """Stop every running engine."""
        with self._lock:
            for engine in self._engines.values():
                if engine.is_running:
                    engine.stop()

    # ======================== Per-Task Control ======================== #

    def start_task(self, task_id: str) -> None:
        with self._lock:
            cfg = self._find_config(task_id)
            if cfg is None:
                raise KeyError(f"Task {task_id!r} not found")
            cfg.enabled = True
            self._rebalance_locked()

    def stop_task(self, task_id: str) -> None:
        with self._lock:
            cfg = self._find_config(task_id)
            if cfg is None:
                raise KeyError(f"Task {task_id!r} not found")
            cfg.enabled = False
            engine = self._engines.get(task_id)
            if engine and engine.is_running:
                engine.stop()
            self._rebalance_locked()

    # ======================== CRUD ======================== #

    def add_task(self, task_cfg: TaskConfig) -> None:
        with self._lock:
            self._config.tasks.append(task_cfg)
            self._engines[task_cfg.id] = self._make_engine(task_cfg)
            if task_cfg.enabled:
                self._rebalance_locked()

    def remove_task(self, task_id: str) -> None:
        with self._lock:
            engine = self._engines.pop(task_id, None)
            if engine and engine.is_running:
                engine.stop()
            self._config.tasks = [t for t in self._config.tasks if t.id != task_id]
            self._rebalance_locked()

    def update_task(self, task_id: str, new_cfg: TaskConfig) -> None:
        with self._lock:
            old_engine = self._engines.pop(task_id, None)
            if old_engine and old_engine.is_running:
                old_engine.stop()
            for i, t in enumerate(self._config.tasks):
                if t.id == task_id:
                    self._config.tasks[i] = new_cfg
                    break
            self._engines[new_cfg.id] = self._make_engine(new_cfg)
            if new_cfg.enabled:
                self._rebalance_locked()

    # ======================== Status ======================== #

    def status(self) -> list[dict[str, Any]]:
        with self._lock:
            result = []
            for task_cfg in self._config.tasks:
                engine = self._engines.get(task_cfg.id)
                s: dict[str, Any] = {
                    "id": task_cfg.id,
                    "name": task_cfg.name,
                    "type": task_cfg.type,
                    "enabled": task_cfg.enabled,
                    "config": task_cfg.model_dump(),
                }
                s.update(engine.status() if engine else {
                    "running": False,
                    "packets_sent": 0,
                    "session_uptime": 0.0,
                })
                result.append(s)
            return result

    # ======================== Internal ======================== #

    def _find_config(self, task_id: str) -> TaskConfig | None:
        return next((t for t in self._config.tasks if t.id == task_id), None)

    def _make_engine(self, cfg: TaskConfig) -> BaseTaskEngine:
        if isinstance(cfg, StandardTaskConfig):
            engine = StandardTaskEngine()
            frame = PacketFactory.build(cfg.packet, cfg.channel)
            engine.load(frame, cfg.packets_per_second)
            return engine

        if isinstance(cfg, SpanTaskConfig):
            engine = SpanTaskEngine()
            first_ch = cfg.channels[0] if cfg.channels else 6
            frame = PacketFactory.build(cfg.packet, first_ch)
            engine.configure(frame, cfg.packets_per_second, cfg.channels, cfg.dwell_ms)
            return engine

        if isinstance(cfg, BeaconSequenceTaskConfig):
            engine = BeaconSequenceEngine()
            engine.configure(
                task_name=cfg.task_name,
                sequence_length=cfg.sequence_length,
                channel=cfg.channel,
                pps=cfg.packets_per_second,
                source_mac=cfg.source_mac,
                bssid=cfg.bssid,
            )
            return engine

        raise ValueError(f"Unknown task type: {cfg.type!r}")

    def _rebalance_locked(self) -> None:
        """Stop all engines, reallocate interfaces, restart enabled tasks.

        Must be called with self._lock held.
        """
        active_cfgs = [t for t in self._config.tasks if t.enabled]

        for engine in self._engines.values():
            if engine.is_running:
                engine.stop()

        if not active_cfgs or not self._pool.is_ready:
            return

        allocations = self._pool.allocate(len(active_cfgs))

        for task_cfg, ifaces in zip(active_cfgs, allocations):
            if not ifaces:
                logger.warning(
                    "Task %r has no interfaces (not enough adapters for %d active tasks)",
                    task_cfg.name,
                    len(active_cfgs),
                )
                continue

            if isinstance(task_cfg, (StandardTaskConfig, BeaconSequenceTaskConfig)):
                for iface in ifaces:
                    iface.set_channel(task_cfg.channel)

            engine = self._engines.get(task_cfg.id)
            if engine is None:
                continue
            try:
                engine.start(ifaces)
                logger.info("Task %r started on %d interface(s)", task_cfg.name, len(ifaces))
            except Exception as exc:
                logger.error("Failed to start task %r: %s", task_cfg.name, exc)
