"""
Collects Docker/Podman images and containers as trackable "packages".

Tracked entities:
  1. Images   — pulled or locally built images  (source=docker, install_type=explicit)
  2. Containers — running + stopped containers  (source=docker, install_type=dependency)
     A container is treated as a "dependency" of its image.

Podman support:
  podman is a drop-in Docker replacement common on Arch/EndeavourOS.
  We auto-detect whichever runtime is available; if both exist, Docker wins.
  Set PAPIS_CONTAINER_RUNTIME=podman to force podman.

Package naming convention:
  Images    →  "<repository>:<tag>"   e.g. "nginx:latest", "myapp:v1.2"
  Containers→  "<image_name>/<container_name>"  e.g. "nginx:latest/web-server"
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .base import BaseCollector, PackageInfo
from ..models import InstallSource, InstallType


# ── runtime detection ─────────────────────────────────────────────────────────

def _detect_runtime() -> Optional[str]:
    """
    Return the path/name of the available container runtime.
    Priority: env override → docker → podman → None
    """
    override = os.environ.get("PAPIS_CONTAINER_RUNTIME")
    if override:
        return override if _can_run([override, "--version"]) else None

    for runtime in ("docker", "podman"):
        if _can_run([runtime, "--version"]):
            return runtime

    return None


def _can_run(cmd: list[str]) -> bool:
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=5)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _run_json(cmd: list[str]) -> list[dict]:
    """Run a command that outputs a JSON array, return parsed list or []."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return []
        return json.loads(r.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return []


def _parse_timestamp(ts: str) -> Optional[datetime]:
    """
    Parse Docker's various timestamp formats into a datetime.
    Docker uses RFC3339Nano: "2024-05-01T12:34:56.789012345Z"
    """
    if not ts or ts == "<nil>":
        return None
    # Truncate sub-second precision that Python's fromisoformat can't handle
    ts = ts.split(".")[0].rstrip("Z") + "+00:00"
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _parse_size(size_str: str) -> Optional[int]:
    """
    Convert Docker size strings like "142MB", "1.2GB", "512kB" to bytes.
    Docker inspect returns raw bytes as an integer — this handles the
    human-readable format from `docker images` format strings.
    """
    if isinstance(size_str, int):
        return size_str
    if not size_str or size_str in ("0B", "N/A", ""):
        return None
    size_str = size_str.strip()
    multipliers = {
        "b"  : 1,
        "kb" : 1000,
        "kib": 1024,
        "mb" : 1000 ** 2,
        "mib": 1024 ** 2,
        "gb" : 1000 ** 3,
        "gib": 1024 ** 3,
    }
    import re
    m = re.match(r"^([\d.]+)\s*([a-zA-Z]+)$", size_str)
    if m:
        val  = float(m.group(1))
        unit = m.group(2).lower()
        return int(val * multipliers.get(unit, 1))
    try:
        return int(size_str)
    except ValueError:
        return None


# ── main collector ─────────────────────────────────────────────────────────────

class DockerCollector(BaseCollector):

    # Go template that produces valid JSON from `docker images`
    _IMAGE_FORMAT = (
        '{"id":"{{.ID}}",'
        '"repository":"{{.Repository}}",'
        '"tag":"{{.Tag}}",'
        '"digest":"{{.Digest}}",'
        '"created":"{{.CreatedAt}}",'
        '"size":"{{.Size}}"}'
    )

    # Go template for `docker ps -a`
    _CONTAINER_FORMAT = (
        '{"id":"{{.ID}}",'
        '"name":"{{.Names}}",'
        '"image":"{{.Image}}",'
        '"image_id":"{{.ImageID}}",'
        '"status":"{{.Status}}",'
        '"created":"{{.CreatedAt}}",'
        '"ports":"{{.Ports}}"}'
    )

    def __init__(self):
        self._runtime = _detect_runtime()

    def is_available(self) -> bool:
        if not self._runtime:
            return False
        # Also verify the daemon is actually reachable
        return _can_run([self._runtime, "info"])

    def collect(self) -> list[PackageInfo]:
        pkgs: list[PackageInfo] = []
        pkgs.extend(self._collect_images())
        pkgs.extend(self._collect_containers())
        return pkgs

    # ── images ────────────────────────────────────────────────────────────────

    def _collect_images(self) -> list[PackageInfo]:
        """
        Use `docker images --format` with a JSON template so we get
        structured data without needing `docker inspect` per image.
        """
        rows = self._run_format_lines(
            [self._runtime, "images", "--no-trunc",
             "--format", self._IMAGE_FORMAT]
        )

        pkgs: list[PackageInfo] = []
        seen_ids: set[str] = set()

        for row in rows:
            img_id = row.get("id", "")
            repo   = row.get("repository", "<none>")
            tag    = row.get("tag",        "<none>")

            # Skip duplicate IDs (same image, multiple tags — we'll get all tags below)
            if img_id in seen_ids:
                continue

            # <none>:<none> means a dangling/intermediate image — still track it
            name = f"{repo}:{tag}"

            # Enrich with full inspect data for dep tree + more accurate size
            inspect = self._inspect_image(img_id)

            pkgs.append(PackageInfo(
                name         = name,
                version      = tag,
                source       = InstallSource.docker,
                install_type = InstallType.explicit,
                install_date = _parse_timestamp(row.get("created", "")),
                size_bytes   = inspect.get("size") or _parse_size(row.get("size", "")),
                description  = (
                    f"[{self._runtime} image] "
                    f"id={img_id[:12]}  "
                    f"layers={inspect.get('layers', '?')}"
                ),
                depends_on   = inspect.get("parent_layers", []),
            ))
            seen_ids.add(img_id)

        return pkgs

    def _inspect_image(self, image_id: str) -> dict:
        """
        Run `docker inspect` on one image and extract the fields we care about.
        Returns a dict with keys: size, layers, parent_layers.
        """
        data = _run_json([self._runtime, "inspect", "--type", "image", image_id])
        if not data:
            return {}
        item = data[0]
        root_fs = item.get("RootFS", {})
        layers  = root_fs.get("Layers", [])
        return {
            "size"         : item.get("Size"),
            "layers"       : len(layers),
            "parent_layers": layers[:-1] if len(layers) > 1 else [],
        }

    # ── containers ────────────────────────────────────────────────────────────

    def _collect_containers(self) -> list[PackageInfo]:
        """
        Track all containers (running + stopped) as dependency-type packages.
        Name format: "<image>/<container_name>"
        """
        rows = self._run_format_lines(
            [self._runtime, "ps", "-a", "--no-trunc",
             "--format", self._CONTAINER_FORMAT]
        )

        pkgs: list[PackageInfo] = []
        for row in rows:
            image  = row.get("image", "unknown")
            cname  = row.get("name",  "unnamed").lstrip("/")
            status = row.get("status", "")
            cid    = row.get("id",    "")[:12]

            running = status.lower().startswith("up")

            pkgs.append(PackageInfo(
                name         = f"{image}/{cname}",
                version      = cid,                    # short container ID as version
                source       = InstallSource.docker,
                install_type = InstallType.dependency,  # containers depend on images
                install_date = _parse_timestamp(row.get("created", "")),
                size_bytes   = None,                    # container RW layer size needs `du`, skip for now
                description  = (
                    f"[{self._runtime} container] "
                    f"image={image}  "
                    f"status={'running' if running else 'stopped'}  "
                    f"ports={row.get('ports', '') or 'none'}"
                ),
                depends_on   = [image],                 # container depends on its image
            ))

        return pkgs

    # ── helpers ───────────────────────────────────────────────────────────────

    def _run_format_lines(self, cmd: list[str]) -> list[dict]:
        """
        Docker's --format outputs one JSON object per line (not a JSON array).
        Parse each line individually and collect valid dicts.
        """
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                return []
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []

        results = []
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return results