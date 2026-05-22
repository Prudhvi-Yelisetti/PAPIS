import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pydantic import BaseModel
from typing import Optional
from ..database import get_db
from ..models import Package, InstallEvent, InstallSource, InstallType
from ..collectors.registry import collect_all

router = APIRouter()


class PackageOut(BaseModel):
    id: int
    name: str
    version: str
    source: str
    install_type: str
    install_date: Optional[datetime]
    size_bytes: Optional[int]
    description: Optional[str]
    is_orphan: bool
    in_inbox: bool
    project_ids: list[int]

    class Config:
        from_attributes = True


class EventIn(BaseModel):
    type: str                    # install | remove | update | pacman_transaction
    package: Optional[str] = None
    packages: Optional[list[str]] = None
    source: Optional[str] = "unknown"
    timestamp: Optional[str] = None


@router.get("/", response_model=list[PackageOut])
def list_packages(
    inbox_only: bool = False,
    source: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Package)
    if inbox_only:
        q = q.filter(Package.in_inbox == True)
    if source:
        q = q.filter(Package.source == source)
    if search:
        q = q.filter(or_(
            Package.name.ilike(f"%{search}%"),
            Package.description.ilike(f"%{search}%"),
        ))
    return [_pkg_out(p) for p in q.all()]


@router.get("/{pkg_id}", response_model=PackageOut)
def get_package(pkg_id: int, db: Session = Depends(get_db)):
    p = db.query(Package).get(pkg_id)
    if not p:
        raise HTTPException(404, "Package not found")
    return _pkg_out(p)


@router.post("/sync")
def sync_packages(db: Session = Depends(get_db)):
    """
    Re-scan all package managers and upsert into DB.

    Priority rules:
      - uv  > pip  (uv entries preserve richer metadata)
      - If a package already exists with source=uv, a pip collector hit
        for the same name will NOT overwrite it.
    """
    from ..collectors.registry import collect_all
    from ..models import InstallSource

    # Source priority: lower number wins when two collectors see the same pkg name
    SOURCE_PRIORITY: dict[str, int] = {
        InstallSource.uv     : 0,
        InstallSource.pacman : 1,
        InstallSource.aur    : 1,
        InstallSource.cargo  : 2,
        InstallSource.npm    : 2,
        InstallSource.pip    : 3,   # pip is lowest — uv supersedes it
        InstallSource.flatpak: 4,
        InstallSource.conda  : 5,
        InstallSource.unknown: 99,
    }

    collected = collect_all()
    added = updated = skipped = 0

    for info in collected:
        # Look for existing record by name + source (exact match)
        existing = (
            db.query(Package)
            .filter_by(name=info.name, source=info.source)
            .first()
        )

        if existing:
            # Update mutable fields; preserve project associations
            existing.version      = info.version
            existing.install_type = info.install_type
            existing.size_bytes   = info.size_bytes or existing.size_bytes
            existing.description  = info.description or existing.description
            existing.depends_on   = json.dumps(info.depends_on) if info.depends_on else existing.depends_on
            existing.required_by  = json.dumps(info.required_by) if info.required_by else existing.required_by
            existing.updated_at   = datetime.utcnow()
            updated += 1
            continue

        # Check if the same package name exists under a higher-priority source.
        # If so, skip this lower-priority entry to avoid duplicates in the UI.
        same_name = db.query(Package).filter_by(name=info.name).first()
        if same_name:
            existing_priority = SOURCE_PRIORITY.get(same_name.source, 99)
            new_priority      = SOURCE_PRIORITY.get(info.source, 99)
            if existing_priority <= new_priority:
                skipped += 1
                continue
            # The new entry is higher priority — update the existing record
            same_name.source       = info.source
            same_name.version      = info.version
            same_name.install_type = info.install_type
            same_name.size_bytes   = info.size_bytes or same_name.size_bytes
            same_name.description  = info.description or same_name.description
            same_name.updated_at   = datetime.utcnow()
            updated += 1
            continue

        # Genuinely new package
        db.add(Package(
            name         = info.name,
            version      = info.version,
            source       = info.source,
            install_type = info.install_type,
            install_date = info.install_date,
            size_bytes   = info.size_bytes,
            description  = info.description,
            depends_on   = json.dumps(info.depends_on) if info.depends_on else None,
            required_by  = json.dumps(info.required_by) if info.required_by else None,
            in_inbox     = True,
        ))
        added += 1

    db.commit()
    return {
        "added"  : added,
        "updated": updated,
        "skipped": skipped,
        "total"  : len(collected),
    }


@router.post("/event")
def handle_event(ev: EventIn, db: Session = Depends(get_db)):
    """Called by the daemon when it detects a package change."""
    names = [ev.package] if ev.package else (ev.packages or [])
    for name in names:
        pkg = db.query(Package).filter_by(name=name).first()
        if not pkg and ev.type == "install":
            pkg = Package(name=name, version="unknown",
                          source=ev.source or "unknown", in_inbox=True)
            db.add(pkg)
            db.flush()
        if pkg:
            db.add(InstallEvent(
                package_id  = pkg.id,
                event_type  = ev.type,
                triggered_by= "daemon",
                occurred_at = datetime.fromisoformat(ev.timestamp) if ev.timestamp else datetime.utcnow(),
            ))
    db.commit()
    return {"ok": True}


def _pkg_out(p: Package) -> PackageOut:
    return PackageOut(
        id           = p.id,
        name         = p.name,
        version      = p.version,
        source       = p.source,
        install_type = p.install_type,
        install_date = p.install_date,
        size_bytes   = p.size_bytes,
        description  = p.description,
        is_orphan    = p.is_orphan,
        in_inbox     = p.in_inbox,
        project_ids  = [pr.id for pr in p.projects],
    )