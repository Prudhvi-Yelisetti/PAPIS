"""
Scans a directory for known manifest files and suggests which installed
packages should be associated with the project.
"""
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import tomllib           # stdlib in Python 3.11+; use tomli for older
from sqlalchemy.orm import Session

from .models import Package, Project, ProjectScan


MANIFEST_HANDLERS: dict[str, str] = {
    "pyproject.toml"   : "pyproject",
    "requirements.txt" : "requirements",
    "Cargo.toml"       : "cargo",
    "package.json"     : "npm",
    "go.mod"           : "go",
    "Gemfile"          : "ruby",
    "composer.json"    : "php",
}


@dataclass
class ScanResult:
    path: str
    manifest: Optional[str]
    detected_deps: list[str] = field(default_factory=list)
    matched_package_ids: list[int] = field(default_factory=list)
    unmatched_deps: list[str] = field(default_factory=list)


def scan_directory(directory: str, db: Session) -> ScanResult:
    root = Path(directory).expanduser().resolve()
    if not root.exists():
        return ScanResult(path=str(root), manifest=None)

    # Find the first manifest file present
    manifest_file = None
    manifest_type = None
    for filename, mtype in MANIFEST_HANDLERS.items():
        candidate = root / filename
        if candidate.exists():
            manifest_file = candidate
            manifest_type = mtype
            break

    if not manifest_file:
        # Try git-based heuristic: look for any recognised file up to 2 dirs deep
        for f in root.rglob("*"):
            if f.name in MANIFEST_HANDLERS and f.stat().st_size < 1_000_000:
                manifest_file = f
                manifest_type = MANIFEST_HANDLERS[f.name]
                break

    if not manifest_file:
        return ScanResult(path=str(root), manifest=None)

    detected = _extract_deps(manifest_file, manifest_type)
    all_pkgs  = db.query(Package).all()
    pkg_by_name = {p.name.lower(): p for p in all_pkgs}

    matched   = []
    unmatched = []
    for dep in detected:
        norm = dep.lower().strip()
        if norm in pkg_by_name:
            matched.append(pkg_by_name[norm].id)
        else:
            unmatched.append(dep)

    return ScanResult(
        path                = str(manifest_file.parent),
        manifest            = manifest_type,
        detected_deps       = detected,
        matched_package_ids = matched,
        unmatched_deps      = unmatched,
    )


def _extract_deps(manifest: Path, mtype: str) -> list[str]:
    try:
        if mtype == "pyproject":
            return _parse_pyproject(manifest)
        elif mtype == "requirements":
            return _parse_requirements(manifest)
        elif mtype == "cargo":
            return _parse_cargo(manifest)
        elif mtype == "npm":
            return _parse_package_json(manifest)
        elif mtype == "go":
            return _parse_go_mod(manifest)
    except Exception as e:
        print(f"[papis scanner] failed to parse {manifest}: {e}")
    return []


def _parse_pyproject(path: Path) -> list[str]:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    deps: list[str] = []

    # PEP 517/518 – project.dependencies
    project_deps = data.get("project", {}).get("dependencies", [])
    deps.extend(_strip_version(d) for d in project_deps)

    # Poetry – tool.poetry.dependencies
    poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
    deps.extend(k for k in poetry_deps if k.lower() != "python")

    # uv – tool.uv.dependencies (same format as PEP 517)
    uv_deps = data.get("tool", {}).get("uv", {}).get("dependencies", [])
    deps.extend(_strip_version(d) for d in uv_deps)

    return list(dict.fromkeys(deps))   # deduplicate, preserve order


def _parse_requirements(path: Path) -> list[str]:
    deps = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        deps.append(_strip_version(line))
    return deps


def _parse_cargo(path: Path) -> list[str]:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    deps = list(data.get("dependencies", {}).keys())
    deps += list(data.get("dev-dependencies", {}).keys())
    return deps


def _parse_package_json(path: Path) -> list[str]:
    data = json.loads(path.read_text())
    deps: list[str] = []
    deps.extend(data.get("dependencies", {}).keys())
    deps.extend(data.get("devDependencies", {}).keys())
    return deps


def _parse_go_mod(path: Path) -> list[str]:
    deps = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("require ") or (line and not line.startswith("/")):
            parts = line.split()
            if len(parts) >= 2 and "/" in parts[0]:
                deps.append(parts[0].split("/")[-1])
    return deps


def _strip_version(dep: str) -> str:
    """'requests>=2.28.0' → 'requests'"""
    return re.split(r"[>=<!;\[\s]", dep)[0].strip()


# ── FastAPI router addition ───────────────────────────────────────────────────
from fastapi import APIRouter, Depends, Body
from .database import get_db

scan_router = APIRouter(prefix="/api/scan", tags=["scan"])


@scan_router.post("/")
def scan_project_dir(
    directory: str = Body(..., embed=True),
    project_id: Optional[int] = Body(None, embed=True),
    auto_assign: bool = Body(False, embed=True),
    db: Session = Depends(get_db),
):
    result = scan_directory(directory, db)

    # Persist scan record
    if project_id:
        db.add(ProjectScan(
            project_id   = project_id,
            scanned_path = result.path,
            manifest     = result.manifest,
            suggestions  = json.dumps(result.matched_package_ids),
        ))
        db.commit()

    # Auto-assign matched packages if requested
    if auto_assign and project_id:
        proj = db.query(Project).get(project_id)
        if proj:
            for pkg_id in result.matched_package_ids:
                pkg = db.query(Package).get(pkg_id)
                if pkg and pkg not in proj.packages:
                    proj.packages.append(pkg)
                    pkg.in_inbox = False
            db.commit()

    return {
        "path"                : result.path,
        "manifest"            : result.manifest,
        "detected_count"      : len(result.detected_deps),
        "matched_package_ids" : result.matched_package_ids,
        "unmatched_deps"      : result.unmatched_deps,
        "auto_assigned"       : auto_assign and project_id is not None,
    }