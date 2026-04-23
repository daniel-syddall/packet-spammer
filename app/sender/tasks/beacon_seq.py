"""Beacon sequence task engine.

Each SSID in the sequence {task_name}-{seq_num}-{pos} gets exactly ONE packet.
Interfaces act as a dispatcher pool: each worker atomically claims the next
position from a shared counter, builds the frame for that SSID, sends one
packet, then immediately claims the next available position.

  seq_counter=0  → seq-1-1  claimed by wlan1
  seq_counter=1  → seq-1-2  claimed by wlan2
  seq_counter=2  → seq-1-3  claimed by wlan1   (wlan1 finished first)
  ...

Total sequence throughput ≈ n_interfaces × packets_per_second.
Minor out-of-order delivery between interfaces (e.g. seq-1-24 arriving
before seq-1-23) is expected and acceptable.
"""

import logging
import threading
import time

from app.sender.pool import ManagedInterface
from app.sender.tasks.base import BaseTaskEngine

logger = logging.getLogger(__name__)


class BeaconSequenceEngine(BaseTaskEngine):
    """Dispatcher-pool beacon sequence: one packet per SSID, split across interfaces."""

    def __init__(self) -> None:
        super().__init__()
        self._pps: int = 10
        self._task_name: str = "seq"
        self._sequence_length: int = 100
        self._channel: int = 6
        self._source_mac: str = "aa:bb:cc:dd:ee:ff"
        self._bssid: str = "aa:bb:cc:dd:ee:ff"

        # Shared position counter — each worker atomically claims the next slot.
        self._seq_counter: int = 0
        self._counter_lock = threading.Lock()

        # Display-only: last SSID dispatched to any interface (last writer wins).
        self._current_ssid: str = ""

        self._stop_event = threading.Event()
        self._workers: list[threading.Thread] = []

    # ======================== Configuration ======================== #

    def configure(
        self,
        task_name: str,
        sequence_length: int,
        channel: int,
        pps: int,
        source_mac: str,
        bssid: str,
    ) -> None:
        self._task_name = task_name
        self._sequence_length = max(1, sequence_length)
        self._channel = channel
        self._pps = max(1, pps)
        self._source_mac = source_mac
        self._bssid = bssid
        self._current_ssid = f"{task_name}-1-1"

    def update_rate(self, pps: int) -> None:
        self._pps = max(1, pps)

    # ======================== Status ======================== #

    def status(self) -> dict:
        s = super().status()
        s["current_ssid"] = self._current_ssid
        return s

    # ======================== Lifecycle ======================== #

    def start(self, interfaces: list[ManagedInterface]) -> None:
        if self._running:
            return
        if not interfaces:
            raise RuntimeError("No interfaces allocated to BeaconSequenceEngine")

        self._packets_sent = 0
        self._session_start = time.monotonic()
        self._seq_counter = 0
        self._current_ssid = f"{self._task_name}-1-1"
        self._stop_event.clear()
        self._running = True
        self._workers = []

        for iface in interfaces:
            t = threading.Thread(
                target=self._worker_loop,
                args=(iface.active,),
                name=f"bseq-{iface.active}",
                daemon=True,
            )
            t.start()
            self._workers.append(t)

        logger.info(
            "BeaconSequenceEngine started on %d interface(s) "
            "(1 packet/SSID, total rate ≈ %d pps)",
            len(interfaces),
            len(interfaces) * self._pps,
        )

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        for t in self._workers:
            if t.is_alive():
                t.join(timeout=2.0)
        self._workers = []
        logger.info(
            "BeaconSequenceEngine stopped — %d packets sent, last SSID: %s",
            self._packets_sent,
            self._current_ssid,
        )

    # ======================== Worker ======================== #

    def _claim_next(self) -> tuple[int, int]:
        """Atomically claim the next sequence position.

        Returns (seq_num, pos) where pos ∈ [1, sequence_length] and
        seq_num increments every time pos wraps around.
        """
        with self._counter_lock:
            n = self._seq_counter
            self._seq_counter += 1
        seq_num = (n // self._sequence_length) + 1
        pos     = (n % self._sequence_length) + 1
        return seq_num, pos

    def _build_frame(self, seq_num: int, pos: int):
        from scapy.layers.dot11 import RadioTap, Dot11, Dot11Beacon, Dot11Elt

        ssid = f"{self._task_name}-{seq_num}-{pos}"
        return (
            RadioTap()
            / Dot11(
                type=0,
                subtype=8,
                addr1="ff:ff:ff:ff:ff:ff",
                addr2=self._source_mac,
                addr3=self._bssid,
            )
            / Dot11Beacon(cap="ESS+privacy")
            / Dot11Elt(ID="SSID", info=ssid)
            / Dot11Elt(ID="Rates", info=b"\x82\x84\x8b\x96\x0c\x12\x18\x24")
            / Dot11Elt(ID="DSset", info=bytes([self._channel]))
        )

    def _worker_loop(self, iface: str) -> None:
        from scapy.all import sendp  # noqa: PLC0415

        next_send = time.monotonic()
        while not self._stop_event.is_set():
            now = time.monotonic()
            if now >= next_send:
                # Claim one position — this is unique to this worker at this instant.
                seq_num, pos = self._claim_next()
                self._current_ssid = f"{self._task_name}-{seq_num}-{pos}"
                frame = self._build_frame(seq_num, pos)
                try:
                    sendp(frame, iface=iface, verbose=0, count=1)
                    self._packets_sent += 1
                except OSError as exc:
                    logger.error("sendp OSError on %s: %s", iface, exc)
                    self._stop_event.wait(1.0)
                except Exception as exc:  # noqa: BLE001
                    logger.error("Unexpected send error on %s: %s", iface, exc)
                next_send += 1.0 / max(1, self._pps)
                if next_send < now - 1.0:
                    next_send = now
            else:
                self._stop_event.wait(max(0.0, next_send - now))
