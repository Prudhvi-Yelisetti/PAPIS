# backend/tests/test_full_disk_scan.py
"""
Tests for full_disk_scan() — the second scan mode: walks a broad root
(not just registered project directories), links packages to projects
exactly like bulk_scan_all_projects() when a manifest sits inside one,
and records "orphan" PackageLocation mappings for everything else
instead of silently discarding it. Also covers the Cargo.lock-based
dependency-graph enrichment.
"""
import json

from papis.scanner import full_disk_scan, _project_for_directory, _find_cargo_lockfiles
from papis.models import InstallSource, PackageLocation


class TestProjectVsOrphanRouting:

    def test_manifest_inside_registered_project_links_to_it(
        self, db_session, make_package, make_project, manifest_writers, tmp_path
    ):
        fastapi = make_package("fastapi", source=InstallSource.pip)
        proj_dir = tmp_path / "myproject"
        proj_dir.mkdir()
        proj = make_project("myproject", directory=str(proj_dir))
        manifest_writers["requirements"](proj_dir, ["fastapi"])

        result = full_disk_scan(db_session, roots=[str(tmp_path)])

        assert len(result.project_links_new) == 1
        assert result.project_links_new[0].project_id == proj.id
        assert result.orphan_mappings_new == []

    def test_manifest_outside_any_project_becomes_orphan_mapping(
        self, db_session, make_package, manifest_writers, tmp_path
    ):
        fastapi = make_package("fastapi", source=InstallSource.pip)
        random_dir = tmp_path / "some-random-folder"
        random_dir.mkdir()
        manifest_writers["requirements"](random_dir, ["fastapi"])

        result = full_disk_scan(db_session, roots=[str(tmp_path)])

        assert result.project_links_new == []
        assert len(result.orphan_mappings_new) == 1
        assert result.orphan_mappings_new[0].package_id == fastapi.id
        assert result.orphan_mappings_new[0].directory == str(random_dir)

    def test_orphan_mapping_persisted_in_database(
        self, db_session, make_package, manifest_writers, tmp_path
    ):
        fastapi = make_package("fastapi", source=InstallSource.pip)
        random_dir = tmp_path / "orphan-project"
        random_dir.mkdir()
        manifest_writers["requirements"](random_dir, ["fastapi"])

        full_disk_scan(db_session, roots=[str(tmp_path)])

        rows = db_session.query(PackageLocation).filter_by(package_id=fastapi.id).all()
        assert len(rows) == 1
        assert rows[0].manifest_type == "requirements"

    def test_orphan_package_stays_in_inbox_unlike_project_linked_ones(
        self, db_session, make_package, manifest_writers, tmp_path
    ):
        """An orphan mapping is informational only — it must NOT clear
        in_inbox or create any project association, unlike a real link."""
        fastapi = make_package("fastapi", source=InstallSource.pip, in_inbox=True)
        random_dir = tmp_path / "orphan-project"
        random_dir.mkdir()
        manifest_writers["requirements"](random_dir, ["fastapi"])

        full_disk_scan(db_session, roots=[str(tmp_path)])
        db_session.refresh(fastapi)

        assert fastapi.in_inbox is True
        assert fastapi.projects == []

    def test_manifest_in_subdirectory_of_project_still_links(
        self, db_session, make_package, make_project, manifest_writers, tmp_path
    ):
        """A manifest doesn't have to sit exactly at the project's root —
        anywhere underneath it counts (matches this repo's own layout:
        backend/pyproject.toml under the PAPIS project root)."""
        fastapi = make_package("fastapi", source=InstallSource.pip)
        proj_dir = tmp_path / "myproject"
        sub_dir = proj_dir / "backend"
        sub_dir.mkdir(parents=True)
        proj = make_project("myproject", directory=str(proj_dir))
        manifest_writers["requirements"](sub_dir, ["fastapi"])

        result = full_disk_scan(db_session, roots=[str(tmp_path)])

        assert len(result.project_links_new) == 1
        assert result.project_links_new[0].project_id == proj.id


class TestProjectForDirectory:

    def test_exact_match(self, tmp_path, make_project, db_session):
        proj = make_project("p", directory=str(tmp_path))
        found = _project_for_directory(tmp_path, [proj])
        assert found is proj

    def test_subdirectory_match(self, tmp_path, make_project, db_session):
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)
        proj = make_project("p", directory=str(tmp_path))
        found = _project_for_directory(sub, [proj])
        assert found is proj

    def test_unrelated_directory_returns_none(self, tmp_path, make_project, db_session):
        other = tmp_path / "unrelated"
        other.mkdir()
        proj_dir = tmp_path / "myproject"
        proj_dir.mkdir()
        proj = make_project("p", directory=str(proj_dir))
        assert _project_for_directory(other, [proj]) is None

    def test_project_with_no_directory_never_matches(self, tmp_path, make_project, db_session):
        proj = make_project("p", directory=None)
        assert _project_for_directory(tmp_path, [proj]) is None


class TestIdempotency:

    def test_second_scan_produces_no_duplicate_orphan_rows(
        self, db_session, make_package, manifest_writers, tmp_path
    ):
        make_package("fastapi", source=InstallSource.pip)
        random_dir = tmp_path / "orphan-project"
        random_dir.mkdir()
        manifest_writers["requirements"](random_dir, ["fastapi"])

        first = full_disk_scan(db_session, roots=[str(tmp_path)])
        second = full_disk_scan(db_session, roots=[str(tmp_path)])

        assert len(first.orphan_mappings_new) == 1
        assert len(second.orphan_mappings_new) == 0
        assert second.orphan_mappings_already == 1

        all_rows = db_session.query(PackageLocation).all()
        assert len(all_rows) == 1

    def test_second_scan_produces_no_duplicate_project_links(
        self, db_session, make_package, make_project, manifest_writers, tmp_path
    ):
        make_package("fastapi", source=InstallSource.pip)
        proj_dir = tmp_path / "myproject"
        proj_dir.mkdir()
        make_project("myproject", directory=str(proj_dir))
        manifest_writers["requirements"](proj_dir, ["fastapi"])

        full_disk_scan(db_session, roots=[str(tmp_path)])
        second = full_disk_scan(db_session, roots=[str(tmp_path)])

        assert len(second.project_links_new) == 0
        assert second.project_links_already == 1


class TestSameFileMultipleLocationsForOnePackage:

    def test_one_package_can_have_multiple_orphan_locations(
        self, db_session, make_package, manifest_writers, tmp_path
    ):
        """A package genuinely used in two different untracked places on
        disk should get two separate location rows, not be collapsed —
        this is the point of the feature: showing every real location."""
        fastapi = make_package("fastapi", source=InstallSource.pip)
        dir_a = tmp_path / "scratch_a"; dir_a.mkdir()
        dir_b = tmp_path / "scratch_b"; dir_b.mkdir()
        manifest_writers["requirements"](dir_a, ["fastapi"])
        manifest_writers["requirements"](dir_b, ["fastapi"])

        full_disk_scan(db_session, roots=[str(tmp_path)])

        rows = db_session.query(PackageLocation).filter_by(package_id=fastapi.id).all()
        assert len(rows) == 2
        dirs = {r.directory for r in rows}
        assert dirs == {str(dir_a), str(dir_b)}


class TestUnmatchedDeps:

    def test_unmatched_deps_grouped_by_directory(
        self, db_session, manifest_writers, tmp_path
    ):
        d = tmp_path / "somewhere"
        d.mkdir()
        manifest_writers["requirements"](d, ["totally-untracked-package"])

        result = full_disk_scan(db_session, roots=[str(tmp_path)])

        assert "totally-untracked-package" in result.unmatched_deps[str(d)]


class TestFindCargoLockfiles:

    def test_finds_lockfile_anywhere_under_root(self, tmp_path):
        proj = tmp_path / "rustproject"
        proj.mkdir()
        (proj / "Cargo.lock").write_text("version = 3\n")

        found = _find_cargo_lockfiles(tmp_path, max_depth=8)
        assert len(found) == 1

    def test_skips_target_directory(self, tmp_path):
        target = tmp_path / "target"
        target.mkdir()
        (target / "Cargo.lock").write_text("version = 3\n")

        found = _find_cargo_lockfiles(tmp_path, max_depth=8)
        assert found == []


class TestDependencyGraphEnrichment:

    def test_cargo_lock_updates_depends_on_for_matched_package(
        self, db_session, make_package, tmp_path
    ):
        serde = make_package("serde", source=InstallSource.cargo, version="1.0.197")

        lock_dir = tmp_path / "rustproject"
        lock_dir.mkdir()
        (lock_dir / "Cargo.lock").write_text('''
version = 3

[[package]]
name = "serde"
version = "1.0.197"
dependencies = [
 "serde_derive",
]

[[package]]
name = "serde_derive"
version = "1.0.197"
''')

        result = full_disk_scan(db_session, roots=[str(tmp_path)])
        db_session.refresh(serde)

        assert result.dependency_graph_updates >= 1
        deps = json.loads(serde.depends_on or "[]")
        assert "serde_derive" in deps

    def test_existing_depends_on_data_is_merged_not_overwritten(
        self, db_session, make_package, tmp_path
    ):
        """The cargo collector may have already populated depends_on from
        live system state — the lockfile scan must add to it, not
        replace it."""
        serde = make_package("serde", source=InstallSource.cargo)
        serde.depends_on = json.dumps(["some-existing-dep"])
        db_session.commit()

        lock_dir = tmp_path / "rustproject"
        lock_dir.mkdir()
        (lock_dir / "Cargo.lock").write_text('''
version = 3

[[package]]
name = "serde"
version = "1.0.197"
dependencies = [
 "serde_derive",
]
''')

        full_disk_scan(db_session, roots=[str(tmp_path)])
        db_session.refresh(serde)

        deps = set(json.loads(serde.depends_on))
        assert "some-existing-dep" in deps
        assert "serde_derive" in deps

    def test_untracked_cargo_package_in_lockfile_causes_no_error(
        self, db_session, tmp_path
    ):
        """A lockfile mentioning packages we don't track at all shouldn't
        crash the scan — just nothing to update."""
        lock_dir = tmp_path / "rustproject"
        lock_dir.mkdir()
        (lock_dir / "Cargo.lock").write_text('''
version = 3

[[package]]
name = "some-untracked-crate"
version = "1.0.0"
''')
        result = full_disk_scan(db_session, roots=[str(tmp_path)])
        assert result.dependency_graph_updates == 0


class TestRootHandling:

    def test_nonexistent_root_skipped_gracefully(self, db_session, tmp_path):
        missing = tmp_path / "does-not-exist"
        result = full_disk_scan(db_session, roots=[str(missing)])
        assert result.roots_scanned == []
        assert result.manifests_found == 0

    def test_defaults_to_home_directory_when_no_roots_given(
        self, db_session, monkeypatch, tmp_path
    ):
        monkeypatch.setattr("papis.scanner.Path.home", lambda: tmp_path)
        result = full_disk_scan(db_session, roots=None)
        assert result.roots_scanned == [str(tmp_path.resolve())]

    def test_empty_directory_produces_empty_result(self, db_session, tmp_path):
        result = full_disk_scan(db_session, roots=[str(tmp_path)])
        assert result.manifests_found == 0
        assert result.project_links_new == []
        assert result.orphan_mappings_new == []
