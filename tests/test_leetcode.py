"""LeetCode GraphQL parsing, caching and resilience tests."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from leetgo.errors import (
    InvalidUsernameError,
    LeetCodeError,
    RateLimitedError,
    ServiceUnavailableError,
    UserNotFoundError,
)
from leetgo.leetcode import (
    LeetCodeClient,
    parse_daily,
    parse_profile,
    validate_username,
)


class FakeResponse:
    """Minimal async-context-manager stand-in for an aiohttp response."""

    def __init__(
        self,
        status: int = 200,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self._payload = payload or {}
        self.headers = headers or {}

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def json(self, content_type: str | None = None) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise RuntimeError(f"unexpected HTTP {self.status}")


class FakeSession:
    """Queue of canned responses consumed one request at a time."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.requests = 0
        self.closed = False

    def post(self, *_: Any, **__: Any) -> FakeResponse:
        self.requests += 1
        return self._responses.pop(0)

    async def close(self) -> None:
        self.closed = True


def make_client(responses: list[FakeResponse], *, retries: int = 3) -> LeetCodeClient:
    client = LeetCodeClient(retries=retries)
    client._session = FakeSession(responses)  # type: ignore[assignment]
    return client


PROFILE_DATA: dict[str, Any] = {
    "matchedUser": {
        "username": "alice",
        "profile": {
            "realName": "Alice Example",
            "userAvatar": "https://example.com/avatar.png",
            "countryName": "India",
            "company": "Example Corp",
            "school": "Example University",
            "ranking": 12345,
            "reputation": 42,
            "starRating": 2.5,
        },
        "submitStatsGlobal": {
            "acSubmissionNum": [
                {"difficulty": "All", "count": 300, "submissions": 500},
                {"difficulty": "Easy", "count": 120, "submissions": 150},
                {"difficulty": "Medium", "count": 140, "submissions": 250},
                {"difficulty": "Hard", "count": 40, "submissions": 100},
            ]
        },
        "userCalendar": {
            "streak": 12,
            "totalActiveDays": 100,
            "submissionCalendar": '{"1700000000": 3, "1700086400": 1}',
        },
        "badges": [{"displayName": "Guardian"}, {"displayName": "Annual Badge"}],
    },
    "allQuestionsCount": [
        {"difficulty": "Easy", "count": 800},
        {"difficulty": "Medium", "count": 1800},
        {"difficulty": "Hard", "count": 700},
    ],
    "userContestRanking": {
        "attendedContestsCount": 10,
        "rating": 1800.5,
        "globalRanking": 1234,
        "topPercentage": 5.2,
    },
    "recentAcSubmissionList": [
        {"title": "Two Sum", "titleSlug": "two-sum", "timestamp": 1700000000}
    ],
}

DAILY_DATA: dict[str, Any] = {
    "activeDailyCodingChallengeQuestion": {
        "date": "2026-11-02",
        "link": "/problems/two-sum/",
        "question": {
            "title": "Two Sum",
            "titleSlug": "two-sum",
            "difficulty": "Easy",
            "acRate": 55.5,
        },
    }
}


def test_validate_username() -> None:
    assert validate_username(" alice_01 ") == "alice_01"
    assert validate_username("a-b") == "a-b"
    with pytest.raises(InvalidUsernameError):
        validate_username("bad name")
    with pytest.raises(InvalidUsernameError):
        validate_username("")


def test_parse_profile() -> None:
    profile = parse_profile(PROFILE_DATA)
    assert profile.username == "alice"
    assert profile.total_solved == 300
    assert profile.total_questions == 3300
    assert profile.easy.solved == 120
    assert profile.easy.total == 800
    assert profile.medium.percent == pytest.approx(140 / 1800 * 100)
    assert profile.streak == 12
    assert profile.total_active_days == 100
    assert len(profile.submission_calendar) == 2
    assert profile.contest is not None and profile.contest.rating == 1800.5
    assert profile.badges == ("Guardian", "Annual Badge")
    assert profile.recent[0].title == "Two Sum"
    assert profile.profile_url.endswith("/alice/")


def test_parse_profile_missing_user() -> None:
    with pytest.raises(UserNotFoundError):
        parse_profile({"matchedUser": None})


def test_parse_daily() -> None:
    daily = parse_daily(DAILY_DATA)
    assert daily.title == "Two Sum"
    assert daily.difficulty == "Easy"
    assert daily.url == "https://leetcode.com/problems/two-sum/"
    with pytest.raises(LeetCodeError):
        parse_daily({})


async def test_fetch_profile_caches() -> None:
    client = make_client([FakeResponse(payload={"data": PROFILE_DATA})])
    client.cache_ttl = 60
    try:
        first = await client.fetch_profile("alice")
        second = await client.fetch_profile("alice")
        assert first.total_solved == 300
        assert second is first
        assert client._session is not None
        assert client._session.requests == 1  # type: ignore[attr-defined]
    finally:
        await client.close()


async def test_fetch_profile_not_found() -> None:
    client = make_client([FakeResponse(payload={"data": {"matchedUser": None}})])
    try:
        with pytest.raises(UserNotFoundError):
            await client.fetch_profile("missing")
    finally:
        await client.close()


async def test_graphql_error_not_found() -> None:
    client = make_client(
        [FakeResponse(payload={"errors": [{"message": "That user does not exist."}]})]
    )
    try:
        with pytest.raises(UserNotFoundError):
            await client.fetch_profile("missing")
    finally:
        await client.close()


async def test_rate_limit() -> None:
    client = make_client([FakeResponse(status=429, headers={"Retry-After": "12"})])
    try:
        with pytest.raises(RateLimitedError) as excinfo:
            await client.fetch_profile("alice")
        assert excinfo.value.retry_after == 12
    finally:
        await client.close()


async def test_retries_server_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    client = make_client(
        [FakeResponse(status=500), FakeResponse(payload={"data": PROFILE_DATA})],
        retries=2,
    )
    try:
        profile = await client.fetch_profile("alice")
        assert profile.total_solved == 300
    finally:
        await client.close()


async def test_service_unavailable_after_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    client = make_client([FakeResponse(status=503), FakeResponse(status=503)], retries=2)
    try:
        with pytest.raises(ServiceUnavailableError):
            await client.fetch_profile("alice")
    finally:
        await client.close()


async def test_fetch_daily() -> None:
    client = make_client([FakeResponse(payload={"data": DAILY_DATA})])
    try:
        daily = await client.fetch_daily()
        assert daily.title == "Two Sum"
    finally:
        await client.close()
