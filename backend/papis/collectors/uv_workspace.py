"""
uv workspaces allow a single uv.lock and pyproject.toml to manage multiple
sub-packages in a monorepo layout:

  my-project/
  ├── pyproject.toml      (workspace root — lists members)
  ├── uv.lock
  ├── packages/
  │   ├── api/
  │   │   └── pyproject.toml
  │   └── worker/
  │       └── pyproject.toml

This module extends UvCollector to detect workspace roots and collect
packages from every member, associating them with the correct sub-project.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .base import PackageInfo
from ..models import InstallSource, InstallType


def _is_workspace_root(pyproject: Path) -> bool:
    """Return True if this pyproject.toml declares a [tool.uv.workspace] section."""
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib          # type: ignore
        except ImportError:
            return False
    try:
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        return "workspace" in data.get("tool", {}).get("uv", {})
    except Exception:
        return False


def _get_workspace_members(pyproject: Path) -> list[Path]:
    """
    Parse [tool.uv.workspace] members globs and return resolved paths.

    [tool.uv.workspace]
    members = ["packages/*", "apps/*"]
    """
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib          # type: ignore
        except ImportError:
            return []
    try:
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return []

    members_globs = (
        data.get("tool", {}).get("uv", {}).get("workspace", {}).get("members", [])
    )
    root = pyproject.parent
    resolved: list[Path] = []
    for pattern in members_globs:
        for match in root.glob(pattern):
            if (match / "pyproject.toml").exists():
                resolved.append(match)
    return resolved


def collect_workspace_packages(root_dir: Path, uv_bin: str) -> list[PackageInfo]:
    """
    Given a workspace root directory, collect packages for every member.
    Returns PackageInfo entries with description annotated with the member name.
    """
    import subprocess, re

    pyproject = root_dir / "pyproject.toml"
    if not pyproject.exists() or not _is_workspace_root(pyproject):
        return []

    members = _get_workspace_members(pyproject)
    if not members:
        return []

    result: list[PackageInfo] = []

    for member in members:
        member_name = member.name
        member_venv = member / ".venv"
        if not member_venv.exists():
            member_venv = root_dir / ".venv"   # shared root venv

        python_bin = member_venv / "bin" / "python"
        if not python_bin.exists():
            continue

        try:
            raw = subprocess.run(
                [uv_bin, "pip", "list", "--format", "json",
                 "--python", str(python_bin)],
                capture_output=True, text=True, timeout=30
            ).stdout
            packages = json.loads(raw)
        except Exception:
            continue

        # Determine explicitly declared deps from member's pyproject.toml
        member_pyproject = member / "pyproject.toml"
        explicit = _explicit_from_member(member_pyproject)

        for item in packages:
            name  = item["name"]
            ver   = item["version"]
            norm  = name.lower().replace("-", "_")
            itype = (
                InstallType.explicit   if norm in explicit
                else InstallType.dependency
            )
            result.append(PackageInfo(
                name         = name,
                version      = ver,
                source       = InstallSource.uv,
                install_type = itype,
                description  = f"[uv workspace member: {member_name}]",
            ))

    return result


def _explicit_from_member(pyproject: Path) -> set[str]:
    import re
    try:
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

    names: set[str] = set()
    for dep in data.get("project", {}).get("dependencies", []):
        name = re.split(r"[>=<!;\[\s@]", dep)[0].strip().lower().replace("-", "_")
        if name:
            names.add(name)
    return names