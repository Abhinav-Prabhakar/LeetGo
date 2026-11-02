"""Concurrent, cached leaderboard aggregation."""

from __future__ import annotations

import asyncio
import logging
import time

from .errors import LeetCodeError
from .leetcode import LeetCodeClient
from .models import LeaderboardEntry, UserRecord

logger = logging.getLogger("LeetGo.leaderboard")


class LeaderboardService:
    """Fetch many profiles concurrently and cache the ranked result."""

    def __init__(self, client: LeetCodeClient, ttl: float = 300.0) -> None:
        self.client = client
        self.ttl = ttl
        self._cache: dict[str, tuple[float, list[LeaderboardEntry]]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _key(members: list[UserRecord]) -> str:
        return "|".join(
            f"{member.user_id}:{member.lc_username.lower()}"
            for member in sorted(members, key=lambda item: item.user_id or 0)
        )

    async def fetch(self, members: list[UserRecord]) -> list[LeaderboardEntry]:
        """Return ranked entries, reusing a recent result when possible."""
        if not members:
            return []
        key = self._key(members)
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and cached[0] > now:
            return cached[1]

        async with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] > now:
                return cached[1]
            entries = await asyncio.gather(*(self._fetch_one(member) for member in members))
            ranked = sorted(entries, key=lambda entry: entry.total_solved, reverse=True)
            self._cache[key] = (now + self.ttl, ranked)
            if len(self._cache) > 100:
                self._prune()
            return ranked

    async def _fetch_one(self, member: UserRecord) -> LeaderboardEntry:
        try:
            profile = await self.client.fetch_profile(member.lc_username, recent_limit=0)
            return LeaderboardEntry(
                user_id=member.user_id or 0,
                lc_username=profile.username or member.lc_username,
                total_solved=profile.total_solved,
                easy=profile.easy.solved,
                medium=profile.medium.solved,
                hard=profile.hard.solved,
                ranking=profile.ranking,
                contest_rating=profile.contest.rating if profile.contest else None,
            )
        except LeetCodeError as exc:
            logger.warning("Leaderboard fetch failed for %s: %s", member.lc_username, exc)
            return LeaderboardEntry(
                user_id=member.user_id or 0,
                lc_username=member.lc_username,
                total_solved=0,
                error=str(exc),
            )

    def _prune(self) -> None:
        now = time.monotonic()
        self._cache = {key: value for key, value in self._cache.items() if value[0] > now}

    def invalidate(self) -> None:
        """Drop every cached leaderboard."""
        self._cache.clear()
