"""Package entry point for ``python -m leetgo``."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from pydantic import ValidationError

from . import __version__
from .bot import LeetGo
from .config import Settings, get_settings
from .logging_setup import setup_logging

logger = logging.getLogger("LeetGo")
_shutdown_tasks: set[asyncio.Task[None]] = set()


def _print_config_error(exc: ValidationError) -> None:
    print("LeetGo could not start: invalid configuration.\n")
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]).upper()
        print(f"  • {location}: {error['msg']}")
    print("\nCopy .env.example to .env and set BOT_TOKEN.")


async def run(settings: Settings) -> None:
    """Start the bot and handle SIGINT/SIGTERM gracefully."""
    bot = LeetGo(settings)
    loop = asyncio.get_running_loop()

    def shutdown() -> None:
        logger.info("Shutdown signal received")
        task = asyncio.create_task(bot.close())
        _shutdown_tasks.add(task)
        task.add_done_callback(_shutdown_tasks.discard)

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(sig, shutdown)

    try:
        await bot.start(settings.token)
    finally:
        await bot.close()


def main() -> None:
    """CLI entry point."""
    try:
        settings = get_settings()
    except ValidationError as exc:
        _print_config_error(exc)
        raise SystemExit(1) from None

    setup_logging(settings.log_level, settings.log_file, settings.log_json)
    logger.info("Starting LeetGo v%s (%s)", __version__, settings.environment)
    try:
        asyncio.run(run(settings))
    except KeyboardInterrupt:  # pragma: no cover - interactive shutdown
        pass
    except Exception:
        logger.exception("Fatal error during startup")
        raise SystemExit(1) from None
    finally:
        logger.info("LeetGo stopped")


if __name__ == "__main__":
    main()
