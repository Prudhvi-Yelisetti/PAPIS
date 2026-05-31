"""
PAPIS background daemon.
Runs as a systemd --user service. Listens for:
  - pacman hook signals   (via a named pipe / socket message)
  - inotify events on pip/cargo/npm dirs
  - D-Bus signals from Flatpak

On any event it calls the PAPIS API to record the change and optionally
fires a desktop notification via libnotify.
"""
import asyncio
import json
import logging
import os
import signal
import socket
import sys
from datetime import datetime
from pathlib import Path

import httpx
import inotify_simple    # pip install inotify-simple
import notify2           # pip install notify2

from watchers.docker_watcher import DockerWatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [papis-daemon] %(levelname)s %(message)s",
)
log = logging.getLogger("papis-daemon")

API_BASE    = os.getenv("PAPIS_API", "http://127.0.0.1:8765")
PIPE_PATH   = Path("/run/user") / str(os.getuid()) / "papis.sock"
WATCH_DIRS  = [
    Path.home() / ".local" / "lib",   # pip user installs
    Path.home() / ".cargo" / "bin",   # cargo installs
    Path.home() / ".npm",             # npm global
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [papis-daemon] %(levelname)s %(message)s",
)
log = logging.getLogger("papis-daemon")

API_BASE    = os.getenv("PAPIS_API", "http://127.0.0.1:8765")
PIPE_PATH   = Path("/run/user") / str(os.getuid()) / "papis.sock"
WATCH_DIRS  = [
    Path.home() / ".local" / "lib",   # pip user installs
    Path.home() / ".cargo" / "bin",   # cargo installs
    Path.home() / ".npm",             # npm global
]


class PapisDaemon:
    def __init__(self):
        self._running = True
        self._http = httpx.AsyncClient(base_url=API_BASE, timeout=5)
        self._docker = DockerWatcher(api_base=API_BASE)
        notify2.init("PAPIS")

    async def start(self):
        log.info("PAPIS daemon starting (API=%s)", API_BASE)
        await asyncio.gather(
            self._unix_socket_listener(),
            self._inotify_watcher(),
            self._docker.watch(),
        )

    async def stop(self):
        self._running = False
        await self._docker.stop()
        await self._http.aclose()

    # ── Unix socket: receives messages from pacman hooks ──────────────────────
    async def _unix_socket_listener(self):
        PIPE_PATH.parent.mkdir(parents=True, exist_ok=True)
        if PIPE_PATH.exists():
            PIPE_PATH.unlink()

        srv = await asyncio.start_unix_server(self._handle_hook_msg, str(PIPE_PATH))
        log.info("Listening on %s", PIPE_PATH)
        async with srv:
            await srv.serve_forever()

    async def _handle_hook_msg(self, reader, writer):
        data = await reader.read(4096)
        writer.close()
        try:
            msg = json.loads(data)
            await self._process_event(msg)
        except Exception as e:
            log.error("hook msg parse error: %s", e)

    # ── inotify: watch filesystem dirs for pip/cargo/npm changes ─────────────
    async def _inotify_watcher(self):
        inotify = inotify_simple.INotify()
        flags = inotify_simple.flags.CREATE | inotify_simple.flags.DELETE
        wd_map = {}
        for d in WATCH_DIRS:
            if d.exists():
                wd = inotify.add_watch(str(d), flags)
                wd_map[wd] = d
                log.info("Watching %s", d)

        loop = asyncio.get_event_loop()
        while self._running:
            events = await loop.run_in_executor(None, inotify.read, 500)
            for ev in events:
                d = wd_map.get(ev.wd)
                if d:
                    await self._process_filesystem_event(d, ev)

    async def _process_filesystem_event(self, directory: Path, event):
        pkg_name = event.name
        ev_type  = "install" if event.mask & inotify_simple.flags.CREATE else "remove"
        log.info("fs event: %s %s in %s", ev_type, pkg_name, directory)
        await self._notify_api({
            "type"     : ev_type,
            "package"  : pkg_name,
            "source"   : self._infer_source(directory),
            "timestamp": datetime.utcnow().isoformat(),
        })

    async def _process_event(self, msg: dict):
        log.info("hook event: %s", msg)
        ev_type  = msg.get("type", "")
        pkg_name = msg.get("package", "?")
        uv_mode  = msg.get("uv_mode", "")

        await self._notify_api(msg)

        if ev_type == "install":
            mode_label = f" ({uv_mode})" if uv_mode else ""
            title = f"Package installed: {pkg_name}{mode_label}"
            body  = "PAPIS: assign it to a project in the dashboard."
            self._desktop_notify(title, body)
            await self._persist_notification(title, body, kind="success",
                                             package=pkg_name,
                                             source=msg.get("source", ""))

        elif ev_type == "remove":
            title = f"Package removed: {pkg_name}"
            body  = "PAPIS: package has been untracked."
            self._desktop_notify(title, body)
            await self._persist_notification(title, body, kind="info",
                                             package=pkg_name,
                                             source=msg.get("source", ""))

        elif ev_type == "duplicate":
            title = f"Already installed: {pkg_name}"
            body  = "PAPIS: this package is already tracked. Check your projects."
            self._desktop_notify(title, body)
            await self._persist_notification(title, body, kind="warning",
                                             package=pkg_name,
                                             source=msg.get("source", ""))

        elif ev_type == "uv_sync":
            log.info("uv sync detected — triggering full package sync")
            try:
                r = await self._http.post("/api/packages/sync")
                data = r.json()
                added   = data.get("added", 0)
                updated = data.get("updated", 0)
                title = "uv sync complete"
                body  = f"PAPIS: {added} new, {updated} updated packages."
                self._desktop_notify(title, body)
                await self._persist_notification(title, body, kind="info")
            except Exception as e:
                log.warning("sync after uv sync failed: %s", e)

    async def _notify_api(self, payload: dict):
        try:
            r = await self._http.post("/api/packages/event", json=payload)
            r.raise_for_status()
        except Exception as e:
            log.warning("API notify failed: %s", e)

    async def _persist_notification(
        self,
        title: str,
        body: str,
        kind: str = "info",
        package: str = "",
        source: str = "",
    ):
        """
        POST to the PAPIS notification center so the in-app
        notification history is always in sync with desktop alerts.
        """
        payload = {
            "title"  : title,
            "body"   : body,
            "kind"   : kind,
            "package": package or None,
            "source" : source  or None,
        }
        try:
            await self._http.post("/api/notifications/", json=payload)
        except Exception as e:
            log.warning("Failed to persist notification: %s", e)

    def _desktop_notify(self, title: str, body: str):
        try:
            n = notify2.Notification(title, body, "dialog-information")
            n.set_urgency(notify2.URGENCY_NORMAL)
            n.show()
        except Exception as e:
            log.warning("notify2 failed: %s", e)

    @staticmethod
    def _infer_source(directory: Path) -> str:
        s = str(directory)
        if ".cargo" in s: return "cargo"
        if ".npm"   in s: return "npm"
        if ".local" in s: return "pip"
        return "unknown"


async def main():
    daemon = PapisDaemon()
    loop   = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.create_task(daemon.stop()))
    loop.add_signal_handler(signal.SIGINT,  lambda: asyncio.create_task(daemon.stop()))
    await daemon.start()

if __name__ == "__main__":
    asyncio.run(main())