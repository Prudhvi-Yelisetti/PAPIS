import json
import subprocess
from typing import List

import json
import subprocess
from typing import List
from .base import BaseCollector, PackageInfo
from ..models import InstallSource, InstallType

class PipCollector(BaseCollector):
    """Collect installed Python packages using pip.

    Uses ``pip list --format=json`` to obtain name and version.
    """

    def is_available(self) -> bool:
        """Return True if the ``pip`` command is executable."""
        try:
            result = subprocess.run(["pip", "--version"], capture_output=True, text=True)
            return result.returncode == 0
        except Exception:
            return False

    def collect(self) -> List[PackageInfo]:
        """Collect installed packages via pip.

        Returns a list of :class:`PackageInfo` with source set to ``InstallSource.pip``.
        """
        try:
            result = subprocess.run(
                ["pip", "list", "--format=json"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return []
            data = json.loads(result.stdout)
        except Exception:
            return []

        pkgs: List[PackageInfo] = []
        for entry in data:
            name = entry.get("name", "")
            version = entry.get("version", "unknown")
            pkgs.append(
                PackageInfo(
                    name=name,
                    version=version,
                    source=InstallSource.pip,
                    install_type=InstallType.unknown,
                    description="[pip package]",
                )
            )
        return pkgs
