from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from ..database import get_db
from ..models import Package, Project, package_project

router = APIRouter()


class ProjectIn(BaseModel):
    name: str
    description: Optional[str] = None
    directory: Optional[str] = None
    tags: Optional[list[str]] = None


class ProjectOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    directory: Optional[str]
    is_archived: bool
    package_count: int

    class Config:
        from_attributes = True


@router.get("/", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return [_proj_out(p) for p in db.query(Project).filter_by(is_archived=False).all()]


@router.post("/", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectIn, db: Session = Depends(get_db)):
    if db.query(Project).filter_by(name=body.name).first():
        raise HTTPException(409, "Project name already exists")
    import json
    p = Project(
        name        = body.name,
        description = body.description,
        directory   = body.directory,
        tags        = json.dumps(body.tags or []),
    )
    db.add(p); db.commit(); db.refresh(p)
    return _proj_out(p)


@router.patch("/{proj_id}", response_model=ProjectOut)
def update_project(proj_id: int, body: ProjectIn, db: Session = Depends(get_db)):
    p = _get_or_404(proj_id, db)
    if body.name:         p.name        = body.name
    if body.description:  p.description = body.description
    if body.directory:    p.directory   = body.directory
    db.commit(); db.refresh(p)
    return _proj_out(p)


@router.delete("/{proj_id}", status_code=204)
def delete_project(
    proj_id: int,
    remove_orphaned_packages: bool = False,
    db: Session = Depends(get_db),
):
    p = _get_or_404(proj_id, db)
    if remove_orphaned_packages:
        # Delete packages that have no other project associations
        for pkg in list(p.packages):
            if len(pkg.projects) == 1:   # only this project
                db.delete(pkg)
    db.delete(p); db.commit()


@router.post("/{proj_id}/packages/{pkg_id}", status_code=204)
def assign_package(proj_id: int, pkg_id: int, db: Session = Depends(get_db)):
    proj = _get_or_404(proj_id, db)
    pkg  = db.query(Package).get(pkg_id)
    if not pkg:
        raise HTTPException(404, "Package not found")
    if pkg not in proj.packages:
        proj.packages.append(pkg)
        pkg.in_inbox = False          # move out of inbox
    db.commit()


@router.delete("/{proj_id}/packages/{pkg_id}", status_code=204)
def unassign_package(proj_id: int, pkg_id: int, db: Session = Depends(get_db)):
    proj = _get_or_404(proj_id, db)
    pkg  = db.query(Package).get(pkg_id)
    if pkg and pkg in proj.packages:
        proj.packages.remove(pkg)
        # Back to inbox if no projects remain
        if not pkg.projects:
            pkg.in_inbox = True
    db.commit()


@router.get("/{proj_id}/packages")
def list_project_packages(proj_id: int, db: Session = Depends(get_db)):
    from .packages import _pkg_out, PackageOut
    proj = _get_or_404(proj_id, db)
    return [_pkg_out(p) for p in proj.packages]


def _get_or_404(proj_id: int, db: Session) -> Project:
    p = db.query(Project).get(proj_id)
    if not p:
        raise HTTPException(404, "Project not found")
    return p


def _proj_out(p: Project) -> ProjectOut:
    return ProjectOut(
        id            = p.id,
        name          = p.name,
        description   = p.description,
        directory     = p.directory,
        is_archived   = p.is_archived,
        package_count = len(p.packages),
    )