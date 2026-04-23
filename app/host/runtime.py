"""Host Runtime.

Coordinates all subsystems:
  • InterfacePool   — USB WiFi detection + monitor mode for all adapters
  • TaskManager     — creates, allocates, and lifecycles task engines
  • APIServer       — FastAPI/Uvicorn web server
  • Pool watchdog   — retries adapter discovery every 10 s if pool is empty

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
from app.sender.pool import InterfacePool
from app.sender.tasks.manager import TaskManager
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
        self._pool = InterfacePool()
        self._task_mgr = TaskManager(self._pool, config)
        self._api = APIServer(config.api, title="Packet Spammer")

    # ======================== Lifecycle ======================== #

    async def run(self) -> None:
        """Start all subsystems and run until cancelled."""
        # Apply autostart: tasks with autostart=True are enabled on every boot,
        # regardless of the last saved enabled state.
        autostart_count = 0
        for task in self._config.tasks:
            if task.autostart and not task.enabled:
                task.enabled = True
                autostart_count += 1
        if autostart_count:
            logger.info("Autostart: enabled %d task(s)", autostart_count)
            self._save_config()

        logger.info("Searching for USB WiFi adapters...")
        pool_ready = await asyncio.to_thread(self._pool.setup)

        if pool_ready:
            logger.info("Pool ready with %d adapter(s)", self._pool.count)
            await asyncio.to_thread(self._task_mgr.start_all)
        else:
            logger.warning("Pool not ready at startup: %s", self._pool.error)
            logger.info("Web UI still available — start tasks once adapters are found")

        self._setup_api()

        try:
            await asyncio.gather(
                self._api.start(),
                self._pool_watchdog(),
            )
        finally:
            logger.info("Shutting down...")
            await asyncio.to_thread(self._task_mgr.stop_all)
            self._pool.teardown()
            await self._api.stop()
            logger.info("Shutdown complete")

    # ======================== API Setup ======================== #

    def _setup_api(self) -> None:
        init_base_routes(extras_fn=self._status_extras)
        self._api.app.include_router(base_router)

        init_project_routes(
            pool=self._pool,
            task_mgr=self._task_mgr,
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

    def _save_config(self) -> None:
        if not self._config_path:
            logger.warning("No config path — changes not saved to disk")
            return
        save_config(self._config_path, self._config)
        logger.info("Config saved → %s", self._config_path)

    def _status_extras(self) -> dict:
        return {
            "pool_ready": self._pool.is_ready,
            "pool_count": self._pool.count,
        }

    # ======================== Pool Watchdog ======================== #

    async def _pool_watchdog(self) -> None:
        """Retry USB adapter discovery every 10 s when the pool is empty."""
        while True:
            await asyncio.sleep(10)

            if self._pool.is_ready:
                continue

            logger.info("Watchdog: retrying USB WiFi adapter search...")
            success = await asyncio.to_thread(self._pool.setup)

            if success:
                logger.info(
                    "Watchdog: pool ready with %d adapter(s) — starting enabled tasks",
                    self._pool.count,
                )
                await asyncio.to_thread(self._task_mgr.start_all)
