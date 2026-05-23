from __future__ import annotations

from datetime import datetime
import enum
from typing import Optional

from sqlalchemy import (
    String,
    Boolean,
    DateTime,
    ForeignKey,
    Table,
    Text,
    BigInteger,
    Enum,
    Integer,
    Column,
)

from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    pass


# ──────────────────────────────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────────────────────────────

class InstallSource(str, enum.Enum):
    pacman = "pacman"
    aur = "aur"
    pip = "pip"
    npm = "npm"
    cargo = "cargo"
    flatpak = "flatpak"
    uv = "uv"
    docker = "docker"
    conda = "conda"
    manual = "manual"
    unknown = "unknown"


class InstallType(str, enum.Enum):
    explicit = "explicit"
    dependency = "dependency"
    transitive = "transitive"
    unknown = "unknown"


# ──────────────────────────────────────────────────────────────────────────────
# Association Table
# ──────────────────────────────────────────────────────────────────────────────

package_project = Table(
    "package_project",
    Base.metadata,

    Column(
        "package_id",
        Integer,
        ForeignKey("packages.id", ondelete="CASCADE"),
        primary_key=True,
    ),

    Column(
        "project_id",
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    ),

    Column(
        "assigned_at",
        DateTime,
        default=datetime.utcnow,
    ),

    Column(
        "notes",
        Text,
        nullable=True,
    ),
)


# ──────────────────────────────────────────────────────────────────────────────
# Package
# ──────────────────────────────────────────────────────────────────────────────

class Package(Base):
    __tablename__ = "packages"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String,
        nullable=False,
        index=True,
    )

    version: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    source: Mapped[InstallSource] = mapped_column(
        Enum(InstallSource),
        default=InstallSource.unknown,
    )

    install_type: Mapped[InstallType] = mapped_column(
        Enum(InstallType),
        default=InstallType.unknown,
    )

    install_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
    )

    last_updated: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
    )

    size_bytes: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    depends_on: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    required_by: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    uv_mode: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True,
    )

    is_orphan: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )

    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
    )

    in_inbox: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    # Relationships
    projects: Mapped[list["Project"]] = relationship(
        secondary=package_project,
        back_populates="packages",
    )

    install_events: Mapped[list["InstallEvent"]] = relationship(
        back_populates="package",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Package {self.name}@{self.version} [{self.source}]>"


# ──────────────────────────────────────────────────────────────────────────────
# Project
# ──────────────────────────────────────────────────────────────────────────────

class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String,
        nullable=False,
        unique=True,
        index=True,
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    directory: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True,
    )

    tags: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    is_archived: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    # Relationships
    packages: Mapped[list["Package"]] = relationship(
        secondary=package_project,
        back_populates="projects",
    )

    def __repr__(self) -> str:
        return f"<Project {self.name}>"


# ──────────────────────────────────────────────────────────────────────────────
# Install Event
# ──────────────────────────────────────────────────────────────────────────────

class InstallEvent(Base):
    __tablename__ = "install_events"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    package_id: Mapped[int] = mapped_column(
        ForeignKey("packages.id", ondelete="CASCADE"),
    )

    event_type: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    version_old: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True,
    )

    version_new: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True,
    )

    triggered_by: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True,
    )

    metadata_: Mapped[Optional[str]] = mapped_column(
        "metadata",
        Text,
        nullable=True,
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        index=True,
    )

    # Relationships
    package: Mapped["Package"] = relationship(
        back_populates="install_events",
    )

    def __repr__(self) -> str:
        return f"<InstallEvent {self.event_type}>"


# ──────────────────────────────────────────────────────────────────────────────
# Project Scan
# ──────────────────────────────────────────────────────────────────────────────

class ProjectScan(Base):
    __tablename__ = "project_scans"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
    )

    scanned_path: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    manifest: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True,
    )

    suggestions: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    scanned_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    def __repr__(self) -> str:
        return f"<ProjectScan {self.scanned_path}>"