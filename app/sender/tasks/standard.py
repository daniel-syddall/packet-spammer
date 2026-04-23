"""Standard task engine — fixed packet, fixed channel, N workers."""

import logging
import threading
import time

from app.sender.pool import ManagedInterface
from app.sender.tasks.base import BaseTaskEngine

logger = logging.getLogger(__name__)


class StandardTaskEngine(BaseTaskEngine):
    """Injects a single 802.11 frame type at a configured rate on a fixed channel.

    One worker thread is spawned per allocated interface.  The frame and rate
    can be hot-swapped while the engine is running.
    """

    def __init__(self) -> None:
        super().__init__()
        self._frame = None
        self._pps: int = 10
        self._stop_event = threading.Event()
        self._workers: list[threading.Thread] = []

    # ======================== Configuration ======================== #

    def load(self, frame, pps: int) -> None:
        """Set the initial frame and rate before calling start()."""
        self._frame = frame
        self._pps = max(1, pps)

    def update_frame(self, frame) -> None:
        """Hot-swap the Scapy frame. Thread-safe under the GIL."""
        self._frame = frame

    def update_rate(self, pps: int) -> None:
        """Hot-change the send rate. Thread-safe under the GIL."""
        self._pps = max(1, pps)

    # ======================== Lifecycle ======================== #

    def start(self, interfaces: list[ManagedInterface]) -> None:
        if self._running:
            return
        if not interfaces:
            raise RuntimeError("No interfaces allocated to StandardTaskEngine")

        self._packets_sent = 0
        self._session_start = time.monotonic()
        self._stop_event.clear()
        self._running = True
        self._workers = []

        for iface in interfaces:
            t = threading.Thread(
                target=self._worker_loop,
                args=(iface.active,),
                name=f"std-{iface.active}",
                daemon=True,
            )
            t.start()
            self._workers.append(t)

        logger.info("StandardTaskEngine started on %d interface(s)", len(interfaces))

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        for t in self._workers:
            if t.is_alive():
                t.join(timeout=2.0)
        self._workers = []
        logger.info("StandardTaskEngine stopped — %d packets this session", self._packets_sent)

    # ======================== Send Loop ======================== #

    def _worker_loop(self, iface: str) -> None:
        from scapy.all import sendp  # noqa: PLC0415

        next_send = time.monotonic()
        while not self._stop_event.is_set():
            now = time.monotonic()
            if now >= next_send:
                frame = self._frame
                pps = self._pps
                if frame is not None:
                    try:
                        sendp(frame, iface=iface, verbose=0, count=1)
                        self._packets_sent += 1
                    except OSError as exc:
                        logger.error("sendp OSError on %s: %s", iface, exc)
                        self._stop_event.wait(1.0)
                    except Exception as exc:  # noqa: BLE001
                        logger.error("Unexpected send error on %s: %s", iface, exc)
                next_send += 1.0 / max(1, pps)
                if next_send < now - 1.0:
                    next_send = now
            else:
                self._stop_event.wait(max(0.0, next_send - now))
