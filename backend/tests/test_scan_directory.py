# backend/tests/test_scan_directory.py
"""
Tests for the legacy single-directory scan_directory() function (used
by the per-project "scan this one directory" endpoint, distinct from
the newer bulk_scan_all_projects()).
"""
from papis.scanner import scan_directory
from papis.models import InstallSource


class TestScanDirectory:

    def test_matches_declared_deps_against_tracked_packages(
        self, db_session, make_package, manifest_writers, tmp_path
    ):
        fastapi = make_package("fastapi", source=InstallSource.pip)
        make_package("httpx", source=InstallSource.pip)   # not in this manifest

        manifest_writers["requirements"](tmp_path, ["fastapi", "sqlalchemy"])

        result = scan_directory(str(tmp_path), db_session)

        assert result.manifest == "requirements"
        assert fastapi.id in result.matched_package_ids
        assert "sqlalchemy" in result.unmatched_deps

    def test_no_manifest_present_returns_none_manifest(self, db_session, tmp_path):
        result = scan_directory(str(tmp_path), db_session)
        assert result.manifest is None
        assert result.matched_package_ids == []

    def test_nonexistent_directory_handled_gracefully(self, db_session, tmp_path):
        missing = tmp_path / "nope"
        result = scan_directory(str(missing), db_session)
        assert result.manifest is None

    def test_name_matching_is_normalized(
        self, db_session, make_package, manifest_writers, tmp_path
    ):
        """'python-dotenv' in a package DB should match 'python_dotenv'
        declared in a manifest — this is what _normalize_name is for."""
        pkg = make_package("python-dotenv", source=InstallSource.pip)
        manifest_writers["requirements"](tmp_path, ["python_dotenv"])

        result = scan_directory(str(tmp_path), db_session)
        assert pkg.id in result.matched_package_ids
