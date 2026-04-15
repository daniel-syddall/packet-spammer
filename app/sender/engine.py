"""Packet sender engine.

Runs a dedicated background thread that injects Scapy frames at a
precisely-controlled rate.  The asyncio runtime interacts with the
engine through simple synchronous methods — thread-safety is ensured
by the GIL for attribute reads and by an explicit threading.Event for
shutdown signalling.

Design decisions
----------------
* A dedicated thread (not asyncio.to_thread) avoids scheduler jitter
  at the sub-millisecond level that asyncio sleep precision can't always
  guarantee for high packet rates.
* Rate accuracy uses a monotonic next-send accumulator instead of a
  plain sleep(interval) so that send-execution time does not drift the
  schedule.
* The Scapy import is deferred to the thread body so that Python's
  import machinery doesn't block the initial server startup.
"""

import logging
import threading
import time

logger = logging.getLogger(__name__)


class SenderEngine:
    """Background-thread 802.11 frame injector.

    Lifecycle::

        engine = SenderEngine()
        engine.load(frame, packets_per_second=10)
        engine.start(interface="wlan1")   # non-blocking
        ...
        engine.update_rate(20)            # hot-change, takes effect immediately
        engine.update_frame(new_frame)    # hot-change, takes effect on next send
        ...
        engine.stop()                     # blocks ≤ 2 s waiting for thread exit
    """

    def __init__(self) -> None:
        self._frame = None
        self._pps: int = 10
        self._iface: str = ""

        self._running: bool = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        # Stats (written only from the send thread, read from main thread — safe
        # under the GIL for simple int/float assignments).
        self._packets_sent: int = 0
        self._session_start: float = 0.0

    # ======================== Public Interface ======================== #

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def packets_sent(self) -> int:
        return self._packets_sent

    @property
    def session_uptime(self) -> float:
        """Seconds since the current session started, or 0 if stopped."""
        if self._running and self._session_start:
            return time.monotonic() - self._session_start
        return 0.0

    @property
    def packets_per_second(self) -> int:
        return self._pps

    def load(self, frame, packets_per_second: int) -> None:
        """Prepare a new frame and rate before calling start().

        Also safe to call while running — changes take effect on the next
        send-loop iteration without restarting the thread.
        """
        self._frame = frame
        self._pps = max(1, packets_per_second)

    def update_frame(self, frame) -> None:
        """Hot-swap the frame.  Thread-safe under the GIL."""
        self._frame = frame

    def update_rate(self, packets_per_second: int) -> None:
        """Hot-change the send rate.  Thread-safe under the GIL."""
        self._pps = max(1, packets_per_second)

    def start(self, interface: str) -> None:
        """Start the background send thread.

        No-op if already running.  Resets the packet counter and uptime.
        """
        if self._running:
            return
        if not interface:
            raise RuntimeError("No interface specified — call setup() first")

        self._iface = interface
        self._packets_sent = 0
        self._session_start = time.monotonic()
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(
            target=self._send_loop,
            name="sender-loop",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Sender started — iface=%s  rate=%d pps  frame_type=%s",
            interface,
            self._pps,
            type(self._frame).__name__ if self._frame is not None else "None",
        )

    def stop(self) -> None:
        """Signal the send thread to stop and wait for it to exit (≤ 2 s).

        Blocking — callers from async code should use asyncio.to_thread(engine.stop).
        """
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        logger.info("Sender stopped — total packets this session: %d", self._packets_sent)

    # ======================== Send Loop ======================== #

    def _send_loop(self) -> None:
        """Inner loop — runs in the dedicated thread."""
        # Defer Scapy import to here so the web server starts quickly.
        from scapy.all import sendp  # noqa: PLC0415

        iface = self._iface
        next_send = time.monotonic()

        while not self._stop_event.is_set():
            now = time.monotonic()

            if now >= next_send:
                frame = self._frame
                pps   = self._pps

                if frame is not None:
                    try:
                        sendp(frame, iface=iface, verbose=0, count=1)
                        self._packets_sent += 1
                    except OSError as exc:
                        # Interface might have disappeared (e.g. dongle unplugged).
                        logger.error("sendp OSError (is the adapter still plugged in?): %s", exc)
                        self._stop_event.wait(1.0)   # brief back-off
                    except Exception as exc:          # noqa: BLE001
                        logger.error("Unexpected send error: %s", exc)

                # Advance the accumulator regardless — prevents a burst of frames
                # if the send itself took longer than one interval.
                next_send += 1.0 / max(1, pps)

                # If we've fallen behind by more than 1 s (e.g. after a long
                # OS scheduling pause) reset the accumulator to now so we don't
                # send a burst to catch up.
                if next_send < now - 1.0:
                    next_send = now

            else:
                # Sleep until the next scheduled send, but wake up immediately
                # if stop() is called.
                self._stop_event.wait(max(0.0, next_send - now))

        logger.debug("Send loop exited cleanly")
