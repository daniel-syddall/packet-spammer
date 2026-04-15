"""Host Runtime.

Coordinates all subsystems:
  • InterfaceManager  — USB WiFi detection + monitor mode
  • SenderEngine      — background packet injection thread
  • APIServer         — FastAPI/Uvicorn web server
  • Interface watchdog — retries adapter discovery every 10 s if not found

Typical call site::

    config  = load_config("config/config.toml", ProjectConfig)
    runtime = HostRuntime(config, config_path=Path("config/config.toml"))
    asyncio.run(runtime.run())
"""

import asyncio
import logging
from pathlib import Path

from base.api import APIServer, base_router, init_base_routes
from base.config import save_config
from app.models.config import ProjectConfig
from app.sender.engine import SenderEngine
from app.sender.interface import InterfaceManager
from app.sender.packets.factory import PacketFactory
from app.api.routes import router as project_router, init_project_routes

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent.parent.parent / "base" / "api" / "static"


class HostRuntime:
    """Encapsulates the full host lifecycle."""

    def __init__(
        self,
        config: ProjectConfig,
        config_path: Path | None = None,
    ) -> None:
        self._config = config
        self._config_path = config_path

        self._iface_mgr = InterfaceManager()
        self._engine    = SenderEngine()
        self._api       = APIServer(config.api, title="Packet Spammer")

    # ======================== Lifecycle ======================== #

    async def run(self) -> None:
        """Start all subsystems and run until cancelled."""
        # ── Interface setup ──────────────────────────────────────────── #
        logger.info("Searching for USB WiFi adapter...")
        interface_ready = await asyncio.to_thread(
            self._iface_mgr.setup, self._config.sender.channel
        )

        if interface_ready:
            self._load_engine()
            if self._config.sender.autostart:
                logger.info("Autostart enabled — beginning transmission immediately")
                self._engine.start(self._iface_mgr.interface)
        else:
            logger.warning(
                "Interface not ready at startup: %s", self._iface_mgr.error
            )
            logger.info("Web UI still available — start transmission once adapter is found")

        # ── API setup ────────────────────────────────────────────────── #
        self._setup_api()

        # ── Task group ───────────────────────────────────────────────── #
        tasks = [
            self._api.start(),
            self._interface_watchdog(),
        ]

        try:
            await asyncio.gather(*tasks)
        finally:
            logger.info("Shutting down...")
            if self._engine.is_running:
                await asyncio.to_thread(self._engine.stop)
            self._iface_mgr.teardown()
            await self._api.stop()
            logger.info("Shutdown complete")

    # ======================== API Setup ======================== #

    def _setup_api(self) -> None:
        """Wire all routes into the FastAPI app."""
        init_base_routes(extras_fn=self._status_extras)
        self._api.app.include_router(base_router)

        init_project_routes(
            engine=self._engine,
            iface_mgr=self._iface_mgr,
            config=self._config,
            save_config_fn=self._save_config,
        )
        self._api.app.include_router(project_router)

        from fastapi.responses import FileResponse

        @self._api.app.get("/")
        async def dashboard():
            return FileResponse(str(STATIC_DIR / "index.html"))

        self._api.mount_static(STATIC_DIR)

    # ======================== Helpers ======================== #

    def _load_engine(self) -> None:
        """Build the Scapy frame from current config and prime the engine."""
        frame = PacketFactory.build(self._config.packet, self._config.sender.channel)
        self._engine.load(frame, self._config.sender.packets_per_second)

    def _save_config(self) -> None:
        """Persist the in-memory config back to disk."""
        if not self._config_path:
            logger.warning("No config path set — changes not saved to disk")
            return
        save_config(self._config_path, self._config)
        logger.info("Config saved → %s", self._config_path)

    def _status_extras(self) -> dict:
        """Extra fields for GET /api/status."""
        return {
            "sender_running":   self._engine.is_running,
            "interface":        self._iface_mgr.interface,
            "interface_ready":  self._iface_mgr.is_ready,
        }

    # ======================== Interface Watchdog ======================== #

    async def _interface_watchdog(self) -> None:
        """Periodically try to find and configure the USB adapter.

        Only runs while the interface is not ready, so there is no overhead
        once the adapter is in use.  Retries every 10 seconds.
        """
        while True:
            await asyncio.sleep(10)

            if self._iface_mgr.is_ready:
                # Interface is healthy — nothing to do.
                continue

            logger.info("Watchdog: retrying USB WiFi adapter search...")
            success = await asyncio.to_thread(
                self._iface_mgr.setup, self._config.sender.channel
            )

            if success:
                logger.info(
                    "Watchdog: adapter found (%s) — engine ready",
                    self._iface_mgr.interface,
                )
                self._load_engine()
                if self._config.sender.autostart and not self._engine.is_running:
                    self._engine.start(self._iface_mgr.interface)
