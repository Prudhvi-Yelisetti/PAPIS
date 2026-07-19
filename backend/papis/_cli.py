"""
CLI entry points defined in pyproject.toml [project.scripts].

  papis-api     Start the FastAPI server (uvicorn).
  papis-daemon  Start the background watcher daemon.

Environment variables:
  PAPIS_HOST           API bind host   (default: 127.0.0.1)
  PAPIS_PORT           API bind port   (default: 8765)
  PAPIS_LOG_LEVEL      uvicorn log level (default: info)
  PAPIS_DB_PATH        Override SQLite database path.
  PAPIS_API            Daemon → API base URL (default: http://127.0.0.1:8765)

Note: startup always uses create_all() now (safe, idempotent). Real schema
migrations are an explicit manual step:  cd backend && alembic upgrade head
See TROUBLESHOOTING.md for why automatic-migration-at-startup was removed.
"""
from __future__ import annotations

import os
import sys


def run_api():
    """
    Entry point for `papis-api`.
    Starts uvicorn with the FastAPI app.

    Execs into `python -m uvicorn papis.main:app ...` rather than calling
    uvicorn.run() in-process, kept from an earlier debugging pass where it
    was suspected (incorrectly, as it turned out) to matter. The actual
    root cause of the startup hang investigated then was main.py running
    Alembic automatically on every startup, which has since been removed
    — see main.py's lifespan and TROUBLESHOOTING.md. Left as execvp since
    it's proven reliable (6/6 in testing) and there's no reason to
    reintroduce risk by changing it without a concrete need to.
    """
    host      = os.environ.get("PAPIS_HOST",      "127.0.0.1")
    port      = os.environ.get("PAPIS_PORT",      "8765")
    log_level = os.environ.get("PAPIS_LOG_LEVEL", "info")

    os.execvp(sys.executable, [
        sys.executable, "-m", "uvicorn",
        "papis.main:app",
        "--host", host,
        "--port", port,
        "--log-level", log_level,
    ])


def run_daemon():
    """
    Entry point for `papis-daemon`.
    Starts the async background watcher daemon.
    """
    import asyncio
    # Ensure the backend package is importable when running from outside the venv
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parents[2]))

    # Lazy import so the daemon module isn't loaded when just checking --help
    from daemon.papis_daemon import main  # type: ignore[import]
    asyncio.run(main())