from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from ..models import InstallSource, InstallType


@dataclass
class PackageInfo:
    name: str
    version: str
    source: InstallSource
    install_type: InstallType = InstallType.unknown
    install_date: Optional[datetime] = None
    size_bytes: Optional[int] = None
    description: Optional[str] = None
    depends_on: list[str] = field(default_factory=list)
    required_by: list[str] = field(default_factory=list)


class BaseCollector(ABC):
    @abstractmethod
    def collect(self) -> list[PackageInfo]:
        """Return all currently installed packages from this source."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this package manager is present on the system."""