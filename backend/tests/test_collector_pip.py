# backend/tests/test_collector_pip.py
import papis.collectors.pip as pip_mod
from papis.collectors.pip import PipCollector
from papis.models import InstallSource
from tests.conftest import FakeCompletedProcess


class TestCollect:

    def test_parses_valid_json_output(self, fake_subprocess_run):
        fake_subprocess_run(pip_mod, {
            ("pip", "list", "--format=json"): FakeCompletedProcess(
                stdout='[{"name": "fastapi", "version": "0.100.0"}, '
                       '{"name": "httpx", "version": "0.27.0"}]'
            ),
        })
        pkgs = PipCollector().collect()
        names = {p.name for p in pkgs}
        assert names == {"fastapi", "httpx"}
        assert all(p.source == InstallSource.pip for p in pkgs)

    def test_empty_environment_returns_empty_list(self, fake_subprocess_run):
        fake_subprocess_run(pip_mod, {
            ("pip", "list", "--format=json"): FakeCompletedProcess(stdout="[]"),
        })
        assert PipCollector().collect() == []

    def test_nonzero_exit_returns_empty_list_not_crash(self, fake_subprocess_run):
        fake_subprocess_run(pip_mod, {
            ("pip", "list", "--format=json"): FakeCompletedProcess(returncode=1, stdout=""),
        })
        assert PipCollector().collect() == []

    def test_malformed_json_returns_empty_list_not_crash(self, fake_subprocess_run):
        fake_subprocess_run(pip_mod, {
            ("pip", "list", "--format=json"): FakeCompletedProcess(stdout="{not valid json"),
        })
        assert PipCollector().collect() == []

    def test_missing_version_defaults_to_unknown(self, fake_subprocess_run):
        fake_subprocess_run(pip_mod, {
            ("pip", "list", "--format=json"): FakeCompletedProcess(
                stdout='[{"name": "weird-package"}]'
            ),
        })
        pkgs = PipCollector().collect()
        assert pkgs[0].version == "unknown"


class TestAvailability:

    def test_available_when_pip_version_succeeds(self, fake_subprocess_run):
        fake_subprocess_run(pip_mod, {
            ("pip", "--version"): FakeCompletedProcess(returncode=0, stdout="pip 24.0"),
        })
        assert PipCollector().is_available() is True

    def test_unavailable_when_pip_version_fails(self, fake_subprocess_run):
        fake_subprocess_run(pip_mod, {
            ("pip", "--version"): FakeCompletedProcess(returncode=1),
        })
        assert PipCollector().is_available() is False
