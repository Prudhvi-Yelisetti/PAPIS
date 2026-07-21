# backend/tests/test_collector_cargo.py
"""
CargoCollector tests. The lockfile/manifest parsers are pure
filesystem-based functions — tested with real tmp_path files rather
than mocks. Only the `cargo install --list` global-tools path needs
subprocess mocking.
"""
import papis.collectors.cargo as cargo_mod
from papis.collectors.cargo import (
    _parse_cargo_lock, _parse_cargo_lock_regex, _parse_cargo_toml_deps,
    CargoCollector,
)
from papis.models import InstallSource, InstallType
from tests.conftest import FakeCompletedProcess


CARGO_LOCK = '''
version = 3

[[package]]
name = "serde"
version = "1.0.197"
source = "registry+https://github.com/rust-lang/crates.io-index"
dependencies = [
 "serde_derive",
]

[[package]]
name = "serde_derive"
version = "1.0.197"
source = "registry+https://github.com/rust-lang/crates.io-index"

[[package]]
name = "tokio"
version = "1.36.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
'''


class TestParseCargoLock:

    def test_parses_all_packages(self, tmp_path):
        p = tmp_path / "Cargo.lock"
        p.write_text(CARGO_LOCK)
        entries = _parse_cargo_lock(p)
        names = {e.name for e in entries}
        assert names == {"serde", "serde_derive", "tokio"}

    def test_versions_captured(self, tmp_path):
        p = tmp_path / "Cargo.lock"
        p.write_text(CARGO_LOCK)
        entries = {e.name: e for e in _parse_cargo_lock(p)}
        assert entries["tokio"].version == "1.36.0"

    def test_dependencies_captured(self, tmp_path):
        p = tmp_path / "Cargo.lock"
        p.write_text(CARGO_LOCK)
        entries = {e.name: e for e in _parse_cargo_lock(p)}
        assert "serde_derive" in entries["serde"].dependencies[0]

    def test_missing_file_returns_empty_list(self, tmp_path):
        missing = tmp_path / "Cargo.lock"
        assert _parse_cargo_lock(missing) == []

    def test_malformed_toml_does_not_crash(self, tmp_path):
        p = tmp_path / "Cargo.lock"
        p.write_text("this [[[ is not valid toml")
        assert _parse_cargo_lock(p) == []


class TestParseCargoLockRegexFallback:
    """The pure-regex fallback used when neither tomllib nor tomli
    is available — must parse the same real-world file correctly."""

    def test_parses_all_packages(self, tmp_path):
        p = tmp_path / "Cargo.lock"
        p.write_text(CARGO_LOCK)
        entries = _parse_cargo_lock_regex(p)
        names = {e.name for e in entries}
        assert names == {"serde", "serde_derive", "tokio"}

    def test_versions_captured(self, tmp_path):
        p = tmp_path / "Cargo.lock"
        p.write_text(CARGO_LOCK)
        entries = {e.name: e for e in _parse_cargo_lock_regex(p)}
        assert entries["tokio"].version == "1.36.0"


class TestParseCargoTomlDeps:

    def test_dependencies_and_dev_dependencies(self, tmp_path):
        p = tmp_path / "Cargo.toml"
        p.write_text('''
[package]
name = "x"

[dependencies]
serde = "1.0"

[dev-dependencies]
mockito = "1.0"
''')
        deps = _parse_cargo_toml_deps(p)
        assert deps == {"serde", "mockito"}

    def test_hyphens_normalized_to_underscores(self, tmp_path):
        """Cargo.toml commonly uses hyphenated names; Cargo.lock stores
        them the same way, but our matching normalizes to underscore —
        verify that normalization actually happens."""
        p = tmp_path / "Cargo.toml"
        p.write_text('''
[dependencies]
my-crate-name = "1.0"
''')
        deps = _parse_cargo_toml_deps(p)
        assert "my_crate_name" in deps

    def test_missing_file_returns_empty_set(self, tmp_path):
        missing = tmp_path / "Cargo.toml"
        assert _parse_cargo_toml_deps(missing) == set()

    def test_target_specific_dependencies_included(self, tmp_path):
        p = tmp_path / "Cargo.toml"
        p.write_text('''
[target.'cfg(windows)'.dependencies]
winapi = "0.3"
''')
        deps = _parse_cargo_toml_deps(p)
        assert "winapi" in deps


class TestFindLockfiles:

    def test_finds_lockfile_in_immediate_subdirectory(self, tmp_path):
        proj = tmp_path / "myproject"
        proj.mkdir()
        (proj / "Cargo.lock").write_text(CARGO_LOCK)

        found = CargoCollector()._find_lockfiles(tmp_path, depth=0)
        assert len(found) == 1

    def test_skips_target_directory(self, tmp_path):
        proj = tmp_path / "myproject"
        proj.mkdir()
        target = proj / "target"
        target.mkdir()
        (target / "Cargo.lock").write_text(CARGO_LOCK)   # phantom, shouldn't be found

        found = CargoCollector()._find_lockfiles(tmp_path, depth=0)
        assert found == []


class TestExplicitVsTransitive:

    def test_deps_in_cargo_toml_marked_explicit_rest_marked_dependency(
        self, tmp_path, monkeypatch
    ):
        proj = tmp_path / "myproject"
        proj.mkdir()
        (proj / "Cargo.toml").write_text('''
[dependencies]
serde = "1.0"
''')
        (proj / "Cargo.lock").write_text(CARGO_LOCK)

        collector = CargoCollector()
        monkeypatch.setattr(collector, "PROJECT_ROOTS", [tmp_path])

        pkgs = {p.name: p for p in collector._collect_project_deps()}

        assert pkgs["serde"].install_type == InstallType.explicit
        assert pkgs["tokio"].install_type == InstallType.dependency


class TestGlobalTools:

    def test_parses_cargo_install_list_output(self, fake_subprocess_run, monkeypatch):
        collector = CargoCollector()
        fake_subprocess_run(cargo_mod, {
            tuple([collector._cargo, "install", "--list"]): FakeCompletedProcess(
                stdout="ripgrep v14.1.0:\n    rg\nfd-find v9.0.0:\n    fd\n"
            ),
        })
        # Avoid real filesystem stat() calls for size
        monkeypatch.setattr(collector, "_installed_size", lambda name: None)

        pkgs = {p.name: p for p in collector._collect_global_tools()}
        assert pkgs["ripgrep"].version == "14.1.0"
        assert pkgs["fd-find"].version == "9.0.0"
        assert all(p.source == InstallSource.cargo for p in pkgs.values())
        assert all(p.install_type == InstallType.explicit for p in pkgs.values())

    def test_no_tools_installed_returns_empty_list(self, fake_subprocess_run):
        collector = CargoCollector()
        fake_subprocess_run(cargo_mod, {
            tuple([collector._cargo, "install", "--list"]): FakeCompletedProcess(stdout=""),
        })
        assert collector._collect_global_tools() == []
