# backend/tests/conftest.py
"""
Shared pytest fixtures for the scanner test suite.

Uses a fresh in-memory SQLite database per test (never touches the real
~/.local/share/papis/papis.db) and real temp directories with real
manifest files for the filesystem-walking tests — more faithful to
production behaviour than mocking Path.iterdir()/open().
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from papis.models import Base, Package, Project, InstallSource, InstallType


@pytest.fixture()
def db_session():
    """A fresh, isolated in-memory SQLite session for a single test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def make_package(db_session):
    """Factory fixture: make_package(name, source=..., version=..., in_inbox=...)."""
    def _make(
        name: str,
        source: InstallSource = InstallSource.pip,
        version: str = "1.0.0",
        in_inbox: bool = True,
        install_type: InstallType = InstallType.explicit,
    ) -> Package:
        pkg = Package(
            name=name,
            version=version,
            source=source,
            in_inbox=in_inbox,
            install_type=install_type,
        )
        db_session.add(pkg)
        db_session.commit()
        db_session.refresh(pkg)
        return pkg
    return _make


@pytest.fixture()
def make_project(db_session):
    """Factory fixture: make_project(name, directory=None, is_archived=False)."""
    def _make(name: str, directory: str | None = None, is_archived: bool = False) -> Project:
        proj = Project(name=name, directory=directory, is_archived=is_archived)
        db_session.add(proj)
        db_session.commit()
        db_session.refresh(proj)
        return proj
    return _make


# ── Manifest-writing helpers ────────────────────────────────────────────────
# Real files on a real tmp_path — exercises the actual filesystem walking
# and parsing code paths, not a mocked substitute.

def write_pyproject(dir_: Path, deps: list[str], filename: str = "pyproject.toml") -> Path:
    deps_toml = ", ".join(f'"{d}"' for d in deps)
    content = f'''[project]
name = "testproject"
version = "0.1.0"
dependencies = [{deps_toml}]
'''
    p = dir_ / filename
    p.write_text(content)
    return p


def write_requirements(dir_: Path, deps: list[str], filename: str = "requirements.txt") -> Path:
    content = "\n".join(deps) + "\n"
    p = dir_ / filename
    p.write_text(content)
    return p


def write_cargo_toml(dir_: Path, deps: list[str], filename: str = "Cargo.toml") -> Path:
    deps_section = "\n".join(f'{d} = "1.0"' for d in deps)
    content = f'''[package]
name = "testcrate"
version = "0.1.0"

[dependencies]
{deps_section}
'''
    p = dir_ / filename
    p.write_text(content)
    return p


def write_package_json(dir_: Path, deps: list[str], filename: str = "package.json") -> Path:
    content = json.dumps({
        "name": "testpkg",
        "version": "1.0.0",
        "dependencies": {d: "^1.0.0" for d in deps},
    })
    p = dir_ / filename
    p.write_text(content)
    return p


@pytest.fixture()
def manifest_writers():
    """Bundle of manifest-writing helpers, exposed as a single fixture."""
    return {
        "pyproject": write_pyproject,
        "requirements": write_requirements,
        "cargo": write_cargo_toml,
        "npm": write_package_json,
    }


# ── Subprocess mocking helpers (for collector tests) ────────────────────────

from dataclasses import dataclass as _dataclass


@_dataclass
class FakeCompletedProcess:
    """Minimal stand-in for subprocess.CompletedProcess."""
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


def make_fake_run(responses: dict):
    """
    Build a fake subprocess.run() replacement.

    `responses` maps a tuple of argv (or an argv PREFIX tuple, for commands
    with variable trailing args like `pacman -Qi <name>`) to a
    FakeCompletedProcess. Any command not matched returns a failed
    (returncode=1, empty output) result rather than raising — this mirrors
    how a missing/misbehaving external tool would look in production, and
    keeps tests from silently passing due to an unmatched command falling
    through to nothing.
    """
    def _fake_run(cmd, *args, **kwargs):
        key = tuple(cmd)
        if key in responses:
            return responses[key]
        for prefix, resp in responses.items():
            if key[:len(prefix)] == prefix:
                return resp
        return FakeCompletedProcess(returncode=1)
    return _fake_run


@pytest.fixture()
def fake_subprocess_run(monkeypatch):
    """
    Fixture returning a function you call with a responses dict to patch
    subprocess.run for a specific collector module, e.g.:

        fake_subprocess_run(papis.collectors.pacman, {
            ("pacman", "-Qe", "--noconfirm"): FakeCompletedProcess(stdout="..."),
        })
    """
    def _patch(module, responses: dict):
        monkeypatch.setattr(module.subprocess, "run", make_fake_run(responses))
    return _patch
