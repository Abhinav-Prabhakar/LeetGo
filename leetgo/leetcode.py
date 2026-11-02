"""Async LeetCode GraphQL client with caching and retries."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

import aiohttp

from .constants import (
    LEETCODE_BASE_URL,
    LEETCODE_CACHE_TTL,
    LEETCODE_DAILY_TTL,
    LEETCODE_GRAPHQL_URL,
    LEETCODE_PROFILE_URL,
    LEETCODE_USERNAME_RE,
)
from .errors import (
    InvalidUsernameError,
    LeetCodeError,
    RateLimitedError,
    ServiceUnavailableError,
    UserNotFoundError,
)

logger = logging.getLogger("LeetGo.leetcode")

T = TypeVar("T")

PROFILE_QUERY = """
query userProfile($username: String!, $recentLimit: Int!) {
  matchedUser(username: $username) {
    username
    profile {
      realName
      userAvatar
      countryName
      company
      school
      ranking
      reputation
      starRating
    }
    submitStatsGlobal {
      acSubmissionNum { difficulty count submissions }
    }
    userCalendar { streak totalActiveDays submissionCalendar }
    badges { displayName }
  }
  allQuestionsCount { difficulty count }
  userContestRanking(username: $username) {
    attendedContestsCount
    rating
    globalRanking
    topPercentage
  }
  recentAcSubmissionList(username: $username, limit: $recentLimit) {
    title
    titleSlug
    timestamp
  }
}
"""

DAILY_QUERY = """
query activeDailyCodingChallenge {
  activeDailyCodingChallengeQuestion {
    date
    link
    question { title titleSlug difficulty acRate }
  }
}
"""


@dataclass(frozen=True, slots=True)
class DifficultyStat:
    """Solved, total and accepted-submission counts for one difficulty."""

    solved: int
    total: int
    submissions: int = 0

    @property
    def percent(self) -> float:
        """Solved percentage for this difficulty."""
        return self.solved / self.total * 100 if self.total else 0.0


@dataclass(frozen=True, slots=True)
class ContestStat:
    """Contest rating summary."""

    rating: float
    attended: int
    global_ranking: int | None = None
    top_percentage: float | None = None


@dataclass(frozen=True, slots=True)
class RecentSolve:
    """A recently accepted submission."""

    title: str
    title_slug: str
    timestamp: int

    @property
    def url(self) -> str:
        """Public problem URL."""
        return f"{LEETCODE_BASE_URL}/problems/{self.title_slug}/"


@dataclass(frozen=True, slots=True)
class DailyChallenge:
    """The current LeetCode daily challenge."""

    date: str
    title: str
    title_slug: str
    difficulty: str
    ac_rate: float
    link: str

    @property
    def url(self) -> str:
        """Absolute challenge URL."""
        return f"{LEETCODE_BASE_URL}{self.link}"


@dataclass(frozen=True, slots=True)
class UserProfile:
    """Everything LeetGo needs to render a member's LeetCode card."""

    username: str
    real_name: str | None
    avatar_url: str | None
    country: str | None
    company: str | None
    school: str | None
    ranking: int | None
    reputation: int
    star_rating: float | None
    total_solved: int
    total_questions: int
    difficulty: dict[str, DifficultyStat] = field(default_factory=dict)
    streak: int = 0
    total_active_days: int = 0
    submission_calendar: dict[str, int] = field(default_factory=dict)
    contest: ContestStat | None = None
    badges: tuple[str, ...] = ()
    recent: tuple[RecentSolve, ...] = ()

    @property
    def easy(self) -> DifficultyStat:
        """Easy difficulty stats."""
        return self.difficulty.get("Easy", DifficultyStat(0, 0))

    @property
    def medium(self) -> DifficultyStat:
        """Medium difficulty stats."""
        return self.difficulty.get("Medium", DifficultyStat(0, 0))

    @property
    def hard(self) -> DifficultyStat:
        """Hard difficulty stats."""
        return self.difficulty.get("Hard", DifficultyStat(0, 0))

    @property
    def overall_percent(self) -> float:
        """Overall solved percentage."""
        return self.total_solved / self.total_questions * 100 if self.total_questions else 0.0

    @property
    def profile_url(self) -> str:
        """Public LeetCode profile URL."""
        return LEETCODE_PROFILE_URL.format(username=self.username)


def validate_username(username: str) -> str:
    """Validate and normalise a LeetCode username."""
    cleaned = username.strip()
    if not LEETCODE_USERNAME_RE.fullmatch(cleaned):
        raise InvalidUsernameError(
            "LeetCode usernames may contain letters, numbers, underscores and hyphens (1–30 chars)."
        )
    return cleaned


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_profile(payload: dict[str, Any]) -> UserProfile:
    """Parse a GraphQL profile response into a typed object."""
    matched = payload.get("matchedUser")
    if not matched:
        raise UserNotFoundError("That LeetCode username could not be found.")

    profile = matched.get("profile") or {}
    totals = {
        str(item.get("difficulty")): _as_int(item.get("count"))
        for item in payload.get("allQuestionsCount") or []
    }
    solved: dict[str, DifficultyStat] = {}
    for item in (matched.get("submitStatsGlobal") or {}).get("acSubmissionNum") or []:
        difficulty = str(item.get("difficulty"))
        solved[difficulty] = DifficultyStat(
            solved=_as_int(item.get("count")),
            total=totals.get(difficulty, 0),
            submissions=_as_int(item.get("submissions")),
        )

    calendar = matched.get("userCalendar") or {}
    raw_calendar = calendar.get("submissionCalendar") or "{}"
    try:
        parsed_calendar = (
            json.loads(raw_calendar) if isinstance(raw_calendar, str) else raw_calendar
        )
        submission_calendar = {
            str(key): _as_int(value) for key, value in dict(parsed_calendar).items()
        }
    except (TypeError, ValueError):
        submission_calendar = {}

    contest_raw = payload.get("userContestRanking")
    contest = None
    if contest_raw:
        contest = ContestStat(
            rating=_as_float(contest_raw.get("rating")),
            attended=_as_int(contest_raw.get("attendedContestsCount")),
            global_ranking=_as_optional_int(contest_raw.get("globalRanking")),
            top_percentage=_as_optional_float(contest_raw.get("topPercentage")),
        )

    recent = tuple(
        RecentSolve(
            title=str(item.get("title") or "Unknown problem"),
            title_slug=str(item.get("titleSlug") or ""),
            timestamp=_as_int(item.get("timestamp")),
        )
        for item in payload.get("recentAcSubmissionList") or []
        if item.get("titleSlug")
    )

    total_questions = sum(totals.get(level, 0) for level in ("Easy", "Medium", "Hard"))
    return UserProfile(
        username=str(matched.get("username") or ""),
        real_name=profile.get("realName") or None,
        avatar_url=profile.get("userAvatar") or None,
        country=profile.get("countryName") or None,
        company=profile.get("company") or None,
        school=profile.get("school") or None,
        ranking=_as_optional_int(profile.get("ranking")),
        reputation=_as_int(profile.get("reputation")),
        star_rating=_as_optional_float(profile.get("starRating")),
        total_solved=solved.get("All", DifficultyStat(0, 0)).solved,
        total_questions=total_questions,
        difficulty=solved,
        streak=_as_int(calendar.get("streak")),
        total_active_days=_as_int(calendar.get("totalActiveDays")),
        submission_calendar=submission_calendar,
        contest=contest,
        badges=tuple(
            str(badge.get("displayName"))
            for badge in matched.get("badges") or []
            if badge.get("displayName")
        ),
        recent=recent,
    )


def parse_daily(payload: dict[str, Any]) -> DailyChallenge:
    """Parse the daily challenge response."""
    daily = payload.get("activeDailyCodingChallengeQuestion")
    if not daily or not daily.get("question"):
        raise LeetCodeError("The daily challenge is unavailable right now.")
    question = daily["question"]
    return DailyChallenge(
        date=str(daily.get("date") or ""),
        title=str(question.get("title") or "Daily Challenge"),
        title_slug=str(question.get("titleSlug") or ""),
        difficulty=str(question.get("difficulty") or "Unknown"),
        ac_rate=_as_float(question.get("acRate")),
        link=str(daily.get("link") or ""),
    )


class LeetCodeClient:
    """Small, resilient client for LeetCode's public GraphQL endpoint."""

    def __init__(
        self,
        *,
        cache_ttl: int = LEETCODE_CACHE_TTL,
        timeout: float = 15.0,
        retries: int = 3,
        max_concurrency: int = 8,
    ) -> None:
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self.retries = retries
        self._session: aiohttp.ClientSession | None = None
        self._cache: dict[str, tuple[float, Any]] = {}
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": LEETCODE_BASE_URL,
            "Referer": f"{LEETCODE_BASE_URL}/problemset/",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                connector=aiohttp.TCPConnector(limit=20, ttl_dns_cache=300),
            )
        return self._session

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def __aenter__(self) -> LeetCodeClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def _cached(self, key: str, ttl: int, factory: Callable[[], Awaitable[T]]) -> T:
        if ttl <= 0:
            return await factory()
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and cached[0] > now:
            return cached[1]
        async with self._locks[key]:
            cached = self._cache.get(key)
            if cached and cached[0] > now:
                return cached[1]
            value = await factory()
            self._cache[key] = (now + ttl, value)
            if len(self._cache) > 500:
                self._prune_cache()
            return value

    def _prune_cache(self) -> None:
        now = time.monotonic()
        self._cache = {key: item for key, item in self._cache.items() if item[0] > now}

    def clear_cache(self) -> None:
        """Drop all cached responses."""
        self._cache.clear()

    async def _post(
        self,
        query: str,
        variables: dict[str, Any],
        *,
        username: str | None = None,
    ) -> dict[str, Any]:
        session = await self._get_session()
        headers = {"Referer": f"{LEETCODE_BASE_URL}/{username}/"} if username else None
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                async with (
                    self._semaphore,
                    session.post(
                        LEETCODE_GRAPHQL_URL,
                        json={"query": query, "variables": variables},
                        headers=headers,
                    ) as response,
                ):
                    if response.status == 429:
                        retry_after = _as_float(response.headers.get("Retry-After"), 30.0)
                        raise RateLimitedError(retry_after)
                    if response.status >= 500:
                        last_error = ServiceUnavailableError(
                            f"LeetCode returned HTTP {response.status}"
                        )
                        if attempt >= self.retries:
                            break
                        await asyncio.sleep(min(0.5 * 2 ** (attempt - 1), 4.0))
                        continue
                    response.raise_for_status()
                    body = await response.json(content_type=None)
            except RateLimitedError:
                raise
            except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                await asyncio.sleep(min(0.5 * 2 ** (attempt - 1), 4.0))
                continue

            errors = body.get("errors") or []
            if errors:
                message = " ".join(str(item.get("message", "")) for item in errors)
                lowered = message.lower()
                if "does not exist" in lowered or "not found" in lowered:
                    raise UserNotFoundError("That LeetCode username could not be found.")
                if "rate limit" in lowered:
                    raise RateLimitedError(30.0)
                raise LeetCodeError(message or "LeetCode returned an unknown error.")
            data = body.get("data")
            if not isinstance(data, dict):
                raise LeetCodeError("LeetCode returned an empty response.")
            return data

        logger.warning("LeetCode request failed after %s attempts: %s", self.retries, last_error)
        raise ServiceUnavailableError("LeetCode is unavailable right now. Please try again soon.")

    async def fetch_profile(self, username: str, *, recent_limit: int = 5) -> UserProfile:
        """Fetch a full profile, including contest stats and recent solves."""
        cleaned = validate_username(username)
        key = f"profile:{cleaned.lower()}:{recent_limit}"

        async def factory() -> UserProfile:
            data = await self._post(
                PROFILE_QUERY,
                {"username": cleaned, "recentLimit": recent_limit},
                username=cleaned,
            )
            return parse_profile(data)

        profile: UserProfile = await self._cached(key, self.cache_ttl, factory)
        return profile

    async def fetch_daily(self) -> DailyChallenge:
        """Fetch today's LeetCode challenge."""

        async def factory() -> DailyChallenge:
            data = await self._post(DAILY_QUERY, {})
            return parse_daily(data)

        daily: DailyChallenge = await self._cached("daily", LEETCODE_DAILY_TTL, factory)
        return daily

    async def fetch_recent(self, username: str, limit: int = 5) -> tuple[RecentSolve, ...]:
        """Fetch recent accepted submissions only (shares the profile cache)."""
        profile = await self.fetch_profile(username, recent_limit=limit)
        return profile.recent[:limit]
