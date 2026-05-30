"""
Collects packages from conda/mamba environments.

Tracks:
  1. All named conda environments  (conda env list)
  2. Packages in each environment  (conda list --json -n <env>)
  3. The base environment

Also handles:
  - mamba / micromamba as drop-in replacements
  - conda-forge vs defaults channel distinction
  - pip packages installed inside conda envs (cross-tracked as pip source)
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from .base import BaseCollector, PackageInfo
from ..models import InstallSource, InstallType


def _run(cmd: list[str], env: dict | None = None) -> str:
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
            env={**os.environ, **(env or {})}
        )
        return r.stdout if r.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def _detect_conda() -> Optional[str]:
    """Return the name of the available conda-compatible binary."""
    override = os.environ.get("PAPIS_CONDA_BIN")
    if override:
        return override if _run([override, "--version"]) else None
    for binary in ("micromamba", "mamba", "conda"):
        if _run([binary, "--version"]):
            return binary
    return None


class CondaCollector(BaseCollector):

    def __init__(self):
        self._bin = _detect_conda()

    def is_available(self) -> bool:
        return self._bin is not None

    def collect(self) -> list[PackageInfo]:
        envs   = self._list_environments()
        result = []
        seen: set[tuple[str, str]] = set()   # (name, env_name)

        for env_name, env_path in envs:
            for pkg in self._list_env_packages(env_name, env_path):
                key = (pkg.name.lower(), env_name)
                if key not in seen:
                    seen.add(key)
                    result.append(pkg)

        return result

    # ── environment discovery ─────────────────────────────────────────────────

    def _list_environments(self) -> list[tuple[str, str]]:
        """
        Returns list of (env_name, env_path).
        micromamba uses `env list` differently — handle both formats.
        """
        raw = _run([self._bin, "env", "list", "--json"])
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []

        envs: list[tuple[str, str]] = []
        for path in data.get("envs", []):
            path = Path(path)
            name = path.name if path.name != "miniconda3" else "base"
            # Skip internal cache/pkgs dirs
            if "pkgs" in path.parts:
                continue
            envs.append((name, str(path)))

        return envs

    # ── per-environment package list ──────────────────────────────────────────

    def _list_env_packages(self, env_name: str, env_path: str) -> list[PackageInfo]:
        """
        Run `conda list --json` for a specific environment.
        Packages with build_channel == "pypi" are cross-tracked as pip source.
        """
        if env_name == "base":
            cmd = [self._bin, "list", "--json"]
        else:
            cmd = [self._bin, "list", "--json", "-n", env_name]

        raw = _run(cmd)
        if not raw:
            return []

        try:
            packages = json.loads(raw)
        except json.JSONDecodeError:
            return []

        pkgs: list[PackageInfo] = []
        for item in packages:
            name    = item.get("name", "")
            version = item.get("version", "unknown")
            channel = item.get("channel", "")
            build   = item.get("build_channel", channel)

            # pip packages inside conda envs get pip source
            if build in ("pypi",) or channel in ("pypi",):
                source = InstallSource.pip
            else:
                source = InstallSource.conda

            pkgs.append(PackageInfo(
                name         = name,
                version      = version,
                source       = source,
                install_type = InstallType.unknown,
                description  = (
                    f"[conda env: {env_name}]  "
                    f"channel={channel or 'defaults'}"
                ),
                size_bytes   = self._pkg_size(env_path, name),
            ))

        return pkgs

    def _pkg_size(self, env_path: str, pkg_name: str) -> Optional[int]:
        """Approximate size from the conda-meta JSON for this package."""
        meta_dir = Path(env_path) / "conda-meta"
        if not meta_dir.exists():
            return None
        # conda-meta contains one JSON file per package: name-version-build.json
        for f in meta_dir.glob(f"{pkg_name}-*.json"):
            try:
                data = json.loads(f.read_text())
                # sum of all file sizes listed in the record
                return sum(
                    Path(env_path, fp).stat().st_size
                    for fp in data.get("files", [])
                    if Path(env_path, fp).exists()
                )
            except Exception:
                return None
        return None