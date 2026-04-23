"""Span task engine — staggered multi-channel cycling across interfaces."""

import logging
import threading
import time

from app.sender.pool import ManagedInterface
from app.sender.tasks.base import BaseTaskEngine
from app.sender.utils import _set_channel

logger = logging.getLogger(__name__)


class SpanTaskEngine(BaseTaskEngine):
    """Each allocated interface cycles through a channel list independently.

    Staggered start: worker i begins at channel_list[i % len(channels)], giving
    simultaneous multi-channel coverage across the adapter pool.

    Within each dwell window the worker injects frames at the configured rate.
    On a channel hop the interface channel is changed via iw, then injection
    resumes for the next dwell_ms milliseconds.
    """

    def __init__(self) -> None:
        super().__init__()
        self._frame = None
        self._pps: int = 10
        self._channels: list[int] = [1, 6, 11]
        self._dwell_ms: int = 1000
        self._stop_event = threading.Event()
        self._workers: list[threading.Thread] = []

    # ======================== Configuration ======================== #

    def configure(
        self,
        frame,
        pps: int,
        channels: list[int],
        dwell_ms: int,
    ) -> None:
        self._frame = frame
        self._pps = max(1, pps)
        self._channels = channels if channels else [1, 6, 11]
        self._dwell_ms = max(100, dwell_ms)

    def update_frame(self, frame) -> None:
        self._frame = frame

    def update_rate(self, pps: int) -> None:
        self._pps = max(1, pps)

    # ======================== Lifecycle ======================== #

    def start(self, interfaces: list[ManagedInterface]) -> None:
        if self._running:
            return
        if not interfaces:
            raise RuntimeError("No interfaces allocated to SpanTaskEngine")

        self._packets_sent = 0
        self._session_start = time.monotonic()
        self._stop_event.clear()
        self._running = True
        self._workers = []

        for idx, iface in enumerate(interfaces):
            start_offset = idx % len(self._channels)
            t = threading.Thread(
                target=self._span_worker,
                args=(iface.active, start_offset),
                name=f"span-{iface.active}",
                daemon=True,
            )
            t.start()
            self._workers.append(t)

        logger.info("SpanTaskEngine started on %d interface(s)", len(interfaces))

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        for t in self._workers:
            if t.is_alive():
                t.join(timeout=3.0)
        self._workers = []
        logger.info("SpanTaskEngine stopped — %d packets this session", self._packets_sent)

    # ======================== Worker ======================== #

    def _span_worker(self, iface: str, start_offset: int) -> None:
        from scapy.all import sendp  # noqa: PLC0415

        ch_idx = start_offset
        channels = self._channels

        while not self._stop_event.is_set():
            ch = channels[ch_idx % len(channels)]
            try:
                _set_channel(iface, ch)
            except Exception as exc:
                logger.warning("Channel %d set failed on %s: %s", ch, iface, exc)

            dwell_end = time.monotonic() + self._dwell_ms / 1000.0
            next_send = time.monotonic()

            while not self._stop_event.is_set() and time.monotonic() < dwell_end:
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
                            break
                        except Exception as exc:  # noqa: BLE001
                            logger.error("Unexpected send error on %s: %s", iface, exc)
                    next_send += 1.0 / max(1, pps)
                    if next_send < now - 1.0:
                        next_send = now
                else:
                    remaining = dwell_end - time.monotonic()
                    sleep_for = min(next_send - now, remaining)
                    self._stop_event.wait(max(0.0, sleep_for))

            ch_idx += 1
