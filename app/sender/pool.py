"""Interface pool — manages all USB WiFi adapters as a shared resource.

All adapters are put into monitor mode at startup.  The pool exposes an
allocate() method that splits the adapters evenly across N active tasks.
"""

import logging
import threading
from dataclasses import dataclass, field

from app.sender.utils import (
    find_all_usb_wifi_interfaces,
    _enable_monitor_mode,
    _set_channel,
    _restore_managed,
)

logger = logging.getLogger(__name__)


@dataclass
class ManagedInterface:
    """A single USB WiFi adapter currently in monitor mode."""
    base: str      # original kernel name, e.g. "wlan1"
    active: str    # name after monitor-mode rename, e.g. "wlan1" or "wlan1mon"
    channel: int = 6

    def set_channel(self, channel: int) -> bool:
        try:
            _set_channel(self.active, channel)
            self.channel = channel
            return True
        except Exception as exc:
            logger.error("set_channel %d on %s failed: %s", channel, self.active, exc)
            return False


class InterfacePool:
    """Thread-safe pool of USB WiFi adapters in monitor mode.

    Usage::

        pool = InterfacePool()
        if pool.setup():
            slices = pool.allocate(n_tasks)   # list of lists
            ...
        pool.teardown()
    """

    def __init__(self) -> None:
        self._interfaces: list[ManagedInterface] = []
        self._lock = threading.Lock()
        self._error: str | None = None

    # ======================== Properties ======================== #

    @property
    def interfaces(self) -> list[ManagedInterface]:
        with self._lock:
            return list(self._interfaces)

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._interfaces)

    @property
    def is_ready(self) -> bool:
        with self._lock:
            return bool(self._interfaces)

    @property
    def error(self) -> str | None:
        return self._error

    # ======================== Lifecycle ======================== #

    def setup(self) -> bool:
        """Detect all USB WiFi adapters and enable monitor mode on each.

        Returns True if at least one adapter is ready.  On failure the
        web UI can still run; the error is exposed via self.error.
        """
        names = find_all_usb_wifi_interfaces()
        if not names:
            self._error = "No USB WiFi adapters found. Plug one in."
            return False

        ready: list[ManagedInterface] = []
        for name in names:
            try:
                active = _enable_monitor_mode(name)
                ready.append(ManagedInterface(base=name, active=active))
                logger.info("Interface ready: base=%s active=%s", name, active)
            except Exception as exc:
                logger.error("Monitor mode failed on %s: %s", name, exc)

        if not ready:
            self._error = "Found adapters but could not enable monitor mode on any."
            return False

        with self._lock:
            self._interfaces = ready

        self._error = None
        logger.info("Interface pool: %d adapter(s) ready", len(ready))
        return True

    def teardown(self) -> None:
        """Restore all adapters to managed mode."""
        with self._lock:
            interfaces = list(self._interfaces)
            self._interfaces = []

        for iface in interfaces:
            logger.info("Restoring %s to managed mode", iface.active)
            try:
                _restore_managed(iface.active)
            except Exception as exc:
                logger.warning("Teardown error on %s (non-fatal): %s", iface.active, exc)

    # ======================== Allocation ======================== #

    def allocate(self, n_tasks: int) -> list[list[ManagedInterface]]:
        """Split the interface pool evenly across n_tasks active tasks.

        Returns a list of n_tasks sublists.  The first (N % n_tasks) tasks
        each receive one extra adapter when the count doesn't divide evenly.
        Returns a list of empty lists if the pool is empty or n_tasks is 0.
        """
        with self._lock:
            interfaces = list(self._interfaces)

        if not interfaces or n_tasks <= 0:
            return [[] for _ in range(max(0, n_tasks))]

        n = len(interfaces)
        base, remainder = divmod(n, n_tasks)
        result: list[list[ManagedInterface]] = []
        idx = 0
        for i in range(n_tasks):
            count = base + (1 if i < remainder else 0)
            result.append(interfaces[idx: idx + count])
            idx += count
        return result

    # ======================== Status ======================== #

    def status(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "base": iface.base,
                    "active": iface.active,
                    "channel": iface.channel,
                }
                for iface in self._interfaces
            ]
