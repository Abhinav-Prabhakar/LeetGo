"""Live health and metrics endpoint tests."""

from __future__ import annotations

import socket
from types import SimpleNamespace

import aiohttp

from leetgo.db import Database
from leetgo.health import HealthServer


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def test_health_server_serves_status_and_metrics(db: Database) -> None:
    await db.link_user(1, "alice", "alice_lc")
    await db.create_cohort("Night Owls", 10, 100, 1)
    bot = SimpleNamespace(
        db=db,
        version="3.0.0",
        latency=0.042,
        guilds=[object(), object()],
    )
    port = free_port()
    server = HealthServer(bot, "127.0.0.1", port)  # type: ignore[arg-type]
    await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{port}/") as response:
                assert response.status == 200
                index = await response.json()
                assert index["name"] == "LeetGo"
                assert index["version"] == "3.0.0"
            async with session.get(f"http://127.0.0.1:{port}/healthz") as response:
                assert response.status == 200
                payload = await response.json()
                assert payload["status"] == "ok"
                assert payload["database"] == "ok"
                assert payload["guilds"] == 2
            async with session.get(f"http://127.0.0.1:{port}/metrics") as response:
                assert response.status == 200
                metrics = await response.text()
                assert "leetgo_up 1" in metrics
                assert "leetgo_guilds 2" in metrics
                assert "leetgo_linked_users 1" in metrics
                assert "leetgo_cohorts 1" in metrics
                assert "leetgo_active_reminders 0" in metrics
    finally:
        await server.stop()


async def test_health_server_reports_degraded_database(db: Database) -> None:
    bot = SimpleNamespace(db=db, version="3.0.0", latency=0.0, guilds=[])
    port = free_port()
    server = HealthServer(bot, "127.0.0.1", port)  # type: ignore[arg-type]
    await server.start()
    await db.close()
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(f"http://127.0.0.1:{port}/healthz") as response,
        ):
            assert response.status == 503
            payload = await response.json()
            assert payload["status"] == "degraded"
            assert payload["database"] == "error"
    finally:
        await server.stop()


async def test_health_server_disabled_without_port(db: Database) -> None:
    bot = SimpleNamespace(db=db, version="3.0.0", latency=0.0, guilds=[])
    server = HealthServer(bot, "127.0.0.1", 0)  # type: ignore[arg-type]
    await server.start()
    assert server._runner is None
    await server.stop()
