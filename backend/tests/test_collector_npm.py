# backend/tests/test_collector_npm.py
import papis.collectors.npm as npm_mod
from papis.collectors.npm import NpmCollector
from papis.models import InstallSource
from tests.conftest import FakeCompletedProcess


class TestCollect:

    def test_parses_dependencies_object(self, fake_subprocess_run):
        fake_subprocess_run(npm_mod, {
            ("npm", "list", "-g", "--json", "--depth=0"): FakeCompletedProcess(
                stdout='{"dependencies": {'
                       '"typescript": {"version": "5.4.0"}, '
                       '"vite": {"version": "5.2.0"}'
                       '}}'
            ),
        })
        pkgs = {p.name: p for p in NpmCollector().collect()}
        assert pkgs["typescript"].version == "5.4.0"
        assert pkgs["vite"].version == "5.2.0"
        assert all(p.source == InstallSource.npm for p in pkgs.values())

    def test_no_dependencies_key_returns_empty_list(self, fake_subprocess_run):
        fake_subprocess_run(npm_mod, {
            ("npm", "list", "-g", "--json", "--depth=0"): FakeCompletedProcess(stdout="{}"),
        })
        assert NpmCollector().collect() == []

    def test_nonzero_exit_returns_empty_list(self, fake_subprocess_run):
        fake_subprocess_run(npm_mod, {
            ("npm", "list", "-g", "--json", "--depth=0"): FakeCompletedProcess(returncode=1),
        })
        assert NpmCollector().collect() == []

    def test_malformed_json_does_not_crash(self, fake_subprocess_run):
        fake_subprocess_run(npm_mod, {
            ("npm", "list", "-g", "--json", "--depth=0"): FakeCompletedProcess(stdout="not json"),
        })
        assert NpmCollector().collect() == []

    def test_missing_version_defaults_to_unknown(self, fake_subprocess_run):
        fake_subprocess_run(npm_mod, {
            ("npm", "list", "-g", "--json", "--depth=0"): FakeCompletedProcess(
                stdout='{"dependencies": {"weird-pkg": {}}}'
            ),
        })
        pkgs = NpmCollector().collect()
        assert pkgs[0].version == "unknown"


class TestAvailability:

    def test_available_when_npm_on_path(self, fake_subprocess_run):
        fake_subprocess_run(npm_mod, {("which", "npm"): FakeCompletedProcess(returncode=0)})
        assert NpmCollector().is_available() is True

    def test_unavailable_when_npm_missing(self, fake_subprocess_run):
        fake_subprocess_run(npm_mod, {("which", "npm"): FakeCompletedProcess(returncode=1)})
        assert NpmCollector().is_available() is False
