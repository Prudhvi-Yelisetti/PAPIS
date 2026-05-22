import json
import subprocess
from datetime import datetime
from .base import BaseCollector, PackageInfo
from ..models import InstallSource, InstallType


class PacmanCollector(BaseCollector):
    """Collects packages from pacman (includes AUR packages installed via yay/paru)."""

    def is_available(self) -> bool:
        return subprocess.run(["which", "pacman"], capture_output=True).returncode == 0

    def collect(self) -> list[PackageInfo]:
        pkgs = {}

        # All explicitly installed packages
        explicit = self._query_pacman(["-Qe", "--noconfirm"])
        explicit_names = {p.name for p in explicit}
        for p in explicit:
            p.install_type = InstallType.explicit
            pkgs[p.name] = p

        # All installed packages (explicit + deps)
        all_pkgs = self._query_pacman(["-Q"])
        for p in all_pkgs:
            if p.name not in pkgs:
                p.install_type = InstallType.dependency
                pkgs[p.name] = p

        # Enrich with full metadata (size, description, dep tree)
        for name, pkg in pkgs.items():
            info = self._query_info(name)
            if info:
                pkg.size_bytes   = info.get("size")
                pkg.description  = info.get("description")
                pkg.depends_on   = info.get("depends", [])
                pkg.required_by  = info.get("required_by", [])
                pkg.install_date = info.get("install_date")
                # AUR packages have no repo in pacman output
                if info.get("repository") in (None, "None", ""):
                    pkg.source = InstallSource.aur
                else:
                    pkg.source = InstallSource.pacman

        return list(pkgs.values())

    def _query_pacman(self, args: list[str]) -> list[PackageInfo]:
        result = subprocess.run(
            ["pacman"] + args,
            capture_output=True, text=True
        )
        pkgs = []
        for line in result.stdout.splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2:
                pkgs.append(PackageInfo(
                    name=parts[0],
                    version=parts[1],
                    source=InstallSource.pacman,
                ))
        return pkgs

    def _query_info(self, name: str) -> dict | None:
        result = subprocess.run(
            ["pacman", "-Qi", name],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return None

        info: dict = {}
        for line in result.stdout.splitlines():
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            key = key.strip().lower().replace(" ", "_")
            val = val.strip()

            if key == "installed_size":
                # e.g. "4.20 MiB"
                try:
                    num, unit = val.split()
                    mult = {"b":1,"kib":1024,"mib":1024**2,"gib":1024**3}
                    info["size"] = int(float(num) * mult.get(unit.lower(), 1))
                except (ValueError, KeyError):
                    pass
            elif key == "install_date":
                try:
                    info["install_date"] = datetime.strptime(val, "%a %d %b %Y %I:%M:%S %p %Z")
                except ValueError:
                    pass
            elif key == "depends_on":
                info["depends"] = [d.strip() for d in val.split() if d != "None"]
            elif key == "required_by":
                info["required_by"] = [r.strip() for r in val.split() if r != "None"]
            elif key == "description":
                info["description"] = val
            elif key == "repository":
                info["repository"] = val

        return info