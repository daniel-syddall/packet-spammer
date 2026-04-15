"""USB WiFi interface manager.

Responsibilities:
  1. Scan /sys/class/net for wireless interfaces whose device path routes
     through a USB bus (i.e., a USB dongle, not the Pi's built-in chip).
  2. Put the selected interface into monitor mode.
  3. Set the target 802.11 channel.
  4. Restore managed mode on teardown.

The first USB wireless interface found is used. Only one is expected.
"""

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


# ======================== Detection helpers ======================== #

def _is_wireless(iface: str) -> bool:
    """Return True if this interface has an 802.11 PHY backing it."""
    return (
        Path(f"/sys/class/net/{iface}/wireless").exists()
        or Path(f"/sys/class/net/{iface}/phy80211").exists()
    )


def _is_usb(iface: str) -> bool:
    """Return True if this wireless interface is attached via USB.

    We resolve the /sys/class/net/<iface>/device symlink and check whether
    the real path passes through a USB subsystem directory.  The Pi's
    built-in BCM chip sits on the SDIO bus whose path contains 'mmc' or
    'platform', never 'usb', so this reliably distinguishes dongles.
    """
    device_link = Path(f"/sys/class/net/{iface}/device")
    if not device_link.exists():
        return False
    try:
        real_path = str(device_link.resolve())
        return "usb" in real_path.lower()
    except OSError:
        return False


def find_usb_wifi_interface() -> str | None:
    """Return the name of the first USB wireless interface found, or None."""
    try:
        ifaces = sorted(os.listdir("/sys/class/net"))
    except OSError:
        logger.error("Cannot read /sys/class/net — are we running as root?")
        return None

    for iface in ifaces:
        if _is_wireless(iface) and _is_usb(iface):
            logger.info("Found USB WiFi interface: %s", iface)
            return iface

    logger.warning("No USB WiFi interface detected")
    return None


# ======================== Interface Manager ======================== #

def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    logger.debug("$ %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd, result.stdout, result.stderr
        )
    return result


class InterfaceManager:
    """Manage a single USB WiFi adapter for raw 802.11 frame injection.

    Usage::

        mgr = InterfaceManager()
        ok  = mgr.setup(channel=6)   # find adapter, enable monitor mode
        if ok:
            mgr.set_channel(11)      # hot-change channel
        mgr.teardown()               # restore managed mode on exit
    """

    def __init__(self) -> None:
        self._iface: str | None = None     # name of the interface (in monitor mode)
        self._base_iface: str | None = None  # original name before any rename
        self._channel: int = 6
        self._error: str | None = None

    # ======================== Properties ======================== #

    @property
    def interface(self) -> str | None:
        """Active interface name (in monitor mode), or None if not ready."""
        return self._iface

    @property
    def is_ready(self) -> bool:
        """True once the interface is in monitor mode and ready for injection."""
        return self._iface is not None

    @property
    def channel(self) -> int:
        return self._channel

    @property
    def error(self) -> str | None:
        """Last setup error message, or None."""
        return self._error

    # ======================== Setup ======================== #

    def setup(self, channel: int) -> bool:
        """Find the USB adapter, enable monitor mode, and set the channel.

        Returns True on success.  On failure, sets self.error and returns False.
        The API server continues running even when this returns False so the
        web UI can display the error.
        """
        self._channel = channel
        self._error = None

        iface = find_usb_wifi_interface()
        if iface is None:
            self._error = "No USB WiFi adapter found. Plug one in and restart."
            return False

        self._base_iface = iface

        try:
            self._enable_monitor_mode(iface)
        except Exception as exc:
            self._error = f"Failed to enable monitor mode on {iface}: {exc}"
            logger.error(self._error)
            return False

        # After mode change, some drivers rename the interface (e.g. wlan1mon).
        # Detect the actual active name.
        active = self._resolve_active_iface(iface)
        self._iface = active

        try:
            self._set_channel_raw(active, channel)
        except Exception as exc:
            # Non-fatal: log a warning but don't abort. The user can change the
            # channel after startup.
            logger.warning("Channel %d set failed on %s: %s", channel, active, exc)

        logger.info(
            "Interface ready — iface=%s  mode=monitor  channel=%d",
            active, channel,
        )
        return True

    def set_channel(self, channel: int) -> bool:
        """Change the operating channel on the live monitor interface."""
        if not self._iface:
            return False
        try:
            self._set_channel_raw(self._iface, channel)
            self._channel = channel
            logger.info("Channel changed to %d on %s", channel, self._iface)
            return True
        except Exception as exc:
            logger.error("set_channel failed: %s", exc)
            return False

    # ======================== Teardown ======================== #

    def teardown(self) -> None:
        """Restore the adapter to managed mode."""
        iface = self._iface or self._base_iface
        if not iface:
            return
        logger.info("Restoring %s to managed mode", iface)
        try:
            _run(["ip",  "link", "set", iface, "down"], check=False)
            _run(["iw",  "dev",  iface, "set", "type", "managed"], check=False)
            _run(["ip",  "link", "set", iface, "up"],   check=False)
        except Exception as exc:
            logger.warning("Teardown error (non-fatal): %s", exc)
        self._iface = None

    # ======================== Internal helpers ======================== #

    def _enable_monitor_mode(self, iface: str) -> None:
        """Bring the interface down, switch to monitor, bring back up."""
        _run(["ip",  "link", "set", iface, "down"])
        _run(["iw",  "dev",  iface, "set", "type", "monitor"])
        _run(["ip",  "link", "set", iface, "up"])

    def _set_channel_raw(self, iface: str, channel: int) -> None:
        _run(["iw", "dev", iface, "set", "channel", str(channel)])

    @staticmethod
    def _resolve_active_iface(base: str) -> str:
        """Some drivers rename the interface after a mode change (e.g. wlan1mon).
        Check for the renamed variant; fall back to the original name.
        """
        candidate = f"{base}mon"
        if Path(f"/sys/class/net/{candidate}").exists():
            return candidate
        return base
