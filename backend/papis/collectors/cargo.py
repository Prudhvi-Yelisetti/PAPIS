"""
Collects Rust packages managed by Cargo across two scopes:

  1. Global tools  — `cargo install --list`
     These live in ~/.cargo/bin/ and are explicitly installed by the user.

  2. Per-project   — Cargo.toml + Cargo.lock in known project roots.
     We read the lockfile (which is the resolved, pinned dep tree) and
     cross-reference Cargo.toml to split explicit deps from transitive ones.

We do NOT scan ~/.cargo/registry/ — that is a download cache, not a list
of "installed" packages, and would produce thousands of phantom entries.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .base import BaseCollector, PackageInfo
from ..models import InstallSource, InstallType


# ── helpers ───────────────────────────────────────────────────────────────────

def _run(cmd: list[str], cwd: str | None = None) -> str:
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=cwd, timeout=30
        )
        return r.stdout if r.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def _cargo_bin() -> str:
    for c in ("cargo", str(Path.home() / ".cargo" / "bin" / "cargo")):
        if _run([c, "--version"]):
            return c
    return "cargo"


# ── Cargo.lock parser ─────────────────────────────────────────────────────────

@dataclass
class LockEntry:
    name: str
    version: str
    source: Optional[str]    # e.g. "registry+https://github.com/rust-lang/crates.io-index"
    dependencies: list[str]  # list of "name version" strings


def _parse_cargo_lock(lock_path: Path) -> list[LockEntry]:
    """
    Parse Cargo.lock (TOML format) without a full TOML library dependency.
    We use tomllib (stdlib ≥3.11) or tomli as fallback.
    """
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib          # type: ignore
        except ImportError:
            return _parse_cargo_lock_regex(lock_path)

    try:
        with open(lock_path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return []

    entries = []
    for pkg in data.get("package", []):
        deps = []
        for dep in pkg.get("dependencies", []):
            # dep is either "name" or "name version" or "name version (source)"
            parts = dep.split()
            deps.append(f"{parts[0]} {parts[1]}" if len(parts) >= 2 else parts[0])
        entries.append(LockEntry(
            name         = pkg.get("name", ""),
            version      = pkg.get("version", "unknown"),
            source       = pkg.get("source"),
            dependencies = deps,
        ))
    return entries


def _parse_cargo_lock_regex(lock_path: Path) -> list[LockEntry]:
    """Regex fallback for environments without tomllib/tomli."""
    entries: list[LockEntry] = []
    current: dict = {}

    for line in lock_path.read_text(errors="replace").splitlines():
        line = line.strip()
        if line == "[[package]]":
            if current.get("name"):
                entries.append(LockEntry(
                    name         = current.get("name", ""),
                    version      = current.get("version", "unknown"),
                    source       = current.get("source"),
                    dependencies = current.get("dependencies", []),
                ))
            current = {}
        elif m := re.match(r'^name\s*=\s*"(.+)"', line):
            current["name"] = m.group(1)
        elif m := re.match(r'^version\s*=\s*"(.+)"', line):
            current["version"] = m.group(1)
        elif m := re.match(r'^source\s*=\s*"(.+)"', line):
            current["source"] = m.group(1)
        elif m := re.match(r'^dependencies\s*=\s*\[', line):
            current["dependencies"] = []
        elif current.get("dependencies") is not None and line.startswith('"'):
            dep = line.strip('", ')
            current["dependencies"].append(dep)

    if current.get("name"):
        entries.append(LockEntry(
            name         = current.get("name", ""),
            version      = current.get("version", "unknown"),
            source       = current.get("source"),
            dependencies = current.get("dependencies", []),
        ))
    return entries


def _parse_cargo_toml_deps(toml_path: Path) -> set[str]:
    """
    Return the set of *directly declared* dependency names from Cargo.toml
    (lowercased, hyphens normalised to match lockfile convention).
    """
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib          # type: ignore
        except ImportError:
            return set()

    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return set()

    names: set[str] = set()
    for section in ("dependencies", "dev-dependencies", "build-dependencies"):
        for k in data.get(section, {}):
            names.add(k.lower().replace("-", "_"))

    # Also handle workspace deps and target-specific deps
    for target_cfg in data.get("target", {}).values():
        for section in ("dependencies", "dev-dependencies"):
            for k in target_cfg.get(section, {}):
                names.add(k.lower().replace("-", "_"))

    return names


# ── main collector ─────────────────────────────────────────────────────────────

class CargoCollector(BaseCollector):

    PROJECT_ROOTS: list[Path] = [
        Path.home() / "projects",
        Path.home() / "code",
        Path.home() / "dev",
        Path.home() / "work",
    ]
    MAX_DEPTH = 4

    def __init__(self):
        self._cargo = _cargo_bin()

    def is_available(self) -> bool:
        return bool(_run([self._cargo, "--version"]))

    def collect(self) -> list[PackageInfo]:
        pkgs: dict[tuple[str, str], PackageInfo] = {}

        for p in self._collect_global_tools():
            pkgs[(p.name, "global")] = p

        for p in self._collect_project_deps():
            key = (p.name, p.description or "")
            pkgs.setdefault(key, p)

        return list(pkgs.values())

    # ── global tools: `cargo install --list` ─────────────────────────────────

    def _collect_global_tools(self) -> list[PackageInfo]:
        """
        Output format:
            ripgrep v14.1.0:
                rg
            fd-find v9.0.0:
                fd
        """
        raw = _run([self._cargo, "install", "--list"])
        pkgs: list[PackageInfo] = []

        for line in raw.splitlines():
            # Package header lines look like:  "name vX.Y.Z:"
            m = re.match(r"^(\S+)\s+v([\d.]+\S*):$", line.strip())
            if not m:
                continue
            name, version = m.group(1), m.group(2)
            size = self._installed_size(name)
            pkgs.append(PackageInfo(
                name         = name,
                version      = version,
                source       = InstallSource.cargo,
                install_type = InstallType.explicit,
                description  = f"[cargo global tool]",
                size_bytes   = size,
            ))

        return pkgs

    def _installed_size(self, name: str) -> Optional[int]:
        """Approximate size by stat-ing the binary in ~/.cargo/bin/."""
        bin_path = Path.home() / ".cargo" / "bin" / name
        try:
            return bin_path.stat().st_size
        except OSError:
            return None

    # ── per-project deps from Cargo.lock ─────────────────────────────────────

    def _collect_project_deps(self) -> list[PackageInfo]:
        pkgs: list[PackageInfo] = []
        visited: set[str] = set()

        for root in self.PROJECT_ROOTS:
            if not root.exists():
                continue
            for lock_file in self._find_lockfiles(root, depth=0):
                lock_str = str(lock_file)
                if lock_str in visited:
                    continue
                visited.add(lock_str)

                project_dir  = lock_file.parent
                project_name = project_dir.name
                toml_path    = project_dir / "Cargo.toml"

                lock_entries = _parse_cargo_lock(lock_file)
                if not lock_entries:
                    continue

                # Direct deps declared in Cargo.toml
                explicit_names = (
                    _parse_cargo_toml_deps(toml_path)
                    if toml_path.exists()
                    else set()
                )

                # Build a set of all names for transitive detection
                all_lock_names = {e.name.lower().replace("-", "_") for e in lock_entries}

                for entry in lock_entries:
                    norm = entry.name.lower().replace("-", "_")
                    if explicit_names:
                        if norm in explicit_names:
                            itype = InstallType.explicit
                        else:
                            itype = InstallType.dependency
                    else:
                        itype = InstallType.unknown

                    pkgs.append(PackageInfo(
                        name         = entry.name,
                        version      = entry.version,
                        source       = InstallSource.cargo,
                        install_type = itype,
                        description  = f"[cargo project: {project_name}]",
                        depends_on   = [d.split()[0] for d in entry.dependencies],
                    ))

        return pkgs

    def _find_lockfiles(self, directory: Path, depth: int) -> list[Path]:
        results: list[Path] = []
        if depth > self.MAX_DEPTH:
            return results
        try:
            for child in directory.iterdir():
                if not child.is_dir():
                    continue
                lock = child / "Cargo.lock"
                if lock.exists():
                    results.append(lock)
                if child.name not in ("target", ".git", "node_modules", "__pycache__"):
                    results.extend(self._find_lockfiles(child, depth + 1))
        except PermissionError:
            pass
        return results