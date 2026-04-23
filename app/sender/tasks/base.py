"""Abstract base class for all task engines."""

import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.sender.pool import ManagedInterface


class BaseTaskEngine(ABC):
    """Common interface for StandardTaskEngine, SpanTaskEngine, BeaconSequenceEngine."""

    def __init__(self) -> None:
        self._running: bool = False
        self._packets_sent: int = 0
        self._session_start: float = 0.0

    @abstractmethod
    def start(self, interfaces: "list[ManagedInterface]") -> None:
        """Begin injection on the given set of interfaces."""

    @abstractmethod
    def stop(self) -> None:
        """Signal all threads to stop and block until they exit."""

    @abstractmethod
    def update_rate(self, pps: int) -> None:
        """Hot-change the injection rate while running."""

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def packets_sent(self) -> int:
        return self._packets_sent

    @property
    def session_uptime(self) -> float:
        if self._running and self._session_start:
            return time.monotonic() - self._session_start
        return 0.0

    def status(self) -> dict:
        uptime = self.session_uptime
        actual_pps = round(self._packets_sent / uptime, 1) if uptime > 0 else 0.0
        return {
            "running": self._running,
            "packets_sent": self._packets_sent,
            "session_uptime": round(uptime, 1),
            "actual_pps": actual_pps,
        }
