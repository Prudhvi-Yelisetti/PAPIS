"""
Watches the Docker/Podman event stream in real time.

Docker emits a JSON object per line on `docker events --format json`.
We filter for image and container events and forward them to the PAPIS API.

Relevant event types we care about:
  Image events:   pull, tag, untag, delete, import, build, load
  Container events: create, start, stop, destroy
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from typing import Optional

import httpx

log = logging.getLogger("papis.docker-watcher")

# Docker → PAPIS event type mapping
_IMAGE_EVENT_MAP = {
    "pull"   : "install",
    "import" : "install",
    "load"   : "install",
    "build"  : "install",
    "tag"    : "update",
    "untag"  : "update",
    "delete" : "remove",
}

_CONTAINER_EVENT_MAP = {
    "create" : "install",
    "start"  : "update",
    "stop"   : "update",
    "destroy": "remove",
    "kill"   : "update",
    "die"    : "update",
}


def _detect_runtime() -> Optional[str]:
    override = os.environ.get("PAPIS_CONTAINER_RUNTIME")
    if override:
        return override
    for rt in ("docker", "podman"):
        try:
            r = subprocess.run([rt, "--version"], capture_output=True, timeout=5)
            if r.returncode == 0:
                return rt
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


class DockerWatcher:
    """
    Streams `docker events --format json` and forwards relevant events
    to the PAPIS API daemon socket handler.
    """

    def __init__(self, api_base: str = "http://127.0.0.1:8765"):
        self._runtime  = _detect_runtime()
        self._api_base = api_base
        self._http     = httpx.AsyncClient(base_url=api_base, timeout=5)
        self._running  = True

    def is_available(self) -> bool:
        if not self._runtime:
            return False
        try:
            r = subprocess.run(
                [self._runtime, "info"], capture_output=True, timeout=5
            )
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    async def watch(self):
        if not self.is_available():
            log.info("Docker/Podman not available — skipping container watcher")
            return

        log.info("Starting Docker event watcher (runtime=%s)", self._runtime)

        while self._running:
            try:
                await self._stream_events()
            except Exception as e:
                log.warning("Docker event stream error: %s — retrying in 10s", e)
                await asyncio.sleep(10)

    async def stop(self):
        self._running = False
        await self._http.aclose()

    async def _stream_events(self):
        """
        Run `docker events --format json` as a subprocess and read lines
        asynchronously. Each line is a JSON object from Docker.
        """
        cmd = [
            self._runtime, "events",
            "--format", "{{json .}}",
            # Filter to only the event types we care about
            "--filter", "type=image",
            "--filter", "type=container",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        log.info("Docker event stream started (pid=%s)", proc.pid)

        async for line in proc.stdout:
            if not self._running:
                break
            line = line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                await self._handle_event(event)
            except json.JSONDecodeError:
                log.debug("Non-JSON docker event line: %s", line[:80])

        await proc.wait()

    async def _handle_event(self, event: dict):
        """
        Docker event structure (--format json):
        {
          "Type":   "image" | "container" | ...
          "Action": "pull" | "create" | "start" | ...
          "Actor":  { "ID": "sha256:...", "Attributes": { "name": "nginx", "tag": "latest", ... } }
          "time":   1234567890
        }
        """
        etype  = event.get("Type", "")
        action = event.get("Action", "")
        actor  = event.get("Actor", {})
        attrs  = actor.get("Attributes", {})

        if etype == "image":
            papis_type = _IMAGE_EVENT_MAP.get(action)
            if not papis_type:
                return

            name = attrs.get("name", actor.get("ID", "unknown"))
            tag  = attrs.get("tag", "latest")
            pkg_name = f"{name}:{tag}" if ":" not in name else name

            payload = {
                "type"   : papis_type,
                "package": pkg_name,
                "source" : self._runtime,
            }

        elif etype == "container":
            papis_type = _CONTAINER_EVENT_MAP.get(action)
            if not papis_type:
                return

            image  = attrs.get("image", "unknown")
            cname  = attrs.get("name",  actor.get("ID", "unknown")[:12])
            payload = {
                "type"   : papis_type,
                "package": f"{image}/{cname}",
                "source" : self._runtime,
            }
        else:
            return

        log.debug("Docker event → PAPIS: %s", payload)
        try:
            await self._http.post("/api/packages/event", json=payload)
        except Exception as e:
            log.warning("Failed to forward docker event: %s", e)