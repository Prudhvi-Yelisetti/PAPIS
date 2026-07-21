# backend/tests/test_collector_flatpak.py
import papis.collectors.flatpak as flatpak_mod
from papis.collectors.flatpak import FlatpakCollector
from papis.models import InstallSource
from tests.conftest import FakeCompletedProcess


class TestCollect:

    def test_parses_tab_separated_columns(self, fake_subprocess_run):
        fake_subprocess_run(flatpak_mod, {
            ("flatpak", "list", "--columns=application,version,size"): FakeCompletedProcess(
                stdout="org.mozilla.firefox\t124.0\t210.5 MB\n"
                       "com.spotify.Client\t1.2.3\t180.0 MB\n"
            ),
        })
        pkgs = {p.name: p for p in FlatpakCollector().collect()}
        assert pkgs["org.mozilla.firefox"].version == "124.0"
        assert pkgs["com.spotify.Client"].version == "1.2.3"
        assert all(p.source == InstallSource.flatpak for p in pkgs.values())

    def test_line_with_only_one_column_is_skipped(self, fake_subprocess_run):
        """A line with no tab at all (fewer than 2 columns) shouldn't
        produce a broken/partial entry."""
        fake_subprocess_run(flatpak_mod, {
            ("flatpak", "list", "--columns=application,version,size"): FakeCompletedProcess(
                stdout="org.mozilla.firefox\t124.0\t210.5 MB\n"
                       "garbage-line-no-tabs\n"
            ),
        })
        pkgs = FlatpakCollector().collect()
        assert len(pkgs) == 1
        assert pkgs[0].name == "org.mozilla.firefox"

    def test_empty_output_returns_empty_list(self, fake_subprocess_run):
        fake_subprocess_run(flatpak_mod, {
            ("flatpak", "list", "--columns=application,version,size"): FakeCompletedProcess(stdout=""),
        })
        assert FlatpakCollector().collect() == []


class TestAvailability:

    def test_available_when_flatpak_on_path(self, fake_subprocess_run):
        fake_subprocess_run(flatpak_mod, {("which", "flatpak"): FakeCompletedProcess(returncode=0)})
        assert FlatpakCollector().is_available() is True

    def test_unavailable_when_flatpak_missing(self, fake_subprocess_run):
        fake_subprocess_run(flatpak_mod, {("which", "flatpak"): FakeCompletedProcess(returncode=1)})
        assert FlatpakCollector().is_available() is False
