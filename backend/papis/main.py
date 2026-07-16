import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from .database import init_db
from .routers import packages, projects, analytics, exports
from .routers.duplicates    import router as duplicates_router
from .routers.ws            import router as ws_router, PackageEventPublisher
from .routers.graph         import router as graph_router
from .notifications import router as notif_router
from .scanner               import scan_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # PAPIS_DEV=1 → fast create_all() path (no Alembic, good for development)
    # PAPIS_DEV=0 or unset → run Alembic migrations (production default)
    dev_mode = os.environ.get("PAPIS_DEV", "0").strip() in ("1", "true", "yes")
    init_db(dev_mode=dev_mode)
    yield


app = FastAPI(
    title="PAPIS",
    description="Project-Aware Package Intelligence System",
    version="0.1.0",
    lifespan=lifespan,
    # Swagger UI available at http://127.0.0.1:8765/docs
    docs_url="/docs",
    redoc_url="/redoc",
)


# ── CORS ──────────────────────────────────────────────────────────────────────
# Allows both the Vite dev server and the built static frontend to call the API.
# All origins are localhost — this app never listens on a public interface.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:1420",      # Vite dev server (tauri dev / npm run dev)
        "http://127.0.0.1:1420",
        "http://localhost:5173",      # Vite fallback default port
        "http://127.0.0.1:5173",
        "http://localhost:8765",      # When frontend is served by FastAPI itself
        "http://127.0.0.1:8765",
        "tauri://localhost",          # Tauri production shell
        "http://tauri.localhost",     # Tauri on some Linux/WebKitGTK builds
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── middleware ────────────────────────────────────────────────────────────────
# Must be added AFTER CORSMiddleware so it sees the already-processed request.
app.add_middleware(PackageEventPublisher)


# ── API routers ───────────────────────────────────────────────────────────────
app.include_router(packages.router,   prefix="/api/packages",      tags=["packages"])
app.include_router(duplicates_router, prefix="/api/packages",      tags=["duplicates"])
app.include_router(projects.router,   prefix="/api/projects",      tags=["projects"])
app.include_router(analytics.router,  prefix="/api/analytics",     tags=["analytics"])
app.include_router(exports.router,    prefix="/api/exports",       tags=["exports"])
app.include_router(graph_router,      prefix="/api/graph",         tags=["graph"])
app.include_router(notif_router,      prefix="/api/notifications",  tags=["notifications"])
app.include_router(scan_router)        # prefix="/api/scan" set inside scanner.py
app.include_router(ws_router)          # WebSocket at /ws/events


# ── health check ─────────────────────────────────────────────────────────────
@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "version": "0.1.0"}


# ── serve built frontend (production / browser-only mode) ────────────────────
# When running without Tauri, the built React app is served directly by FastAPI.
# `npm run build` outputs to frontend/dist — we mount it at "/" so that
# http://127.0.0.1:8765 opens the UI and all /api/* routes still work.
#
# This block is intentionally LAST so API routes take priority over static files.
_frontend_dist = Path(__file__).parents[2] / "frontend" / "dist"
if _frontend_dist.exists():
    # Serve static assets (JS, CSS, images) under the root path
    app.mount(
        "/",
        StaticFiles(directory=str(_frontend_dist), html=True),
        name="frontend",
    )