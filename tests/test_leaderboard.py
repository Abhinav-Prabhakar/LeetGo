"""Leaderboard aggregation and caching tests."""

from __future__ import annotations

from typing import Any

from leetgo.errors import ServiceUnavailableError
from leetgo.leaderboard import LeaderboardService
from leetgo.leetcode import UserProfile


class FakeClient:
    def __init__(self) -> None:
        self.calls = 0

    async def fetch_profile(self, username: str, recent_limit: int = 0) -> UserProfile:
        self.calls += 1
        if username == "bad":
            raise ServiceUnavailableError("down")
        solved = {"alice": 100, "bob": 250}[username]
        return UserProfile(
            username=username,
            real_name=None,
            avatar_url=None,
            country=None,
            company=None,
            school=None,
            ranking=None,
            reputation=0,
            star_rating=None,
            total_solved=solved,
            total_questions=3000,
        )


async def test_leaderboard_sorts_and_caches(make_user: Any) -> None:
    client = FakeClient()
    service = LeaderboardService(client, ttl=60)  # type: ignore[arg-type]
    members = [make_user(1, "alice"), make_user(2, "bob")]

    entries = await service.fetch(members)
    assert [entry.lc_username for entry in entries] == ["bob", "alice"]
    assert client.calls == 2

    again = await service.fetch(members)
    assert again is entries
    assert client.calls == 2

    service.invalidate()
    await service.fetch(members)
    assert client.calls == 4


async def test_leaderboard_handles_failures(make_user: Any) -> None:
    client = FakeClient()
    service = LeaderboardService(client, ttl=60)  # type: ignore[arg-type]
    entries = await service.fetch([make_user(1, "bad"), make_user(2, "alice")])
    assert entries[0].lc_username == "alice"
    failed = next(entry for entry in entries if entry.lc_username == "bad")
    assert failed.error is not None


async def test_leaderboard_empty() -> None:
    service = LeaderboardService(FakeClient(), ttl=60)  # type: ignore[arg-type]
    assert await service.fetch([]) == []
