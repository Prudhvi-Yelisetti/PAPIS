from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime,
    ForeignKey, Table, Text, BigInteger, Enum
)
from sqlalchemy.orm import DeclarativeBase, relationship
import enum


class Base(DeclarativeBase):
    pass


class InstallSource(str, enum.Enum):
    pacman   = "pacman"
    aur      = "aur"
    pip      = "pip"
    npm      = "npm"
    cargo    = "cargo"
    flatpak  = "flatpak"
    uv       = "uv"
    docker   = "docker"
    conda    = "conda"
    manual   = "manual"
    unknown  = "unknown"


class InstallType(str, enum.Enum):
    explicit     = "explicit"       # user directly installed
    dependency   = "dependency"     # direct dep of an explicit pkg
    transitive   = "transitive"     # dep of a dep
    unknown      = "unknown"


# Many-to-many: packages <-> projects
package_project = Table(
    "package_project",
    Base.metadata,
    Column("package_id", Integer, ForeignKey("packages.id", ondelete="CASCADE"), primary_key=True),
    Column("project_id", Integer, ForeignKey("projects.id",  ondelete="CASCADE"), primary_key=True),
    Column("assigned_at", DateTime, default=datetime.utcnow),
    Column("notes", Text, nullable=True),
)


class Package(Base):
    __tablename__ = "packages"

    id              = Column(Integer, primary_key=True, index=True)
    name            = Column(String, nullable=False, index=True)
    version         = Column(String, nullable=False)
    source          = Column(Enum(InstallSource), default=InstallSource.unknown)
    install_type    = Column(Enum(InstallType),   default=InstallType.unknown)
    install_date    = Column(DateTime, nullable=True)
    last_updated    = Column(DateTime, nullable=True)
    size_bytes      = Column(BigInteger, nullable=True)
    description     = Column(Text, nullable=True)
    # JSON-serialised dep list stored as Text; parse in application layer
    depends_on      = Column(Text, nullable=True)   # JSON array of package names
    required_by     = Column(Text, nullable=True)   # JSON array of package names
    is_orphan       = Column(Boolean, default=False)
    last_used_at    = Column(DateTime, nullable=True)
    in_inbox        = Column(Boolean, default=True)  # unassigned until mapped
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    projects = relationship("Project", secondary=package_project, back_populates="packages")
    install_events = relationship("InstallEvent", back_populates="package", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Package {self.name}@{self.version} [{self.source}]>"


class Project(Base):
    __tablename__ = "projects"

    id           = Column(Integer, primary_key=True, index=True)
    name         = Column(String, nullable=False, unique=True, index=True)
    description  = Column(Text, nullable=True)
    directory    = Column(String, nullable=True)   # abs path on disk, if linked
    tags         = Column(Text, nullable=True)     # JSON array
    is_archived  = Column(Boolean, default=False)
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    packages = relationship("Package", secondary=package_project, back_populates="projects")

    def __repr__(self):
        return f"<Project {self.name}>"


class InstallEvent(Base):
    """Append-only audit log — never update, only insert."""
    __tablename__ = "install_events"

    id          = Column(Integer, primary_key=True, index=True)
    package_id  = Column(Integer, ForeignKey("packages.id", ondelete="CASCADE"))
    event_type  = Column(String, nullable=False)   # install | remove | update | duplicate_attempt
    version_old = Column(String, nullable=True)
    version_new = Column(String, nullable=True)
    triggered_by= Column(String, nullable=True)    # e.g. "pacman_hook", "pip_wrapper"
    metadata_   = Column("metadata", Text, nullable=True)  # JSON blob for extra context
    occurred_at = Column(DateTime, default=datetime.utcnow, index=True)

    package = relationship("Package", back_populates="install_events")


class ProjectScan(Base):
    """Results from scanning a directory for manifest files."""
    __tablename__ = "project_scans"

    id           = Column(Integer, primary_key=True, index=True)
    project_id   = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"))
    scanned_path = Column(String, nullable=False)
    manifest     = Column(String, nullable=True)   # e.g. "pyproject.toml"
    suggestions  = Column(Text,   nullable=True)   # JSON: list of package names to auto-assign
    scanned_at   = Column(DateTime, default=datetime.utcnow)