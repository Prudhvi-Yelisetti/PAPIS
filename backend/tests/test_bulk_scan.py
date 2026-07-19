# backend/tests/test_bulk_scan.py
"""
Tests for bulk_scan_all_projects() — the core feature: scan every
registered project's directory, auto-link matching packages, and leave
everything else untouched. These tests map directly to the original
requirements:

  1. Efficient (single query for packages, single walk per project)
  2. Works correctly when one package is linked to multiple projects
  3. Files outside any registered project's directory are never touched
  4. Safe to re-run (idempotent, no duplicate links)
"""
from papis.scanner import bulk_scan_all_projects
from papis.models import InstallSource


class TestBasicLinking:

    def test_single_project_single_manifest_links_matching_package(
        self, db_session, make_package, make_project, manifest_writers, tmp_path
    ):
        fastapi = make_package("fastapi", source=InstallSource.pip)
        proj = make_project("myapi", directory=str(tmp_path))
        manifest_writers["requirements"](tmp_path, ["fastapi"])

        result = bulk_scan_all_projects(db_session)

        assert result.projects_scanned == 1
        assert result.manifests_found == 1
        assert len(result.new_links) == 1
        assert result.new_links[0].package_id == fastapi.id
        assert result.new_links[0].project_id == proj.id

    def test_linked_package_leaves_the_inbox(
        self, db_session, make_package, make_project, manifest_writers, tmp_path
    ):
        pkg = make_package("fastapi", source=InstallSource.pip, in_inbox=True)
        proj = make_project("myapi", directory=str(tmp_path))
        manifest_writers["requirements"](tmp_path, ["fastapi"])

        bulk_scan_all_projects(db_session)
        db_session.refresh(pkg)

        assert pkg.in_inbox is False
        assert proj in pkg.projects

    def test_unmatched_dep_recorded_without_crashing(
        self, db_session, make_project, manifest_writers, tmp_path
    ):
        make_project("myapi", directory=str(tmp_path))
        manifest_writers["requirements"](tmp_path, ["some-untracked-package"])

        result = bulk_scan_all_projects(db_session)

        assert result.new_links == []
        assert "some-untracked-package" in result.unmatched_deps["myapi"]


class TestMultiProjectLinking:
    """The core requirement: 'work even if a single package is linked to
    multiple projects' — verified with a real shared package across
    multiple real project directories, matching the live verification
    done against this repo's own stud-os/43BGuard-AI/PAPIS projects."""

    def test_one_package_links_to_multiple_projects_in_a_single_pass(
        self, db_session, make_package, make_project, manifest_writers, tmp_path
    ):
        shared = make_package("fastapi", source=InstallSource.pip)

        dir_a = tmp_path / "project_a"; dir_a.mkdir()
        dir_b = tmp_path / "project_b"; dir_b.mkdir()
        dir_c = tmp_path / "project_c"; dir_c.mkdir()
        proj_a = make_project("a", directory=str(dir_a))
        proj_b = make_project("b", directory=str(dir_b))
        proj_c = make_project("c", directory=str(dir_c))

        manifest_writers["requirements"](dir_a, ["fastapi"])
        manifest_writers["requirements"](dir_b, ["fastapi"])
        manifest_writers["requirements"](dir_c, ["fastapi"])

        result = bulk_scan_all_projects(db_session)

        assert result.projects_scanned == 3
        linked_project_ids = {link.project_id for link in result.new_links}
        assert linked_project_ids == {proj_a.id, proj_b.id, proj_c.id}

        db_session.refresh(shared)
        assert {p.id for p in shared.projects} == {proj_a.id, proj_b.id, proj_c.id}

    def test_two_packages_each_shared_by_different_project_subsets(
        self, db_session, make_package, make_project, manifest_writers, tmp_path
    ):
        """fastapi used by A+B, uvicorn used by B+C only — verifies matching
        doesn't leak associations across projects that don't declare a dep."""
        fastapi = make_package("fastapi", source=InstallSource.pip)
        uvicorn = make_package("uvicorn", source=InstallSource.pip)

        dir_a = tmp_path / "a"; dir_a.mkdir()
        dir_b = tmp_path / "b"; dir_b.mkdir()
        dir_c = tmp_path / "c"; dir_c.mkdir()
        proj_a = make_project("a", directory=str(dir_a))
        proj_b = make_project("b", directory=str(dir_b))
        proj_c = make_project("c", directory=str(dir_c))

        manifest_writers["requirements"](dir_a, ["fastapi"])
        manifest_writers["requirements"](dir_b, ["fastapi", "uvicorn"])
        manifest_writers["requirements"](dir_c, ["uvicorn"])

        bulk_scan_all_projects(db_session)
        db_session.refresh(fastapi)
        db_session.refresh(uvicorn)

        assert {p.id for p in fastapi.projects} == {proj_a.id, proj_b.id}
        assert {p.id for p in uvicorn.projects} == {proj_b.id, proj_c.id}


class TestMultipleManifestsPerProject:
    """Real projects (this repo included) mix ecosystems in one directory."""

    def test_pyproject_and_package_json_and_cargo_all_scanned_together(
        self, db_session, make_package, make_project, manifest_writers, tmp_path
    ):
        fastapi = make_package("fastapi", source=InstallSource.pip)
        react = make_package("react", source=InstallSource.npm)
        serde = make_package("serde", source=InstallSource.cargo)

        manifest_writers["pyproject"](tmp_path, ["fastapi"])
        frontend = tmp_path / "frontend"; frontend.mkdir()
        manifest_writers["npm"](frontend, ["react"])
        rust_dir = tmp_path / "src-tauri"; rust_dir.mkdir()
        manifest_writers["cargo"](rust_dir, ["serde"])

        make_project("fullstack", directory=str(tmp_path))
        result = bulk_scan_all_projects(db_session)

        assert result.manifests_found == 3
        linked_ids = {link.package_id for link in result.new_links}
        assert linked_ids == {fastapi.id, react.id, serde.id}


class TestEcosystemAwareMatching:
    """Prevents cross-language name collisions — a Python package and an
    npm package can legitimately share a normalized name; the manifest
    type must disambiguate which one gets linked."""

    def test_pyproject_dep_matches_pip_package_not_same_named_npm_package(
        self, db_session, make_package, make_project, manifest_writers, tmp_path
    ):
        py_core = make_package("core", source=InstallSource.pip)
        make_package("core", source=InstallSource.npm)   # decoy, same name

        manifest_writers["pyproject"](tmp_path, ["core"])
        make_project("proj", directory=str(tmp_path))

        result = bulk_scan_all_projects(db_session)

        assert len(result.new_links) == 1
        assert result.new_links[0].package_id == py_core.id

    def test_npm_dep_matches_npm_package_not_same_named_cargo_package(
        self, db_session, make_package, make_project, manifest_writers, tmp_path
    ):
        make_package("types", source=InstallSource.cargo)   # decoy
        npm_types = make_package("types", source=InstallSource.npm)

        manifest_writers["npm"](tmp_path, ["types"])
        make_project("proj", directory=str(tmp_path))

        result = bulk_scan_all_projects(db_session)

        assert len(result.new_links) == 1
        assert result.new_links[0].package_id == npm_types.id


class TestIdempotency:

    def test_second_run_produces_zero_new_links(
        self, db_session, make_package, make_project, manifest_writers, tmp_path
    ):
        make_package("fastapi", source=InstallSource.pip)
        make_project("myapi", directory=str(tmp_path))
        manifest_writers["requirements"](tmp_path, ["fastapi"])

        first = bulk_scan_all_projects(db_session)
        second = bulk_scan_all_projects(db_session)

        assert len(first.new_links) == 1
        assert len(second.new_links) == 0
        assert second.already_linked_count == 1

    def test_repeated_runs_never_create_duplicate_association_rows(
        self, db_session, make_package, make_project, manifest_writers, tmp_path
    ):
        pkg = make_package("fastapi", source=InstallSource.pip)
        proj = make_project("myapi", directory=str(tmp_path))
        manifest_writers["requirements"](tmp_path, ["fastapi"])

        for _ in range(5):
            bulk_scan_all_projects(db_session)

        db_session.refresh(proj)
        # Exactly one association, no matter how many times we scan
        assert len([p for p in proj.packages if p.id == pkg.id]) == 1

    def test_already_linked_before_first_scan_is_recognized_not_duplicated(
        self, db_session, make_package, make_project, manifest_writers, tmp_path
    ):
        """Mirrors what was found live in this repo's own stud-os project:
        a package already linked from before should be recognized, not
        re-added or double-counted as 'new'."""
        pkg = make_package("fastapi", source=InstallSource.pip)
        proj = make_project("myapi", directory=str(tmp_path))
        proj.packages.append(pkg)
        db_session.commit()

        manifest_writers["requirements"](tmp_path, ["fastapi"])
        result = bulk_scan_all_projects(db_session)

        assert result.new_links == []
        assert result.already_linked_count == 1


class TestScopeIsRegisteredProjectsOnly:
    """The literal requirement: 'if the file isn't in any existing
    project, it should remain as it is'. Verified by construction — the
    scan only ever walks directories of already-registered projects."""

    def test_project_with_no_directory_is_never_scanned(
        self, db_session, make_project
    ):
        make_project("no-dir-project", directory=None)
        result = bulk_scan_all_projects(db_session)
        assert result.projects_scanned == 0

    def test_project_with_empty_string_directory_is_never_scanned(
        self, db_session, make_project
    ):
        make_project("empty-dir-project", directory="")
        result = bulk_scan_all_projects(db_session)
        assert result.projects_scanned == 0

    def test_archived_project_is_excluded(
        self, db_session, make_package, make_project, manifest_writers, tmp_path
    ):
        make_package("fastapi", source=InstallSource.pip)
        make_project("archived", directory=str(tmp_path), is_archived=True)
        manifest_writers["requirements"](tmp_path, ["fastapi"])

        result = bulk_scan_all_projects(db_session)
        assert result.projects_scanned == 0
        assert result.new_links == []

    def test_directory_that_does_not_exist_on_disk_is_skipped_gracefully(
        self, db_session, make_project, tmp_path
    ):
        missing = tmp_path / "does-not-exist"
        make_project("ghost-project", directory=str(missing))

        result = bulk_scan_all_projects(db_session)
        assert result.projects_scanned == 0   # not counted, not an error

    def test_package_unrelated_to_any_project_manifest_stays_in_inbox(
        self, db_session, make_package, make_project, manifest_writers, tmp_path
    ):
        """A package that no registered project's manifest mentions must
        remain exactly as it was — this is the 'remain as it is' case."""
        untouched = make_package("some-random-tool", source=InstallSource.pip, in_inbox=True)
        make_project("myapi", directory=str(tmp_path))
        manifest_writers["requirements"](tmp_path, ["fastapi"])   # doesn't mention it

        bulk_scan_all_projects(db_session)
        db_session.refresh(untouched)

        assert untouched.in_inbox is True
        assert untouched.projects == []

    def test_no_registered_projects_at_all_does_not_crash(self, db_session):
        result = bulk_scan_all_projects(db_session)
        assert result.projects_scanned == 0
        assert result.new_links == []
