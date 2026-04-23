"""Beacon sequence task engine.

Cycles through a sequence of beacon SSIDs:
  {task_name}-{seq_num}-{pos}   (pos = 1 … sequence_length)

A sequencer thread advances to the next SSID every second while worker
threads inject the current frame at the configured rate.  When the full
sequence is exhausted seq_num increments and pos resets to 1.
"""

import logging
import threading
import time

from app.sender.pool import ManagedInterface
from app.sender.tasks.base import BaseTaskEngine

logger = logging.getLogger(__name__)

_DWELL_SECONDS = 1.0  # time spent broadcasting each SSID


class BeaconSequenceEngine(BaseTaskEngine):
    """All interfaces broadcast the same SSID; a sequencer rotates through them."""

    def __init__(self) -> None:
        super().__init__()
        self._frame = None
        self._pps: int = 10
        self._task_name: str = "seq"
        self._sequence_length: int = 100
        self._channel: int = 6
        self._source_mac: str = "aa:bb:cc:dd:ee:ff"
        self._bssid: str = "aa:bb:cc:dd:ee:ff"
        self._stop_event = threading.Event()
        self._workers: list[threading.Thread] = []
        self._sequencer: threading.Thread | None = None

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
        self._frame = self._build_frame(1, 1)

    def update_rate(self, pps: int) -> None:
        self._pps = max(1, pps)

    # ======================== Lifecycle ======================== #

    def start(self, interfaces: list[ManagedInterface]) -> None:
        if self._running:
            return
        if not interfaces:
            raise RuntimeError("No interfaces allocated to BeaconSequenceEngine")

        self._packets_sent = 0
        self._session_start = time.monotonic()
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

        self._sequencer = threading.Thread(
            target=self._sequencer_loop,
            name="bseq-sequencer",
            daemon=True,
        )
        self._sequencer.start()
        logger.info("BeaconSequenceEngine started on %d interface(s)", len(interfaces))

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        for t in self._workers:
            if t.is_alive():
                t.join(timeout=2.0)
        if self._sequencer and self._sequencer.is_alive():
            self._sequencer.join(timeout=2.0)
        self._workers = []
        self._sequencer = None
        logger.info(
            "BeaconSequenceEngine stopped — %d packets this session", self._packets_sent
        )

    # ======================== Threads ======================== #

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

    def _sequencer_loop(self) -> None:
        """Advances through seq_num / pos at a fixed 1-second dwell per SSID."""
        seq_num = 1
        pos = 1
        while not self._stop_event.is_set():
            self._frame = self._build_frame(seq_num, pos)
            logger.debug(
                "BeaconSeq: ssid=%s-%d-%d", self._task_name, seq_num, pos
            )
            self._stop_event.wait(_DWELL_SECONDS)
            pos += 1
            if pos > self._sequence_length:
                pos = 1
                seq_num += 1

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
