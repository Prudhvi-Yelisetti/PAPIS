"""
CLI entry points defined in pyproject.toml [project.scripts].

  papis-api     Start the FastAPI server (uvicorn).
  papis-daemon  Start the background watcher daemon.

Environment variables:
  PAPIS_DEV=1          Use create_all() instead of Alembic (dev mode).
  PAPIS_HOST           API bind host   (default: 127.0.0.1)
  PAPIS_PORT           API bind port   (default: 8765)
  PAPIS_LOG_LEVEL      uvicorn log level (default: info)
  PAPIS_DB_PATH        Override SQLite database path.
  PAPIS_API            Daemon → API base URL (default: http://127.0.0.1:8765)
"""
from __future__ import annotations

import os
import sys


def run_api():
    """
    Entry point for `papis-api`.
    Starts uvicorn with the FastAPI app.

    Examples
    --------
    # Normal use (production, Alembic migrations):
    papis-api

    # Development mode (create_all, hot-reload):
    PAPIS_DEV=1 papis-api --reload
    """
    import uvicorn

    dev_mode  = os.environ.get("PAPIS_DEV", "").strip() in ("1", "true", "yes")
    host      = os.environ.get("PAPIS_HOST",      "127.0.0.1")
    port      = int(os.environ.get("PAPIS_PORT",  "8765"))
    log_level = os.environ.get("PAPIS_LOG_LEVEL", "info")

    # Pass dev_mode into the app via an env var that main.py reads.
    # We can't pass it directly to uvicorn's factory, so we set it here.
    os.environ["PAPIS_DEV"] = "1" if dev_mode else "0"

    # Forward any extra CLI args (e.g. --reload) to uvicorn
    extra_args = sys.argv[1:]

    uvicorn.main([
        "papis.main:app",
        "--host",      host,
        "--port",      str(port),
        "--log-level", log_level,
        *extra_args,
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