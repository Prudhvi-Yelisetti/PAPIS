"""
WebSocket live event feed.

  WS /ws/events

Clients connect and receive a JSON message for every package event as it
happens — installs, removals, updates, duplicates, uv_sync completions.

The daemon and the /api/packages/event endpoint both call
`event_bus.publish()` to push events to all connected clients.

Architecture:
  - EventBus: a simple in-process pub/sub using asyncio.Queue per client.
  - PackageEventMiddleware: thin wrapper that auto-publishes after any
    POST to /api/packages/event succeeds.
  - The WebSocket route reads from the client's queue and streams JSON.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .._time import utcnow

log = logging.getLogger("papis.ws")
router = APIRouter()


# ── Event bus ─────────────────────────────────────────────────────────────────

class EventBus:
    """
    Singleton pub/sub bus.  Each connected WebSocket client gets its own
    asyncio.Queue.  Publishing puts the event onto every active queue.

    The lock is created LAZILY on first actual use inside a running event
    loop, not in __init__. Creating asyncio.Lock() at module-import time
    (before uvicorn's event loop exists) was found to cause the app to
    hang indefinitely on startup — the lock silently binds to whatever
    loop happens to be "current" at construction time, which doesn't
    match the loop uvicorn actually runs the app on. See TROUBLESHOOTING.md.
    """

    def __init__(self):
        self._clients: set[asyncio.Queue] = set()
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        async with self._get_lock():
            self._clients.add(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue):
        async with self._get_lock():
            self._clients.discard(q)

    async def publish(self, event: dict):
        """Broadcast event to all connected clients (non-blocking)."""
        if not self._clients:
            return
        payload = json.dumps(event)
        async with self._get_lock():
            dead: list[asyncio.Queue] = []
            for q in self._clients:
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    # Client is not consuming fast enough — drop oldest item
                    try:
                        q.get_nowait()
                        q.put_nowait(payload)
                    except Exception:
                        dead.append(q)
            for q in dead:
                self._clients.discard(q)

    @property
    def client_count(self) -> int:
        return len(self._clients)


# Module-level singleton — imported everywhere
event_bus = EventBus()


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@router.websocket("/ws/events")
async def websocket_events(ws: WebSocket):
    """
    Client connects here to receive a live stream of package events.

    Each message is a JSON object:
    {
      "type":       "install" | "remove" | "update" | "duplicate_attempt" | "uv_sync" | "ping",
      "package":    "ruff",
      "source":     "uv",
      "version":    "0.4.3",
      "occurred_at":"2024-05-01T12:34:56",
      "projects":   ["my-project"]          // if already assigned
    }
    """
    await ws.accept()
    q = await event_bus.subscribe()
    log.info("WebSocket client connected (total=%d)", event_bus.client_count)

    # Send a welcome/sync message with current stats
    await ws.send_json({
        "type"       : "connected",
        "clients"    : event_bus.client_count,
        "occurred_at": utcnow().isoformat(),
    })

    # Start a ping task to keep the connection alive through proxies / Tauri
    ping_task = asyncio.create_task(_ping_loop(ws))

    try:
        while True:
            # Wait for the next event from the bus (with timeout for pings)
            try:
                payload = await asyncio.wait_for(q.get(), timeout=20)
                await ws.send_text(payload)
            except asyncio.TimeoutError:
                pass   # ping_task handles keepalive
    except WebSocketDisconnect:
        log.info("WebSocket client disconnected")
    except Exception as e:
        log.warning("WebSocket error: %s", e)
    finally:
        ping_task.cancel()
        await event_bus.unsubscribe(q)


async def _ping_loop(ws: WebSocket):
    """Send a ping frame every 15 s to keep the connection alive."""
    while True:
        await asyncio.sleep(15)
        try:
            await ws.send_json({"type": "ping", "occurred_at": utcnow().isoformat()})
        except Exception:
            break


# ── Middleware: auto-publish after /api/packages/event ───────────────────────

class PackageEventPublisher(BaseHTTPMiddleware):
    """
    After a successful POST to /api/packages/event, read the request body
    and re-publish the event to all WebSocket clients.

    We read the body twice (once by FastAPI, once here) using a cached body
    approach compatible with Starlette's middleware chain.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        if (
            request.method == "POST"
            and request.url.path == "/api/packages/event"
            and response.status_code == 200
        ):
            try:
                body = await self._get_cached_body(request)
                if body:
                    event = json.loads(body)
                    event.setdefault("occurred_at", utcnow().isoformat())
                    asyncio.create_task(event_bus.publish(event))
            except Exception as e:
                log.debug("EventPublisher middleware error: %s", e)

        return response

    @staticmethod
    async def _get_cached_body(request: Request) -> bytes:
        # Starlette caches the body in request.state after first read
        if not hasattr(request.state, "_body"):
            request.state._body = await request.body()
        return request.state._body


# ── Helper: publish from anywhere in the backend ─────────────────────────────

async def publish_event(
    event_type: str,
    package: str,
    source: str = "unknown",
    version: str | None = None,
    extra: dict | None = None,
):
    """
    Convenience wrapper — call this from routers, collectors, or the daemon
    API handler to push an event to all WebSocket clients.

    Example:
        from .routers.ws import publish_event
        await publish_event("install", "ruff", source="uv", version="0.4.3")
    """
    payload: dict[str, Any] = {
        "type"       : event_type,
        "package"    : package,
        "source"     : source,
        "occurred_at": utcnow().isoformat(),
    }
    if version:
        payload["version"] = version
    if extra:
        payload.update(extra)
    await event_bus.publish(payload)