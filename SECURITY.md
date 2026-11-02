# Security Policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| 3.x     | ✅        |
| 2.x     | ❌        |

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Report privately through
[GitHub Security Advisories](https://github.com/Abhinav-Prabhakar/LeetGo/security/advisories/new).
Include:

- a description of the issue and its impact,
- reproduction steps,
- the affected version or commit,
- any suggested mitigation.

You can expect an acknowledgement within 72 hours. We will coordinate a fix and a
disclosure date with you.

## Secrets

LeetGo reads its Discord token and configuration from environment variables or a local
`.env` file. Never commit `.env`, database files or logs. If a token is exposed, revoke it
immediately in the [Discord Developer Portal](https://discord.com/developers/applications)
and generate a new one.

## Deployment hardening

- Run the container as the unprivileged `leetgo` user (the provided image does).
- Grant the Discord bot only the permissions it needs: View Channels, Send Messages,
  Embed Links, Read Message History and Manage Channels (for cohorts).
- Keep `HEALTH_PORT` reachable only from your orchestrator or private network.
- Back up `data/leetgo.db` regularly and restrict filesystem access to it.
- Pin dependencies and apply Dependabot updates promptly.
