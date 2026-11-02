"""Static data and presentation constants."""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- Brand ----------------------------------------------------------------
BRAND_COLOR = 0xFFA116
SUCCESS_COLOR = 0x00B8A3
ERROR_COLOR = 0xFF375F
INFO_COLOR = 0x5865F2
WARNING_COLOR = 0xFFC01E
MUTED_COLOR = 0x2B2D31

DIFFICULTY_COLORS: dict[str, int] = {
    "Easy": 0x00B8A3,
    "Medium": 0xFFC01E,
    "Hard": 0xFF375F,
}
DIFFICULTY_EMOJI: dict[str, str] = {
    "Easy": "🟢",
    "Medium": "🟡",
    "Hard": "🔴",
}
DIFFICULTY_ORDER = ("Easy", "Medium", "Hard")

FOOTER_TEXT = "LeetGo • Grind smarter, together."

# --- LeetCode -------------------------------------------------------------
LEETCODE_BASE_URL = "https://leetcode.com"
LEETCODE_GRAPHQL_URL = "https://leetcode.com/graphql"
LEETCODE_PROFILE_URL = "https://leetcode.com/u/{username}/"
LEETCODE_USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,30}$")
LEETCODE_CACHE_TTL = 300
LEETCODE_TOTALS_TTL = 6 * 60 * 60
LEETCODE_DAILY_TTL = 15 * 60
LEETCODE_RECENT_TTL = 60


# --- Roadmaps -------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Roadmap:
    """A curated learning path."""

    key: str
    emoji: str
    description: str
    topics: tuple[str, ...]


ROADMAPS: dict[str, Roadmap] = {
    "Beginner": Roadmap(
        key="Beginner",
        emoji="🌱",
        description="Build the fundamentals that every interview question is made of.",
        topics=(
            "Arrays & Hashing",
            "Two Pointers",
            "Sliding Window",
            "Strings & Stack",
            "Linked Lists",
            "Sorting & Binary Search Basics",
        ),
    ),
    "Intermediate": Roadmap(
        key="Intermediate",
        emoji="📈",
        description="Turn patterns into instincts with trees, graphs and dynamic programming.",
        topics=(
            "Binary Search",
            "Trees & BST",
            "Graphs & Traversal",
            "Backtracking",
            "Heaps & Priority Queues",
            "1-D Dynamic Programming",
        ),
    ),
    "Advanced": Roadmap(
        key="Advanced",
        emoji="🚀",
        description="Push into the algorithms that separate strong candidates from great ones.",
        topics=(
            "Advanced Dynamic Programming",
            "Shortest Paths & MST",
            "Tries",
            "Segment Trees & Fenwick",
            "Bit Manipulation",
            "Advanced Math & Geometry",
        ),
    ),
    "Interview Prep": Roadmap(
        key="Interview Prep",
        emoji="💼",
        description="A focused sprint through the highest-signal interview material.",
        topics=(
            "Top 150 Questions",
            "System Design Basics",
            "Behavioral & STAR Stories",
            "Mock Interviews",
            "OOP & Concurrency",
            "SQL & Databases",
        ),
    ),
}

# --- Cohorts --------------------------------------------------------------
COHORT_CATEGORY_DEFAULT = "Cohorts"
COHORT_NAME_MAX_LENGTH = 90
COHORT_WELCOME_TITLE = "🎉 Welcome to {name}!"

# --- Limits ---------------------------------------------------------------
MAX_DISCORD_SELECT_OPTIONS = 25
MAX_EMBED_FIELD_VALUE = 1024
MAX_USERNAME_LENGTH = 30

COMMON_TIMEZONES: tuple[str, ...] = (
    "UTC",
    "America/Los_Angeles",
    "America/Denver",
    "America/Chicago",
    "America/New_York",
    "America/Sao_Paulo",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Europe/Madrid",
    "Europe/Amsterdam",
    "Europe/Stockholm",
    "Europe/Warsaw",
    "Europe/Istanbul",
    "Africa/Lagos",
    "Africa/Cairo",
    "Africa/Johannesburg",
    "Asia/Dubai",
    "Asia/Karachi",
    "Asia/Kolkata",
    "Asia/Dhaka",
    "Asia/Bangkok",
    "Asia/Singapore",
    "Asia/Shanghai",
    "Asia/Tokyo",
    "Asia/Seoul",
    "Australia/Sydney",
    "Australia/Melbourne",
    "Pacific/Auckland",
)

# --- Misc -----------------------------------------------------------------
PROGRESS_FILLED = "▰"
PROGRESS_EMPTY = "▱"
PROGRESS_BAR_LENGTH = 10
