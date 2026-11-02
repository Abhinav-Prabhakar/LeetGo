# Changelog

All notable changes to the LeetGo Discord bot are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.0.0] - 2026-11-02

The production rewrite. LeetGo is now a typed async package with a direct LeetCode
integration, a tested migration path, and a deployable container image.

### Added

- **Async LeetCode GraphQL client** with profile, daily challenge, contest, badge and
  recent-solve parsing, a five-minute cache, per-user request coalescing, retries with
  exponential backoff, and explicit handling for `429` and unavailable responses.
- **Cohort system** with channel provisioning, join/leave flows, roster and cohort
  leaderboards, ownership transfer, and confirmation-gated deletion with cleanup.
- **Goal pacing** that records a baseline and reports ahead/behind/complete plus expected
  pace and days remaining.
- **Roadmap progress** persisted per topic for four curated learning paths.
- **Timezone-aware reminders** with IANA autocomplete, a resilient polling window,
  idempotent daily delivery, and `/reminder test`.
- **Slash command groups** for cohorts, goals and reminders, plus `/daily`, `/compare`,
  `/profile`, `/leaderboard`, `/help`, `/ping` and `/about`.
- **Operational endpoints**: `/healthz` for orchestration and `/metrics` for Prometheus.
- **Global error handler** with cooldowns, friendly messages for expected failures, and
  reference IDs for unexpected ones.
- **SQLite v1 → v2 auto-migration** with `users_v1_backup` and `cohorts_v1_backup`
  snapshots, legacy account claiming, WAL mode and cascade-aware deletion.
- **Production packaging**: `pyproject.toml`, non-root Dockerfile, Compose stack, health
  check, Makefile, pre-commit hooks, GitHub Actions CI across Python 3.11–3.13,
  Dependabot, issue/PR templates, security policy and code of conduct.
- **Test suite** covering formatting, timezones, configuration, models, database
  migrations, GraphQL parsing/retries and leaderboard caching.
- **Visual documentation**: hand-built SVG banner, logo and three product previews, plus
  architecture and request-flow diagrams.

### Changed

- **Breaking:** the bot is slash-command only. The old message-command prefix is removed.
- **Breaking:** the entry point is `python -m leetgo` (or the `leetgo` console script);
  `main.py` remains as a thin compatibility shim.
- **Breaking:** the database defaults to `data/leetgo.db` and keys users by Discord
  snowflake instead of Discord username.
- The project now requires Python 3.11+ and discord.py 2.x.
- Statistics are fetched directly from LeetCode instead of the retired public stats API.
- Leaderboards use a five-minute service cache and are invalidated on cohort or data
  changes.
- All embeds share one visual system with consistent colours, progress bars and empty
  states.

### Fixed

- Reminders no longer compare a naive local time against UTC; they now respect the user's
  IANA timezone and tolerate scheduler drift.
- Duplicate LeetCode usernames are rejected case-insensitively.
- Cohort channel creation rolls back the channel if the database insert fails.
- Hosts cannot unlink or leave while other members depend on their cohort.
- SQLite connections enable foreign keys, WAL and busy timeouts, preventing partial
  cascades and lock errors.
- Interaction responses handle already-acknowledged and expired interactions without
  raising secondary exceptions.

### Removed

- The dead `leetcodestats.cyclic.app` integration and the blocking `requests` dependency.
- `database.py` from the project root; persistence now lives in `leetgo/db.py`.
- Unused resource and legacy command modules.

### Security

- The Docker image runs as an unprivileged user and excludes environment files, databases
  and tests from the build context.
- Logs redact configured secrets and never include the bot token.
- Added a private vulnerability disclosure process in `SECURITY.md`.

### Upgrading from 2.x

1. Back up your existing database.
2. Keep the old `storage.db` in the working directory or `data/`; LeetGo imports it on first start. Alternatively place it at `DATABASE_PATH`.
3. Start LeetGo once; the migration runs automatically and keeps backup tables.
4. Each member runs `/set-username` with their existing LeetCode username to claim their
   migrated row.
5. Set `GUILD_ID` for immediate slash-command sync while testing.

## [2.0.0] - 2024

### Added

#### Features
- **Interactive Roadmap System**: Users can now select from 4 learning paths (Beginner, Intermediate, Advanced, Interview Prep) with topic breakdowns
- **Join Cohort Functionality**: Complete implementation with interactive dropdown menu to join existing study cohorts
- **Leave Cohort Command**: New `/leave-cohort` command allowing users to exit their current cohort
- **Daily Reminder System**: Fully functional reminder system with:
  - `/set-reminders` to configure daily study reminders at specific times
  - `/view-reminders` to check current reminder settings
  - `/remove-reminders` to disable reminders
  - Background task that sends DM reminders to users at their scheduled times
- **Enhanced Goal Tracking**: Goals now persist with start dates and display in `/stats` command
- **Improved Statistics Display**: Enhanced `/stats` command with:
  - Rich embed formatting
  - Progress percentages
  - Difficulty breakdown with color-coded emojis
  - Goal display integration

#### Technical Improvements
- **Comprehensive Error Handling**: All database operations and commands now have try-catch blocks with proper error messages
- **Logging System**: Implemented logging to both console and file (`leetgo.log`) for debugging and monitoring
- **Input Validation**: Added validation for all user inputs (usernames, goals, reminders, cohort names)
- **Database Enhancements**:
  - Added `roadmap` column (TEXT) to store user's selected learning path
  - Added `reminder_hour` and `reminder_minute` columns for reminder scheduling
  - Added `UNIQUE` constraint on `discord_username` to prevent duplicates
  - All database methods now include error handling and logging
- **Code Quality**:
  - Added comprehensive docstrings
  - Improved code organization and readability
  - Better type hints and return types
  - Consistent error messaging with emoji indicators

#### Documentation
- **MIT License**: Added LICENSE file
- **Enhanced README**: Updated with:
  - Complete command list with all implemented features
  - Bot permissions requirements
  - Step-by-step usage guide
  - Updated project structure
  - Future enhancements section
- **Environment Configuration**: Updated `.env.example` with clear instructions

### Changed
- **Stats Command**: Now uses embeds instead of plain text for better readability
- **Goal Setting**: Enhanced with breakdown showing per-month and per-week targets
- **Cohort Creation**: Now sends welcome message to newly created cohort channels
- **User Experience**: All commands now provide rich, emoji-enhanced feedback

### Removed
- **Resources Command**: Removed `/resources` command as requested
- **Known Issues Section**: Removed from README as all issues have been resolved
- **Roadmap Section**: Replaced with "Future Enhancements" after completing all roadmap items

### Fixed
- **Cohort Leave Functionality**: Implemented complete leave functionality that was previously missing
- **Reminder System**: Converted from stub to fully functional system with background tasks
- **Goal Persistence**: Goals now properly persist in database and display in stats
- **Database Connection**: Improved connection handling and proper cleanup
- **Error Messages**: All error messages are now user-friendly and informative

### Security
- **Timeout Handling**: Added 10-second timeout for LeetCode API requests
- **Permission Checks**: Added checks for bot permissions before creating channels
- **User Validation**: All commands validate that users exist before operations

## [1.0.0] - Previous Version

### Initial Features
- Basic user profile linking
- LeetCode statistics fetching
- Cohort hosting
- Basic goal setting
- SQLite database integration
