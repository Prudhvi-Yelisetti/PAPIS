# backend/tests/test_find_all_manifests.py
"""
Tests for find_all_manifests() — the bounded, skip-list-aware directory
walker. All tests use real directories under tmp_path.
"""
from papis.scanner import find_all_manifests, SKIP_DIRS


class TestFindAllManifests:

    def test_finds_manifest_in_root(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        found = find_all_manifests(tmp_path)
        assert len(found) == 1
        assert found[0].name == "pyproject.toml"

    def test_finds_multiple_manifest_types_in_one_project(self, tmp_path):
        """The realistic case this feature was built for: a repo mixing
        several ecosystems (this very project does exactly this)."""
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        (tmp_path / "frontend").mkdir()
        (tmp_path / "frontend" / "package.json").write_text("{}")
        (tmp_path / "src-tauri").mkdir()
        (tmp_path / "src-tauri" / "Cargo.toml").write_text("[package]\n")

        found = find_all_manifests(tmp_path)
        names = {f.name for f in found}
        assert names == {"pyproject.toml", "package.json", "Cargo.toml"}
        assert len(found) == 3

    def test_finds_nested_manifests(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        (nested / "package.json").write_text("{}")

        found = find_all_manifests(tmp_path)
        assert len(found) == 1

    def test_skips_node_modules(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        nm = tmp_path / "node_modules" / "some-dep"
        nm.mkdir(parents=True)
        (nm / "package.json").write_text("{}")

        found = find_all_manifests(tmp_path)
        # Only the root one, NOT the one inside node_modules.
        # Check relative to tmp_path — pytest's own auto-generated
        # tmp_path directory name can itself contain "node_modules"-like
        # substrings derived from the test function name, so comparing
        # the full absolute path would be a false negative here.
        assert len(found) == 1
        assert "node_modules" not in str(found[0].relative_to(tmp_path))

    def test_skips_all_configured_skip_dirs(self, tmp_path):
        for skip_dir in SKIP_DIRS:
            d = tmp_path / skip_dir
            d.mkdir()
            (d / "pyproject.toml").write_text("[project]\n")

        found = find_all_manifests(tmp_path)
        assert found == []

    def test_skips_hidden_directories(self, tmp_path):
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        (hidden / "pyproject.toml").write_text("[project]\n")

        found = find_all_manifests(tmp_path)
        assert found == []

    def test_respects_max_depth(self, tmp_path):
        deep = tmp_path
        for i in range(10):
            deep = deep / f"level{i}"
            deep.mkdir()
        (deep / "pyproject.toml").write_text("[project]\n")

        found_shallow = find_all_manifests(tmp_path, max_depth=2)
        assert found_shallow == []

        found_deep = find_all_manifests(tmp_path, max_depth=15)
        assert len(found_deep) == 1

    def test_empty_directory_returns_empty_list(self, tmp_path):
        assert find_all_manifests(tmp_path) == []

    def test_nonexistent_directory_returns_empty_list_not_error(self, tmp_path):
        missing = tmp_path / "does-not-exist"
        assert find_all_manifests(missing) == []

    def test_ignores_unrelated_files(self, tmp_path):
        (tmp_path / "README.md").write_text("# hi")
        (tmp_path / "notes.txt").write_text("notes")
        assert find_all_manifests(tmp_path) == []

    def test_permission_error_on_subdir_does_not_crash_whole_walk(self, tmp_path, monkeypatch):
        """One unreadable subdirectory shouldn't abort the entire scan."""
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        blocked = tmp_path / "blocked"
        blocked.mkdir()

        import pathlib
        real_iterdir = pathlib.Path.iterdir

        def fake_iterdir(self):
            if self == blocked:
                raise PermissionError("nope")
            return real_iterdir(self)

        monkeypatch.setattr(pathlib.Path, "iterdir", fake_iterdir)
        found = find_all_manifests(tmp_path)
        assert len(found) == 1
        assert found[0].name == "pyproject.toml"
