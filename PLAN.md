# LeetGo v3.0 — Production Readiness Plan

> Status: implemented in v3.0.0 (2026-11-02). This file is kept as an architecture decision record.

## 1. Audit summary

| Severity | Finding | Impact |
|---|---|---|
| Critical | `/stats` depends on `leetcodestats.cyclic.app`, which is offline | Core feature returns an error |
| Critical | `requests.get()` is called inside async commands | Blocks the whole event loop |
| High | Users keyed by `str(discord_user)` | Breaks on rename; reminders cannot resolve members |
| High | Reminders use naive server time, no timezone | Wrong delivery time for most users |
| High | No global error handler / cooldowns | Unhandled errors, API abuse |
| Medium | Cohort DB row created before channel; no rollback | Orphaned cohorts |
| Medium | No delete/transfer/kick for cohorts | Hosts abandon channels |
| Medium | Single 680-line module, duplicated boilerplate | Hard to test and extend |
| Medium | Unpinned dependencies, no tests/CI/lint/typecheck | Not production deployable |
| Low | README clone URL points at a different account | Broken onboarding |
| Low | `.env.example` documents an unused `LEETCODE_SESSION` | Confusing setup |

## 2. Target architecture

```
Discord Gateway
      │
      ▼
leetgo/bot.py ── global error handler, presence, lifecycle
      │
      ├── cogs/profile.py     link / profile / unlink
      ├── cogs/stats.py       stats / daily / compare / leaderboard
      ├── cogs/cohorts.py     cohort create/join/leave/info/list/delete/transfer
      ├── cogs/roadmap.py     roadmap selection + topic progress
      ├── cogs/goals.py       goal set/view/clear + pace tracking
      ├── cogs/reminders.py   timezone-aware DM reminders
      └── cogs/meta.py        help / ping / about
      │
      ├── leetcode.py   async GraphQL + TTL cache + retry/backoff
      ├── db.py         aiosqlite, WAL, migrations, typed records
      ├── health.py     optional /healthz + /metrics
      └── config.py     pydantic-settings, validated environment
```

## 3. Data model v2

- `users` — Discord `user_id` (snowflake, unique), nullable for legacy rows,
  LeetCode username, roadmap, roadmap progress (JSON), goal + baseline, reminder
  time + IANA timezone, timestamps.
- `cohorts` — id, unique name per guild, guild/channel/host IDs, created_at.
- `reminder_log` — `(user_id, sent_on)` primary key; prevents duplicate DMs across
  restarts and multiple loop ticks.
- `schema_migrations` — explicit versioning; v1 databases are copied to
  `users_v1_backup` / `cohorts_v1_backup` before migration.
- Legacy rows are claimed on the next `/set-username` by matching the old
  `discord_username`, preserving goals, roadmaps, reminders and cohorts.

## 4. Feature set

### Profiles
- `/set-username` verifies the account against LeetCode before saving.
- `/profile [member]` — avatar, rank, streak, contest rating, roadmap, goal.
- `/unlink` — confirmation button, cascades cohort membership.

### Statistics
- `/stats [member]` — overall + per-difficulty bars, ranking, reputation, streak,
  active days, contest rating, goal pace, recent accepted solves.
- `/daily` — today's LeetCode challenge with a link button.
- `/compare <a> <b>` — head-to-head table.
- `/leaderboard [scope]` — cohort or server, cached, concurrent fetch with semaphore.

### Cohorts
- `/cohort create|join|leave|info|list|leaderboard|delete|transfer`.
- Auto-creates the `Cohorts` category when permitted; rolls back DB on channel failure.
- Host must transfer ownership or delete before leaving; confirmation on destructive actions.

### Roadmaps
- Four curated paths, six topics each.
- `/roadmap` select menu; `/roadmap progress` toggle buttons persisted per user.

### Goals
- `/goal set|view|clear` with baseline solved count, target date, expected pace,
  and an on-track / behind / complete verdict.

### Reminders
- `/reminder set|view|remove|test`.
- IANA timezone per user, autocomplete, next-run preview.
- Minute loop with DB dedupe; daily challenge included in the DM.

### Meta
- `/help` command catalogue, `/ping` latency + DB/API health, `/about` stats.

## 5. Reliability & security

- Every command defers before network I/O; no blocking calls.
- Global `app_commands` error handler maps domain errors to friendly embeds and
  logs a short reference ID.
- Per-user cooldowns on network-heavy commands.
- Input validation: username regex, cohort name sanitisation, hour/minute bounds,
  timezone validation, 25-option Discord limits.
- Parameterised SQL only; secrets held in `SecretStr`; token never logged.
- Graceful SIGINT/SIGTERM shutdown, DB close, HTTP session close.
- Optional `/healthz` + `/metrics` endpoint for container probes.

## 6. Quality gates

- `pytest` + `pytest-asyncio` with fake HTTP sessions, targeting the DB, GraphQL client,
  formatting, goal math, reminder scheduling and every command surface.
- `ruff check`, `ruff format --check`, `mypy` in CI across Python 3.11–3.13.
- Docker build check in CI.
- Pinned dependency ranges, Dependabot, pre-commit hooks.

## 7. Documentation & visuals

- Hand-built SVG hero banner, logo, stats mockup and cohort mockup in `docs/assets/`.
- Shields.io badge wall (CI, version, Python, discord.py, license, Docker, tests).
- Mermaid architecture and request-flow diagrams.
- Rewritten README: quick start, Docker, bot setup, permissions, commands,
  configuration, deployment, troubleshooting, FAQ, roadmap.
- Updated CHANGELOG, CONTRIBUTING, SECURITY, CODE_OF_CONDUCT and templates.

## 8. Delivery order

1. Tooling + config + formatting/timezone utilities
2. LeetCode GraphQL client + tests
3. Database layer + migrations + tests
4. Bot shell, health server, error handling
5. Cogs (profile → stats → cohorts → roadmap → goals → reminders → meta)
6. Test suite, lint, typecheck
7. Docker, CI, templates
8. Visuals + README + changelog
9. Full verification pass
