"""Shared subprocess helpers for 802.11 interface management."""

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    logger.debug("$ %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd, result.stdout, result.stderr
        )
    return result


def _enable_monitor_mode(iface: str) -> str:
    """Put iface into monitor mode and return the active interface name.

    Some drivers rename wlan1 → wlan1mon after the mode change; this
    function detects that and returns whichever name is now active.
    """
    _run(["ip", "link", "set", iface, "down"])
    _run(["iw", "dev", iface, "set", "type", "monitor"])
    _run(["ip", "link", "set", iface, "up"])
    return _resolve_active_iface(iface)


def _set_channel(iface: str, channel: int) -> None:
    _run(["iw", "dev", iface, "set", "channel", str(channel)])


def _restore_managed(iface: str) -> None:
    _run(["ip", "link", "set", iface, "down"], check=False)
    _run(["iw", "dev", iface, "set", "type", "managed"], check=False)
    _run(["ip", "link", "set", iface, "up"], check=False)


def _resolve_active_iface(base: str) -> str:
    """Return the post-mode-change interface name (handles wlan1mon rename)."""
    candidate = f"{base}mon"
    if Path(f"/sys/class/net/{candidate}").exists():
        return candidate
    return base


def _is_wireless(iface: str) -> bool:
    return (
        Path(f"/sys/class/net/{iface}/wireless").exists()
        or Path(f"/sys/class/net/{iface}/phy80211").exists()
    )


def _is_usb(iface: str) -> bool:
    """True if this wireless interface is attached via USB.

    Resolves the device symlink and checks whether the real path passes
    through a USB subsystem directory.  The Pi's built-in BCM chip sits
    on the SDIO bus whose path contains 'mmc' or 'platform', never 'usb'.
    """
    device_link = Path(f"/sys/class/net/{iface}/device")
    if not device_link.exists():
        return False
    try:
        real_path = str(device_link.resolve())
        return "usb" in real_path.lower()
    except OSError:
        return False


def find_all_usb_wifi_interfaces() -> list[str]:
    """Return the names of all USB wireless interfaces found in /sys/class/net."""
    try:
        ifaces = sorted(os.listdir("/sys/class/net"))
    except OSError:
        logger.error("Cannot read /sys/class/net — are we running as root?")
        return []

    found = [iface for iface in ifaces if _is_wireless(iface) and _is_usb(iface)]

    if found:
        logger.info("Found USB WiFi interface(s): %s", ", ".join(found))
    else:
        logger.warning("No USB WiFi interfaces detected")
    return found
