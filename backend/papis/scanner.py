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

from .models import Package, Project, ProjectScan, PackageLocation, InstallSource


MANIFEST_HANDLERS: dict[str, str] = {
    "pyproject.toml"   : "pyproject",
    "requirements.txt" : "requirements",
    "Cargo.toml"       : "cargo",
    "package.json"     : "npm",
    "go.mod"           : "go",
    "Gemfile"          : "ruby",
    "composer.json"    : "php",
}

# Which package sources are plausible matches for each manifest ecosystem.
# Prevents cross-ecosystem name collisions (e.g. an npm "types" package
# incorrectly matching an unrelated cargo crate also named "types").
MANIFEST_SOURCE_MAP: dict[str, set[str]] = {
    "pyproject"   : {"pip", "uv", "conda"},
    "requirements": {"pip", "uv", "conda"},
    "cargo"       : {"cargo"},
    "npm"         : {"npm"},
    "go"          : set(),   # no Go collector exists yet — name-only fallback
    "ruby"        : set(),
    "php"         : set(),
}

# Directories never worth descending into during a bulk scan — build output,
# dependency caches, and VCS internals. Keeps the walk fast even on large
# monorepos with node_modules/target/.venv sitting right next to manifests.
SKIP_DIRS = {
    "node_modules", ".git", "target", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".nuxt", "vendor", ".cargo", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "__MACOSX", "egg-info",
}

BULK_SCAN_MAX_DEPTH = 5


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
    pkg_by_name = {_normalize_name(p.name): p for p in all_pkgs}

    matched   = []
    unmatched = []
    for dep in detected:
        norm = _normalize_name(dep)
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
        if not line or line.startswith("//") or line.startswith("module ") or line.startswith("go "):
            continue
        parts = line.split()
        if line.startswith("require "):
            # Single-line style: "require github.com/foo/bar v1.2.3"
            # → module path is parts[1], not parts[0].
            if len(parts) >= 2 and "/" in parts[1]:
                deps.append(parts[1].split("/")[-1])
        elif len(parts) >= 2 and "/" in parts[0]:
            # Block style: bare "github.com/foo/bar v1.2.3" line inside
            # a `require (...)` block — module path is parts[0].
            deps.append(parts[0].split("/")[-1])
    return deps


def _strip_version(dep: str) -> str:
    """'requests>=2.28.0' → 'requests'"""
    return re.split(r"[>=<!;\[\s]", dep.strip())[0].strip()


def _normalize_name(name: str) -> str:
    """
    PEP 503-style normalization, applied generically across ecosystems so
    'types-requests', 'types_requests', and 'Types.Requests' all collapse
    to the same lookup key. Cheap and correct enough for cross-referencing
    against tracked package names.
    """
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def find_all_manifests(root: Path, max_depth: int = BULK_SCAN_MAX_DEPTH) -> list[Path]:
    """
    Find every recognized manifest file under `root`, not just the first
    one — real projects commonly have several at once (e.g. this very repo:
    backend/pyproject.toml + frontend/package.json + src-tauri/Cargo.toml).
    Skips heavy/irrelevant directories so the walk stays fast regardless of
    how large node_modules or target/ get.
    """
    found: list[Path] = []

    def _walk(d: Path, depth: int):
        if depth > max_depth:
            return
        try:
            entries = list(d.iterdir())
        except (PermissionError, OSError):
            return
        for child in entries:
            if child.is_file():
                if child.name in MANIFEST_HANDLERS:
                    found.append(child)
            elif child.is_dir():
                if child.name in SKIP_DIRS or child.name.startswith("."):
                    continue
                _walk(child, depth + 1)

    _walk(root, 0)
    return found


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

# ── Bulk scan: all registered projects at once ────────────────────────────────
#
# Efficiency notes:
#   - Packages are loaded into an in-memory dict ONCE (single query), so
#     matching is O(1) dict lookups instead of a DB query per candidate.
#   - Every project's directory is walked exactly once, for every manifest
#     type present (not just the first found) — real projects commonly mix
#     several ecosystems in one tree (this repo included).
#   - Matching is ecosystem-aware (MANIFEST_SOURCE_MAP) to avoid cross-
#     language name collisions.
#   - Every registered project is evaluated independently with no early
#     exit, so a package used by N projects correctly gets linked to all N
#     in a single pass — no repeated scans needed.
#   - Exactly one db.commit() at the very end, not per-match.
#   - Files outside any registered project's directory are never visited at
#     all, so "packages not tied to a known project stay untouched" holds
#     by construction rather than needing an explicit check.

@dataclass
class ProjectMatch:
    project_id: int
    project_name: str
    package_id: int
    package_name: str
    manifest_type: str


@dataclass
class BulkScanResult:
    projects_scanned: int
    manifests_found: int
    new_links: list[ProjectMatch] = field(default_factory=list)
    already_linked_count: int = 0
    unmatched_deps: dict[str, list[str]] = field(default_factory=dict)  # project name -> dep names


def bulk_scan_all_projects(db: Session) -> BulkScanResult:
    projects = (
        db.query(Project)
        .filter(Project.is_archived == False)
        .filter(Project.directory.isnot(None))
        .filter(Project.directory != "")
        .all()
    )

    # One query, build the lookup table once.
    all_packages = db.query(Package).all()
    pkg_by_name: dict[str, list[Package]] = {}
    for pkg in all_packages:
        pkg_by_name.setdefault(_normalize_name(pkg.name), []).append(pkg)

    result = BulkScanResult(projects_scanned=0, manifests_found=0)

    for proj in projects:
        root = Path(proj.directory).expanduser().resolve()
        if not root.exists():
            continue

        result.projects_scanned += 1
        manifests = find_all_manifests(root)
        result.manifests_found += len(manifests)

        # Track already-linked package ids for this project to avoid
        # redundant relationship-append work.
        already_linked_ids = {p.id for p in proj.packages}
        project_unmatched: list[str] = []

        for manifest_path in manifests:
            mtype = MANIFEST_HANDLERS[manifest_path.name]
            allowed_sources = MANIFEST_SOURCE_MAP.get(mtype, set())

            try:
                dep_names = _extract_deps(manifest_path, mtype)
            except Exception:
                continue

            for dep in dep_names:
                norm = _normalize_name(dep)
                candidates = pkg_by_name.get(norm)
                if not candidates:
                    project_unmatched.append(dep)
                    continue

                # Prefer a candidate matching this manifest's ecosystem;
                # fall back to any name match if no source-typed hit exists
                # (covers untracked ecosystems like Go/Ruby/PHP gracefully).
                match = next(
                    (c for c in candidates if c.source in allowed_sources),
                    candidates[0],
                )

                if match.id in already_linked_ids:
                    result.already_linked_count += 1
                    continue

                proj.packages.append(match)
                match.in_inbox = False
                already_linked_ids.add(match.id)

                result.new_links.append(ProjectMatch(
                    project_id    = proj.id,
                    project_name  = proj.name,
                    package_id    = match.id,
                    package_name  = match.name,
                    manifest_type = mtype,
                ))

        if project_unmatched:
            result.unmatched_deps[proj.name] = sorted(set(project_unmatched))

    db.commit()
    return result


@scan_router.post("/bulk")
def bulk_scan(db: Session = Depends(get_db)):
    """
    Scan every registered project's directory (all manifests found within
    it, not just one), auto-link any matching inbox/tracked packages to
    the correct project(s), and leave everything else untouched. Safe to
    call repeatedly — already-linked packages are skipped, never duplicated.
    """
    result = bulk_scan_all_projects(db)

    return {
        "projects_scanned"     : result.projects_scanned,
        "manifests_found"      : result.manifests_found,
        "new_links_count"      : len(result.new_links),
        "new_links"            : [
            {
                "project_id"   : m.project_id,
                "project_name" : m.project_name,
                "package_id"   : m.package_id,
                "package_name" : m.package_name,
                "manifest_type": m.manifest_type,
            }
            for m in result.new_links
        ],
        "already_linked_count" : result.already_linked_count,
        "unmatched_deps"       : result.unmatched_deps,
    }


# ── Full-disk scan: entire filesystem, not just registered projects ──────────
#
# Distinct from bulk_scan_all_projects() above in one key way: this walks
# a much broader root (default: the user's home directory) looking for
# manifest files ANYWHERE, not just inside directories that are already
# registered as projects.
#
#   - Manifest inside (or is) a registered project's directory
#       -> identical behaviour to bulk_scan_all_projects: link the
#          matching package to that project.
#   - Manifest anywhere else
#       -> record a PackageLocation "orphan" mapping instead of ignoring
#          it. The package is known to be used at this file location on
#          disk even though no project claims it (yet).
#
# Also separately walks for Cargo.lock files specifically (wherever they
# sit) and uses their real RESOLVED dependency graph to update depends_on
# on matching tracked cargo packages — Cargo.lock is the one manifest
# format we already have genuine inter-package graph parsing for
# (_parse_cargo_lock, from the cargo collector), as opposed to every other
# manifest type which only gives a flat "these names are declared" list
# with no actual edges between them.
#
# Efficiency: same approach as the project-only scan — packages and
# existing orphan locations are each loaded into memory with a single
# query, matching is O(1) dict lookups, and there is exactly one
# db.commit() at the very end regardless of how much was found.

FULL_SCAN_DEFAULT_MAX_DEPTH = 8


@dataclass
class OrphanMapping:
    package_id: int
    package_name: str
    file_path: str
    directory: str
    manifest_type: str


@dataclass
class FullScanResult:
    roots_scanned: list[str] = field(default_factory=list)
    manifests_found: int = 0
    project_links_new: list[ProjectMatch] = field(default_factory=list)
    project_links_already: int = 0
    orphan_mappings_new: list[OrphanMapping] = field(default_factory=list)
    orphan_mappings_already: int = 0
    dependency_graph_updates: int = 0
    unmatched_deps: dict[str, list[str]] = field(default_factory=dict)   # dir -> dep names


def _project_for_directory(directory: Path, projects: list[Project]) -> Optional[Project]:
    """Return the registered project that owns `directory`, if any —
    i.e. the project's directory equals it or is an ancestor of it."""
    directory = directory.resolve()
    for proj in projects:
        if not proj.directory:
            continue
        proj_dir = Path(proj.directory).expanduser().resolve()
        if directory == proj_dir or proj_dir in directory.parents:
            return proj
    return None


def _find_cargo_lockfiles(root: Path, max_depth: int) -> list[Path]:
    """Dedicated walk for Cargo.lock specifically — used only for
    dependency-graph enrichment, kept separate from find_all_manifests
    since Cargo.lock isn't a 'these are my direct deps' declaration file
    the way the other recognized manifests are."""
    found: list[Path] = []

    def _walk(d: Path, depth: int):
        if depth > max_depth:
            return
        try:
            entries = list(d.iterdir())
        except (PermissionError, OSError):
            return
        for child in entries:
            if child.is_file():
                if child.name == "Cargo.lock":
                    found.append(child)
            elif child.is_dir():
                if child.name in SKIP_DIRS or child.name.startswith("."):
                    continue
                _walk(child, depth + 1)

    _walk(root, 0)
    return found


def _merge_cargo_lock_graph(lock_path: Path, pkg_by_name: dict[str, list[Package]]) -> int:
    """
    Update depends_on for tracked cargo packages using this lockfile's
    real resolved dependency graph. Merges with (never overwrites)
    whatever depends_on data the cargo collector already gathered from
    live system state. Returns how many packages were actually updated.
    """
    from .collectors.cargo import _parse_cargo_lock

    entries = _parse_cargo_lock(lock_path)
    updated = 0

    for entry in entries:
        norm = _normalize_name(entry.name)
        candidates = pkg_by_name.get(norm)
        if not candidates:
            continue
        match = next((c for c in candidates if c.source == InstallSource.cargo), None)
        if not match:
            continue

        new_dep_names = sorted({
            dep.split()[0] for dep in entry.dependencies if dep.strip()
        })
        if not new_dep_names:
            continue

        existing = set(json.loads(match.depends_on or "[]"))
        merged = existing | set(new_dep_names)
        if merged != existing:
            match.depends_on = json.dumps(sorted(merged))
            updated += 1

    return updated


def full_disk_scan(
    db: Session,
    roots: Optional[list[str]] = None,
    max_depth: int = FULL_SCAN_DEFAULT_MAX_DEPTH,
) -> FullScanResult:
    if roots is None:
        roots = [str(Path.home())]

    projects = (
        db.query(Project)
        .filter(Project.is_archived == False)
        .filter(Project.directory.isnot(None))
        .filter(Project.directory != "")
        .all()
    )

    all_packages = db.query(Package).all()
    pkg_by_name: dict[str, list[Package]] = {}
    for pkg in all_packages:
        pkg_by_name.setdefault(_normalize_name(pkg.name), []).append(pkg)

    result = FullScanResult()

    already_linked: dict[int, set[int]] = {
        proj.id: {p.id for p in proj.packages} for proj in projects
    }
    existing_locations: set[tuple[int, str]] = {
        (loc.package_id, loc.file_path)
        for loc in db.query(PackageLocation).all()
    }
    unmatched_sets: dict[str, set[str]] = {}

    for root_str in roots:
        root = Path(root_str).expanduser().resolve()
        if not root.exists():
            continue
        result.roots_scanned.append(str(root))

        manifests = find_all_manifests(root, max_depth=max_depth)
        result.manifests_found += len(manifests)

        for manifest_path in manifests:
            mtype = MANIFEST_HANDLERS[manifest_path.name]
            allowed_sources = MANIFEST_SOURCE_MAP.get(mtype, set())
            directory = manifest_path.parent
            dir_key = str(directory)

            try:
                dep_names = _extract_deps(manifest_path, mtype)
            except Exception:
                continue

            owning_project = _project_for_directory(directory, projects)

            for dep in dep_names:
                norm = _normalize_name(dep)
                candidates = pkg_by_name.get(norm)
                if not candidates:
                    unmatched_sets.setdefault(dir_key, set()).add(dep)
                    continue

                match = next(
                    (c for c in candidates if c.source in allowed_sources),
                    candidates[0],
                )

                if owning_project:
                    linked_ids = already_linked.setdefault(owning_project.id, set())
                    if match.id in linked_ids:
                        result.project_links_already += 1
                        continue
                    owning_project.packages.append(match)
                    match.in_inbox = False
                    linked_ids.add(match.id)
                    result.project_links_new.append(ProjectMatch(
                        project_id    = owning_project.id,
                        project_name  = owning_project.name,
                        package_id    = match.id,
                        package_name  = match.name,
                        manifest_type = mtype,
                    ))
                else:
                    key = (match.id, str(manifest_path))
                    if key in existing_locations:
                        result.orphan_mappings_already += 1
                        continue
                    db.add(PackageLocation(
                        package_id    = match.id,
                        file_path     = str(manifest_path),
                        directory     = dir_key,
                        manifest_type = mtype,
                    ))
                    existing_locations.add(key)
                    result.orphan_mappings_new.append(OrphanMapping(
                        package_id    = match.id,
                        package_name  = match.name,
                        file_path     = str(manifest_path),
                        directory     = dir_key,
                        manifest_type = mtype,
                    ))

        # Separate pass: Cargo.lock files anywhere under this root, for
        # real dependency-graph enrichment.
        for lock_path in _find_cargo_lockfiles(root, max_depth):
            try:
                result.dependency_graph_updates += _merge_cargo_lock_graph(lock_path, pkg_by_name)
            except Exception:
                continue

    result.unmatched_deps = {k: sorted(v) for k, v in unmatched_sets.items()}

    db.commit()
    return result


@scan_router.post("/full")
def full_scan(
    roots: Optional[list[str]] = Body(None, embed=True),
    max_depth: int = Body(FULL_SCAN_DEFAULT_MAX_DEPTH, embed=True),
    db: Session = Depends(get_db),
):
    """
    Scan the user's entire home directory (or custom roots) for every
    manifest file anywhere on disk — not just registered projects.
    Packages found in a registered project's directory get linked to
    that project, exactly like /api/scan/bulk. Packages found elsewhere
    get recorded as "orphan" file locations instead of being silently
    ignored, and any Cargo.lock found contributes real dependency-graph
    data. Safe to call repeatedly — already-linked packages and
    already-recorded locations are skipped, never duplicated.
    """
    result = full_disk_scan(db, roots=roots, max_depth=max_depth)

    # Cap the detailed lists in the response for a whole-disk scan — the
    # counts are always accurate, the itemised lists are capped so the
    # response stays a reasonable size.
    LIST_CAP = 200

    return {
        "roots_scanned"             : result.roots_scanned,
        "manifests_found"           : result.manifests_found,
        "project_links_new_count"   : len(result.project_links_new),
        "project_links_new"        : [
            {
                "project_id"   : m.project_id,
                "project_name" : m.project_name,
                "package_id"   : m.package_id,
                "package_name" : m.package_name,
                "manifest_type": m.manifest_type,
            }
            for m in result.project_links_new[:LIST_CAP]
        ],
        "project_links_already"     : result.project_links_already,
        "orphan_mappings_new_count" : len(result.orphan_mappings_new),
        "orphan_mappings_new"      : [
            {
                "package_id"   : m.package_id,
                "package_name" : m.package_name,
                "file_path"    : m.file_path,
                "directory"    : m.directory,
                "manifest_type": m.manifest_type,
            }
            for m in result.orphan_mappings_new[:LIST_CAP]
        ],
        "orphan_mappings_already"   : result.orphan_mappings_already,
        "dependency_graph_updates"  : result.dependency_graph_updates,
        "unmatched_deps"            : result.unmatched_deps,
    }
