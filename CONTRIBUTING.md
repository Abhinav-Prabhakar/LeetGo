# Contributing to LeetGo

Thanks for taking the time to improve LeetGo. This guide covers the development loop, the
quality bar, and the few project-specific rules that keep the bot safe for real servers.

By participating, you agree to our [Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

- **Report a bug** with the [bug template](.github/ISSUE_TEMPLATE/bug_report.yml). Include
  the reference ID from Discord and the matching log lines, with secrets removed.
- **Request a feature** with the [feature template](.github/ISSUE_TEMPLATE/feature_request.yml).
- **Improve docs** — setup notes, troubleshooting, roadmap topics and screenshots are all
  welcome.
- **Send code** — bug fixes, tests, refactors and new commands.

Please open an issue before a large change so we can agree on the shape first. Small fixes
can go straight to a pull request.

## Development setup

Requires Python 3.11+ and, for container work, Docker.

```bash
git clone https://github.com/Abhinav-Prabhakar/LeetGo.git
cd LeetGo
make dev
cp .env.example .env
# set BOT_TOKEN; set GUILD_ID for instant command sync during development
```

`make dev` creates `.venv`, installs the project in editable mode with dev dependencies, and
installs the pre-commit hooks.

### Useful commands

| Command | Purpose |
|:--|:--|
| `make check` | Ruff lint, format check, mypy and pytest — the full gate |
| `make format` | Format code and apply safe lint fixes |
| `make typecheck` | Run mypy over `leetgo/` |
| `make coverage` | Tests with a terminal coverage report |
| `make run` | Start the bot locally |
| `make docker-build` | Build the production image |

## Quality bar

A pull request is ready when:

1. `make check` passes locally.
2. New behaviour has tests, and coverage stays above the CI gate (85%). Pure helpers
   belong in `tests/test_*.py`; database changes use the `db` fixture; HTTP behaviour uses
   a fake session rather than the real LeetCode API.
3. Public functions and non-obvious internals have type hints and short docstrings.
4. User-facing text is rendered through `leetgo/embeds.py` so cards stay consistent.
5. No secrets, tokens, database files or logs are committed.

### Style

- Ruff formats to 100 columns with double quotes. Do not fight the formatter.
- Prefer `async` I/O. Never call blocking network or disk APIs from an event loop; wrap
  unavoidable blocking work with `asyncio.to_thread`.
- Catch specific exceptions. Let unexpected failures reach the global handler so they get a
  reference ID and a useful log entry.
- Keep SQL in `leetgo/db.py`. Cogs should not open cursors.
- New settings belong in `leetgo/config.py` with validation, a default, and a row in
  `.env.example` and the README configuration table.

### Database changes

The schema is versioned with `schema_migrations`. To change it:

1. Add a migration step in `leetgo/db.py`; never edit an already-released migration.
2. Preserve existing rows and test the upgrade path from the previous schema.
3. Update `tests/test_db.py`, including an idempotency test.
4. Mention the change and any manual step in `CHANGELOG.md`.

### Commands and permissions

- Commands are slash commands registered through `app_commands`. There is no prefix
  command layer.
- Defer before network calls. Use `respond()` / `send_error()` from
  `leetgo/interactions.py` so expired interactions are handled.
- Add cooldowns for commands that hit LeetCode.
- Cohort commands must check host ownership and Discord permissions before mutating state.
- Destructive actions require a confirmation view.

## Commit messages

Use a short imperative subject, optionally with a conventional prefix:

```text
feat: add weekly cohort recap
fix: keep reminder window across restarts
docs: document legacy database claiming
test: cover GraphQL rate-limit retries
```

Keep the body focused on **why**, not a restatement of the diff.

## Pull request checklist

- [ ] The change is linked to an issue where one exists.
- [ ] `make check` passes.
- [ ] Tests cover the new behaviour and the previous bug.
- [ ] Documentation, `.env.example` and `CHANGELOG.md` are updated when relevant.
- [ ] No secrets or personal data are included.
- [ ] Screenshots are attached for visible embed or command changes.

## Security

Do **not** open a public issue for a vulnerability. Follow [SECURITY.md](SECURITY.md) and
report it privately through GitHub Security Advisories.

## License

By contributing, you agree that your contribution is licensed under the project's
[MIT License](LICENSE).
