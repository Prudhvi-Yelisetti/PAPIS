"""
Duplicate install detection endpoints.

  GET  /api/packages/check?name=<pkg>&source=<src>
       → Fast lookup: is this package already tracked?
         Returns match info + which projects use it.
         Called by shell hooks BEFORE the install runs.

  POST /api/packages/duplicate
       → Log a duplicate install attempt as an audit event.
         Called when the user attempts to reinstall an already-tracked package.

  POST /api/packages/check-many
       → Batch version of /check for `uv sync` / `pip install -r` style
         installs that involve many packages at once.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import InstallEvent, Package, Project
from .._time import utcnow

router = APIRouter()


# ── response models ───────────────────────────────────────────────────────────

class ProjectRef(BaseModel):
    id: int
    name: str
    directory: Optional[str]

    class Config:
        from_attributes = True


class CheckResult(BaseModel):
    """
    Returned by /check.  `found` drives the shell hook's branching logic.
    """
    found: bool
    package_id: Optional[int]
    name: str
    version: Optional[str]
    source: Optional[str]
    install_type: Optional[str]
    in_inbox: bool
    projects: list[ProjectRef]          # projects currently using this package
    suggestion: str                     # human-readable hint for the terminal prompt


class BatchCheckItem(BaseModel):
    name: str
    source: Optional[str] = None


class BatchCheckResult(BaseModel):
    results: list[CheckResult]
    duplicate_count: int
    new_count: int


class DuplicateEventIn(BaseModel):
    name: str
    source: str
    attempted_version: Optional[str] = None
    resolved_action: str            # "skipped" | "reassigned" | "reinstalled" | "ignored"
    target_project_id: Optional[int] = None   # if action == "reassigned"


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.get("/check", response_model=CheckResult)
def check_package(
    name: str = Query(..., description="Package name to look up"),
    source: Optional[str] = Query(None, description="Package manager source (optional filter)"),
    db: Session = Depends(get_db),
):
    """
    Called by shell hooks before running an install command.
    Performs a case-insensitive name match, optionally filtered by source.
    """
    q = db.query(Package).filter(Package.name.ilike(name))
    if source:
        q = q.filter(Package.source == source)

    pkg = q.first()

    if not pkg:
        return CheckResult(
            found        = False,
            package_id   = None,
            name         = name,
            version      = None,
            source       = source,
            install_type = None,
            in_inbox     = False,
            projects     = [],
            suggestion   = f"Not tracked yet — proceed with install.",
        )

    projects = [
        ProjectRef(id=p.id, name=p.name, directory=p.directory)
        for p in pkg.projects
    ]

    if pkg.in_inbox:
        suggestion = (
            f"'{name}' is already installed ({pkg.version}) but not assigned to any project. "
            f"Consider assigning it instead of reinstalling."
        )
    elif projects:
        proj_names = ", ".join(p.name for p in projects)
        suggestion = (
            f"'{name}' is already installed ({pkg.version}) and used by: {proj_names}. "
            f"Assign it to another project instead of reinstalling?"
        )
    else:
        suggestion = (
            f"'{name}' is already installed ({pkg.version}). "
            f"No action needed unless you want to upgrade."
        )

    return CheckResult(
        found        = True,
        package_id   = pkg.id,
        name         = pkg.name,
        version      = pkg.version,
        source       = pkg.source,
        install_type = pkg.install_type,
        in_inbox     = pkg.in_inbox,
        projects     = projects,
        suggestion   = suggestion,
    )


@router.post("/check-many", response_model=BatchCheckResult)
def check_many_packages(
    items: list[BatchCheckItem],
    db: Session = Depends(get_db),
):
    """
    Batch duplicate check — used by the shell hook when it detects a
    requirements file install (pip install -r / uv sync).
    """
    results: list[CheckResult] = []
    dup_count = new_count = 0

    for item in items:
        # Reuse the single-check logic by calling the helper directly
        result = _check_one(item.name, item.source, db)
        results.append(result)
        if result.found:
            dup_count += 1
        else:
            new_count += 1

    return BatchCheckResult(
        results         = results,
        duplicate_count = dup_count,
        new_count       = new_count,
    )


@router.post("/duplicate")
def log_duplicate_attempt(
    body: DuplicateEventIn,
    db: Session = Depends(get_db),
):
    """
    Records a duplicate install attempt in the audit log.
    If action == "reassigned", also performs the project assignment.
    """
    pkg = db.query(Package).filter(Package.name.ilike(body.name)).first()

    if pkg:
        db.add(InstallEvent(
            package_id   = pkg.id,
            event_type   = "duplicate_attempt",
            version_new  = body.attempted_version,
            triggered_by = f"shell_hook:{body.source}",
            metadata_    = _json({
                "resolved_action"  : body.resolved_action,
                "target_project_id": body.target_project_id,
            }),
            occurred_at  = utcnow(),
        ))

        if body.resolved_action == "reassigned" and body.target_project_id:
            proj = db.query(Project).get(body.target_project_id)
            if proj and pkg not in proj.packages:
                proj.packages.append(pkg)
                pkg.in_inbox = False

        db.commit()

    return {"ok": True, "action": body.resolved_action}


# ── internal helper (shared by single + batch check) ─────────────────────────

def _check_one(name: str, source: Optional[str], db: Session) -> CheckResult:
    q = db.query(Package).filter(Package.name.ilike(name))
    if source:
        q = q.filter(Package.source == source)
    pkg = q.first()

    if not pkg:
        return CheckResult(
            found=False, package_id=None, name=name,
            version=None, source=source, install_type=None,
            in_inbox=False, projects=[],
            suggestion="Not tracked yet — proceed with install.",
        )

    projects = [
        ProjectRef(id=p.id, name=p.name, directory=p.directory)
        for p in pkg.projects
    ]
    proj_names = ", ".join(p.name for p in projects) if projects else "none"
    suggestion = (
        f"Already installed ({pkg.version}). Projects: {proj_names}."
        if pkg.projects else
        f"Already installed ({pkg.version}) — sitting in inbox."
    )
    return CheckResult(
        found=True, package_id=pkg.id, name=pkg.name,
        version=pkg.version, source=pkg.source,
        install_type=pkg.install_type, in_inbox=pkg.in_inbox,
        projects=projects, suggestion=suggestion,
    )


def _json(data: dict) -> str:
    import json
    return json.dumps(data)