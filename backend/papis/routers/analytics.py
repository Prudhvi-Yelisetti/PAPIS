from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from pydantic import BaseModel
from typing import Optional
from ..database import get_db
from ..models import Package, Project, InstallEvent, InstallSource, InstallType

router = APIRouter()


class OrphanInfo(BaseModel):
    id: int
    name: str
    version: str
    source: str
    size_bytes: Optional[int]


class StorageBreakdown(BaseModel):
    source: str
    package_count: int
    total_bytes: int


class DependencyBloat(BaseModel):
    name: str
    version: str
    required_by_count: int
    size_bytes: Optional[int]
    install_type: str


class SystemSummary(BaseModel):
    total_packages: int
    inbox_count: int
    orphan_count: int
    project_count: int
    total_size_bytes: int
    sources: dict[str, int]


@router.get("/summary", response_model=SystemSummary)
def summary(db: Session = Depends(get_db)):
    pkgs = db.query(Package).all()
    sources: dict[str, int] = {}
    total_size = 0
    orphans = 0
    inbox = 0
    for p in pkgs:
        sources[p.source] = sources.get(p.source, 0) + 1
        total_size += p.size_bytes or 0
        if p.is_orphan:
            orphans += 1
        if p.in_inbox:
            inbox += 1
    return SystemSummary(
        total_packages   = len(pkgs),
        inbox_count      = inbox,
        orphan_count     = orphans,
        project_count    = db.query(Project).filter_by(is_archived=False).count(),
        total_size_bytes = total_size,
        sources          = sources,
    )


@router.get("/orphans", response_model=list[OrphanInfo])
def list_orphans(db: Session = Depends(get_db)):
    """
    Packages that are:
    - explicitly installed
    - not assigned to any project
    - not required by any other package
    """
    pkgs = (
        db.query(Package)
        .filter(Package.install_type == InstallType.explicit)
        .filter(Package.in_inbox == True)
        .all()
    )
    return [
        OrphanInfo(
            id=p.id, name=p.name, version=p.version,
            source=p.source, size_bytes=p.size_bytes,
        )
        for p in pkgs
        if not p.required_by or p.required_by == "[]"
    ]


@router.get("/storage", response_model=list[StorageBreakdown])
def storage_by_source(db: Session = Depends(get_db)):
    rows = (
        db.query(
            Package.source,
            func.count(Package.id).label("pkg_count"),
            func.coalesce(func.sum(Package.size_bytes), 0).label("total"),
        )
        .group_by(Package.source)
        .all()
    )
    return [
        StorageBreakdown(source=r.source, package_count=r.pkg_count, total_bytes=r.total)
        for r in rows
    ]


@router.get("/storage/by-project")
def storage_by_project(db: Session = Depends(get_db)):
    projects = db.query(Project).filter_by(is_archived=False).all()
    result = []
    for proj in projects:
        total = sum(p.size_bytes or 0 for p in proj.packages)
        result.append({
            "project_id": proj.id,
            "project_name": proj.name,
            "package_count": len(proj.packages),
            "total_bytes": total,
        })
    return sorted(result, key=lambda x: x["total_bytes"], reverse=True)


@router.get("/bloat", response_model=list[DependencyBloat])
def dependency_bloat(
    min_size_mb: float = 50,
    db: Session = Depends(get_db),
):
    """Large dependency packages not directly assigned to any project."""
    min_bytes = int(min_size_mb * 1024 * 1024)
    pkgs = (
        db.query(Package)
        .filter(Package.install_type.in_([InstallType.dependency, InstallType.transitive]))
        .filter(Package.size_bytes >= min_bytes)
        .filter(Package.in_inbox == True)
        .order_by(Package.size_bytes.desc())
        .all()
    )
    return [
        DependencyBloat(
            name=p.name, version=p.version,
            required_by_count=len(p.required_by.split(",")) if p.required_by and p.required_by != "[]" else 0,
            size_bytes=p.size_bytes,
            install_type=p.install_type,
        )
        for p in pkgs
    ]


@router.get("/timeline")
def install_timeline(
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """Recent install/remove events with package names."""
    events = (
        db.query(InstallEvent)
        .order_by(InstallEvent.occurred_at.desc())
        .limit(limit)
        .all()
    )
    result = []
    for ev in events:
        pkg_name = ev.package.name if ev.package else "unknown"
        result.append({
            "event_id"    : ev.id,
            "event_type"  : ev.event_type,
            "package"     : pkg_name,
            "version_old" : ev.version_old,
            "version_new" : ev.version_new,
            "triggered_by": ev.triggered_by,
            "occurred_at" : ev.occurred_at.isoformat(),
        })
    return result


@router.get("/missing-deps")
def missing_dependencies(db: Session = Depends(get_db)):
    """
    For each project, check if packages listed in required_by fields
    are actually installed and tracked.
    """
    import json
    all_names = {p.name for p in db.query(Package.name).all()}
    projects  = db.query(Project).filter_by(is_archived=False).all()
    report    = []

    for proj in projects:
        missing = []
        for pkg in proj.packages:
            deps = json.loads(pkg.depends_on or "[]")
            for dep in deps:
                dep_name = dep.split(">")[0].split("<")[0].split("=")[0].strip()
                if dep_name and dep_name not in all_names:
                    missing.append({"package": pkg.name, "missing_dep": dep_name})
        if missing:
            report.append({"project": proj.name, "missing": missing})

    return report