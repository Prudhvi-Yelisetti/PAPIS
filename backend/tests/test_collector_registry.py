# backend/tests/test_collector_registry.py
"""
Tests for collect_all()'s deduplication and error-isolation logic.
Uses fake, lightweight collectors instead of the real ones — this is
about the dedup/error-handling algorithm itself, not any one specific
package manager's parsing.
"""
import papis.collectors.registry as registry_mod
from papis.collectors.registry import collect_all
from papis.collectors.base import BaseCollector, PackageInfo
from papis.models import InstallSource, InstallType


class FakeCollector(BaseCollector):
    def __init__(self, packages, available=True, raises=False):
        self._packages = packages
        self._available = available
        self._raises = raises

    def is_available(self) -> bool:
        return self._available

    def collect(self) -> list[PackageInfo]:
        if self._raises:
            raise RuntimeError("simulated collector failure")
        return self._packages


def pkg(name, source=InstallSource.pip, version="1.0.0"):
    return PackageInfo(name=name, version=version, source=source)


class TestDeduplication:

    def test_same_name_same_source_deduplicated_first_wins(self, monkeypatch):
        first = FakeCollector([pkg("fastapi", version="1.0.0")])
        second = FakeCollector([pkg("fastapi", version="2.0.0")])
        monkeypatch.setattr(registry_mod, "ALL_COLLECTORS", [first, second])

        result = collect_all()
        assert len(result) == 1
        assert result[0].version == "1.0.0"   # first collector's entry wins

    def test_same_name_different_source_both_kept(self, monkeypatch):
        """This is the actual observed real-world case: uv-sourced and
        pip-sourced fastapi both legitimately exist as separate rows."""
        uv_collector = FakeCollector([pkg("fastapi", source=InstallSource.uv)])
        pip_collector = FakeCollector([pkg("fastapi", source=InstallSource.pip)])
        monkeypatch.setattr(registry_mod, "ALL_COLLECTORS", [uv_collector, pip_collector])

        result = collect_all()
        sources = {p.source for p in result}
        assert sources == {InstallSource.uv, InstallSource.pip}
        assert len(result) == 2

    def test_dedup_key_is_case_insensitive_on_name(self, monkeypatch):
        first = FakeCollector([pkg("FastAPI", version="1.0.0")])
        second = FakeCollector([pkg("fastapi", version="2.0.0")])
        monkeypatch.setattr(registry_mod, "ALL_COLLECTORS", [first, second])

        result = collect_all()
        assert len(result) == 1


class TestAvailabilityFiltering:

    def test_unavailable_collector_is_skipped_entirely(self, monkeypatch):
        available = FakeCollector([pkg("real-package")], available=True)
        unavailable = FakeCollector([pkg("should-never-appear")], available=False)
        monkeypatch.setattr(registry_mod, "ALL_COLLECTORS", [available, unavailable])

        result = collect_all()
        names = {p.name for p in result}
        assert names == {"real-package"}


class TestErrorIsolation:

    def test_one_collector_raising_does_not_crash_the_whole_scan(self, monkeypatch):
        """A single misbehaving collector (e.g. a package manager that
        changed its CLI output format) must not take down every other
        collector's results."""
        broken = FakeCollector([], raises=True)
        healthy = FakeCollector([pkg("survives-the-crash")])
        monkeypatch.setattr(registry_mod, "ALL_COLLECTORS", [broken, healthy])

        result = collect_all()
        assert len(result) == 1
        assert result[0].name == "survives-the-crash"

    def test_all_collectors_raising_returns_empty_list_not_crash(self, monkeypatch):
        broken1 = FakeCollector([], raises=True)
        broken2 = FakeCollector([], raises=True)
        monkeypatch.setattr(registry_mod, "ALL_COLLECTORS", [broken1, broken2])

        assert collect_all() == []


class TestEmptyState:

    def test_no_collectors_available_returns_empty_list(self, monkeypatch):
        monkeypatch.setattr(registry_mod, "ALL_COLLECTORS", [
            FakeCollector([pkg("x")], available=False),
        ])
        assert collect_all() == []

    def test_no_collectors_registered_at_all(self, monkeypatch):
        monkeypatch.setattr(registry_mod, "ALL_COLLECTORS", [])
        assert collect_all() == []
