"""
Collects packages installed via uv across all three modes:

  1. uv tool install  → ~/.local/share/uv/tools/<tool>/
  2. uv pip install   → active venv or ~/.venv
  3. uv sync / add    → per-project virtualenvs under <project>/.venv
                        (also reads pyproject.toml to reconstruct intent)

Each mode produces PackageInfo entries with the correct install_type and
a uv_mode field stored in the description prefix so the UI can distinguish them.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from .base import BaseCollector, PackageInfo
from ..models import InstallSource, InstallType


# ── helpers ───────────────────────────────────────────────────────────────────

def _run(cmd: list[str], cwd: str | None = None) -> str:
    """Run a command and return stdout, empty string on failure."""
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, cwd=cwd, timeout=30
        )
        return r.stdout if r.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def _uv_bin() -> str:
    """Return the path to the uv binary."""
    # Prefer the uv on PATH; fall back to the standard install location.
    for candidate in ("uv", str(Path.home() / ".cargo" / "bin" / "uv"),
                      str(Path.home() / ".local" / "bin" / "uv")):
        if _run([candidate, "--version"]):
            return candidate
    return "uv"


def _pip_list_json(uv: str, python: str | None = None, project_dir: str | None = None) -> list[dict]:
    """
    Run `uv pip list --format json` optionally targeting a specific Python
    interpreter or project venv, return parsed list or [].
    """
    cmd = [uv, "pip", "list", "--format", "json"]
    if python:
        cmd += ["--python", python]
    raw = _run(cmd, cwd=project_dir)
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def _pkg_size(pkg_name: str, python: str | None = None) -> Optional[int]:
    """
    Approximate installed size by summing the dist-info directory.
    Falls back to None if not found.
    """
    try:
        import importlib.metadata as im
        dist = im.distribution(pkg_name)
        total = 0
        for f in dist.files or []:
            try:
                total += f.locate().stat().st_size
            except (OSError, AttributeError):
                pass
        return total or None
    except Exception:
        return None


# ── main collector ─────────────────────────────────────────────────────────────

class UvCollector(BaseCollector):
    """
    Collects all uv-managed packages across tool installs, the global venv,
    and every per-project venv found under common project roots.
    """

    # Directories to search for per-project .venv folders.
    PROJECT_ROOTS: list[Path] = [
        Path.home() / "projects",
        Path.home() / "code",
        Path.home() / "dev",
        Path.home() / "work",
        Path.home(),            # direct children only (depth=1)
    ]
    MAX_DEPTH = 3               # how deep to recurse looking for .venv dirs

    def __init__(self):
        self._uv = _uv_bin()

    def is_available(self) -> bool:
        return bool(_run([self._uv, "--version"]))

    # ── public entry point ────────────────────────────────────────────────────

    def collect(self) -> list[PackageInfo]:
        seen: dict[tuple[str, str], PackageInfo] = {}   # (name, venv_path) → info

        for pkg in self._collect_tool_packages():
            seen[(pkg.name, "tools")] = pkg

        for pkg in self._collect_global_venv():
            seen.setdefault((pkg.name, "global"), pkg)

        for pkg in self._collect_project_venvs():
            key = (pkg.name, pkg.description or "")
            seen.setdefault(key, pkg)

        # Collect uv workspace members
        for pkg in self._collect_workspaces():
            key = (pkg.name, pkg.description or "")
            seen.setdefault(key, pkg)

        return list(seen.values())

    # ── mode 1: uv tool install ───────────────────────────────────────────────

    def _collect_tool_packages(self) -> list[PackageInfo]:
        """
        `uv tool list --format json` returns a list like:
          [{"name": "ruff", "version": "0.4.3", "entrypoints": [...]}]
        """
        raw = _run([self._uv, "tool", "list", "--format", "json"])
        if not raw:
            # Older uv versions don't support --format json; fall back to text
            return self._collect_tool_packages_text()

        try:
            tools = json.loads(raw)
        except json.JSONDecodeError:
            return self._collect_tool_packages_text()

        pkgs = []
        for t in tools:
            name = t.get("name", "")
            ver  = t.get("version", "unknown")
            if not name:
                continue

            # Each tool has its own isolated venv; list its packages too
            tool_venv = Path.home() / ".local" / "share" / "uv" / "tools" / name
            tool_python = str(tool_venv / "bin" / "python")
            deps = _pip_list_json(self._uv, python=tool_python)

            # The tool itself is explicit; everything else is a dependency
            pkgs.append(PackageInfo(
                name         = name,
                version      = ver,
                source       = InstallSource.uv,
                install_type = InstallType.explicit,
                description  = f"[uv tool] {name}",
                depends_on   = [d["name"] for d in deps if d["name"].lower() != name.lower()],
            ))

            for dep in deps:
                if dep["name"].lower() == name.lower():
                    continue
                pkgs.append(PackageInfo(
                    name         = dep["name"],
                    version      = dep["version"],
                    source       = InstallSource.uv,
                    install_type = InstallType.dependency,
                    description  = f"[uv tool dep of {name}]",
                ))

        return pkgs

    def _collect_tool_packages_text(self) -> list[PackageInfo]:
        """Fallback text parser for `uv tool list`."""
        raw = _run([self._uv, "tool", "list"])
        pkgs = []
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("-"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                pkgs.append(PackageInfo(
                    name         = parts[0],
                    version      = parts[1].strip("()"),
                    source       = InstallSource.uv,
                    install_type = InstallType.explicit,
                    description  = "[uv tool]",
                ))
        return pkgs

    # ── mode 2: global / active venv ─────────────────────────────────────────

    def _collect_global_venv(self) -> list[PackageInfo]:
        """
        Packages visible to `uv pip list` in the currently active venv
        (or the default interpreter if none is active).
        """
        raw_list = _pip_list_json(self._uv)
        if not raw_list:
            return []

        # Try to find which packages were explicitly requested vs auto-deps.
        # uv doesn't expose this directly, so we use `uv pip show` heuristics.
        explicit = self._infer_explicit_set(raw_list)

        pkgs = []
        for item in raw_list:
            name = item["name"]
            ver  = item["version"]
            show = self._pip_show(name)
            itype = InstallType.explicit if name.lower() in explicit else InstallType.dependency
            pkgs.append(PackageInfo(
                name         = name,
                version      = ver,
                source       = InstallSource.uv,
                install_type = itype,
                description  = f"[uv pip] {show.get('summary', '')}",
                depends_on   = show.get("requires", []),
                required_by  = show.get("required_by", []),
                size_bytes   = _pkg_size(name),
            ))
        return pkgs

    # ── mode 3: per-project venvs ─────────────────────────────────────────────

    def _collect_project_venvs(self) -> list[PackageInfo]:
        """
        Walk common project root directories looking for .venv folders.
        For each one found, list its packages and attempt to read the
        adjacent pyproject.toml to separate explicit from dependency packages.
        """
        pkgs: list[PackageInfo] = []
        visited: set[str] = set()

        for root in self.PROJECT_ROOTS:
            if not root.exists():
                continue
            for venv in self._find_venvs(root, depth=0):
                venv_str = str(venv)
                if venv_str in visited:
                    continue
                visited.add(venv_str)

                project_dir = venv.parent
                python_bin  = venv / "bin" / "python"
                if not python_bin.exists():
                    continue

                raw_list = _pip_list_json(self._uv, python=str(python_bin))
                if not raw_list:
                    continue

                explicit = self._explicit_from_pyproject(project_dir)
                if not explicit:
                    explicit = self._infer_explicit_set(raw_list)

                for item in raw_list:
                    name = item["name"]
                    ver  = item["version"]
                    itype = (
                        InstallType.explicit if name.lower() in explicit
                        else InstallType.dependency
                    )
                    pkgs.append(PackageInfo(
                        name         = name,
                        version      = ver,
                        source       = InstallSource.uv,
                        install_type = itype,
                        description  = f"[uv project venv: {project_dir.name}]",
                        size_bytes   = None,   # skip sizing per-venv for speed
                    ))

        return pkgs

    def _find_venvs(self, directory: Path, depth: int) -> list[Path]:
        """Recursively find .venv directories up to MAX_DEPTH."""
        results: list[Path] = []
        if depth > self.MAX_DEPTH:
            return results
        try:
            for child in directory.iterdir():
                if not child.is_dir():
                    continue
                if child.name == ".venv":
                    results.append(child)
                elif not child.name.startswith(".") and child.name not in ("node_modules", "__pycache__"):
                    results.extend(self._find_venvs(child, depth + 1))
        except PermissionError:
            pass
        return results

    # ── uv workspaces ─────────────────────────────────────────────────────────

    def _collect_workspaces(self) -> list[PackageInfo]:
        """
        Walk PROJECT_ROOTS looking for uv workspace roots (pyproject.toml
        with [tool.uv.workspace]) and collect packages from each member.
        """
        from .uv_workspace import collect_workspace_packages
        pkgs: list[PackageInfo] = []
        visited: set[str] = set()

        for root in self.PROJECT_ROOTS:
            if not root.exists():
                continue
            for pyproject in root.rglob("pyproject.toml"):
                ws_root = str(pyproject.parent)
                if ws_root in visited:
                    continue
                visited.add(ws_root)
                pkgs.extend(collect_workspace_packages(pyproject.parent, self._uv))

        return pkgs

    # ── helpers ───────────────────────────────────────────────────────────────

    def _pip_show(self, name: str) -> dict:
        """Parse `uv pip show <name>` into a dict."""
        raw = _run([self._uv, "pip", "show", name])
        out: dict = {"requires": [], "required_by": []}
        for line in raw.splitlines():
            key, _, val = line.partition(":")
            k = key.strip().lower()
            v = val.strip()
            if k == "requires":
                out["requires"] = [r.strip() for r in v.split(",") if r.strip() and r.strip() != "None"]
            elif k == "required-by":
                out["required_by"] = [r.strip() for r in v.split(",") if r.strip() and r.strip() != "None"]
            elif k == "summary":
                out["summary"] = v
        return out

    def _infer_explicit_set(self, pkg_list: list[dict]) -> set[str]:
        """
        Heuristic: a package is 'explicit' if nothing else in the env
        lists it as a requirement.  This mirrors what `pip list --not-required` does.
        """
        all_names = {p["name"].lower() for p in pkg_list}
        required_by_something: set[str] = set()

        for item in pkg_list:
            show = self._pip_show(item["name"])
            for dep in show.get("requires", []):
                # Strip version specifiers
                dep_name = dep.split("[")[0].strip().lower()
                required_by_something.add(dep_name)

        return all_names - required_by_something

    @staticmethod
    def _explicit_from_pyproject(project_dir: Path) -> set[str]:
        """
        Read pyproject.toml and return the set of declared dependency names
        (lowercased, version specifiers stripped).  Returns empty set if not found.
        """
        pyproject = project_dir / "pyproject.toml"
        if not pyproject.exists():
            return set()

        try:
            # tomllib is stdlib in 3.11+
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib          # type: ignore
            except ImportError:
                return set()

        try:
            with open(pyproject, "rb") as f:
                data = tomllib.load(f)
        except Exception:
            return set()

        deps: set[str] = set()

        # PEP 517/518 — project.dependencies
        for d in data.get("project", {}).get("dependencies", []):
            deps.add(_strip_dep_name(d))

        # Poetry — tool.poetry.dependencies
        for k in data.get("tool", {}).get("poetry", {}).get("dependencies", {}):
            if k.lower() != "python":
                deps.add(k.lower())

        # uv workspace / dev dependencies
        for d in (data.get("tool", {}).get("uv", {}).get("dependencies", []) or []):
            deps.add(_strip_dep_name(d))

        for group in data.get("dependency-groups", {}).values():
            for d in group:
                if isinstance(d, str):
                    deps.add(_strip_dep_name(d))

        return deps


def _strip_dep_name(dep: str) -> str:
    """'requests>=2.28.0 ; python_version>="3.8"' → 'requests'"""
    import re
    return re.split(r"[>=<!;\[\s@]", dep)[0].strip().lower()