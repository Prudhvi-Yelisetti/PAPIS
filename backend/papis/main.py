from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import init_db
from .routers import packages, projects, analytics, exports
from .routers.duplicates import router as duplicates_router
from .scanner import scan_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(
    title="PAPIS",
    description="Project-Aware Package Intelligence System",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:1420", "tauri://localhost"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(packages.router,    prefix="/api/packages",  tags=["packages"])
app.include_router(duplicates_router,  prefix="/api/packages",  tags=["duplicates"])
app.include_router(projects.router,    prefix="/api/projects",  tags=["projects"])
app.include_router(analytics.router,   prefix="/api/analytics", tags=["analytics"])
app.include_router(exports.router,     prefix="/api/exports",   tags=["exports"])
app.include_router(scan_router)

@app.get("/health")
def health():
    return {"status": "ok"}