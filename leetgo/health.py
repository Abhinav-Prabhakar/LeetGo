"""Optional HTTP health and Prometheus metrics endpoint."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from aiohttp import web

if TYPE_CHECKING:
    from .bot import LeetGo

logger = logging.getLogger("LeetGo.health")


class HealthServer:
    """Serve ``/healthz`` and ``/metrics`` for container orchestration."""

    def __init__(self, bot: LeetGo, host: str = "0.0.0.0", port: int = 0) -> None:
        self.bot = bot
        self.host = host
        self.port = port
        self._runner: web.AppRunner | None = None
        self._started_at = time.monotonic()

    async def start(self) -> None:
        """Start the server when a non-zero port is configured."""
        if self.port <= 0:
            return
        app = web.Application()
        app.router.add_get("/", self._index)
        app.router.add_get("/healthz", self._health)
        app.router.add_get("/metrics", self._metrics)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        try:
            await site.start()
        except OSError:
            logger.exception("Could not bind health server to %s:%s", self.host, self.port)
            await self._runner.cleanup()
            self._runner = None
            return
        logger.info("Health endpoint listening on http://%s:%s/healthz", self.host, self.port)

    async def stop(self) -> None:
        """Stop the HTTP server."""
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    async def _index(self, _: web.Request) -> web.Response:
        return web.json_response(
            {
                "name": "LeetGo",
                "version": self.bot.version,
                "endpoints": ["/healthz", "/metrics"],
            }
        )

    async def _health(self, _: web.Request) -> web.Response:
        database_ok = await self.bot.db.health_check()
        payload: dict[str, Any] = {
            "status": "ok" if database_ok else "degraded",
            "version": self.bot.version,
            "uptime_seconds": round(time.monotonic() - self._started_at, 1),
            "latency_ms": round(self.bot.latency * 1000, 1),
            "guilds": len(self.bot.guilds),
            "database": "ok" if database_ok else "error",
        }
        return web.json_response(payload, status=200 if database_ok else 503)

    async def _metrics(self, _: web.Request) -> web.Response:
        try:
            users = await self.bot.db.count_users()
            cohorts = await self.bot.db.count_cohorts()
            reminders = await self.bot.db.count_active_reminders()
        except Exception:  # pragma: no cover - metrics must never crash
            logger.exception("Failed to collect metrics")
            users = cohorts = reminders = 0
        lines = [
            "# HELP leetgo_up Whether the bot process is running.",
            "# TYPE leetgo_up gauge",
            "leetgo_up 1",
            "# HELP leetgo_uptime_seconds Process uptime.",
            "# TYPE leetgo_uptime_seconds gauge",
            f"leetgo_uptime_seconds {time.monotonic() - self._started_at:.1f}",
            "# HELP leetgo_guilds Number of Discord guilds.",
            "# TYPE leetgo_guilds gauge",
            f"leetgo_guilds {len(self.bot.guilds)}",
            "# HELP leetgo_linked_users Number of linked accounts.",
            "# TYPE leetgo_linked_users gauge",
            f"leetgo_linked_users {users}",
            "# HELP leetgo_cohorts Number of cohorts.",
            "# TYPE leetgo_cohorts gauge",
            f"leetgo_cohorts {cohorts}",
            "# HELP leetgo_active_reminders Number of configured reminders.",
            "# TYPE leetgo_active_reminders gauge",
            f"leetgo_active_reminders {reminders}",
        ]
        return web.Response(text="\n".join(lines) + "\n", content_type="text/plain")
