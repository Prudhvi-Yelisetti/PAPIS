# backend/tests/test_collector_uv.py
"""
UvCollector tests. Focused on the pure/file-based helpers
(_strip_dep_name, _explicit_from_pyproject, _find_venvs) plus the
subprocess-mocked pip-show/explicit-inference logic. uv's three
collection modes (tool/pip/add) are exercised at the parsing-logic
level rather than full end-to-end, since _collect_tool_packages etc.
mix several subprocess calls together — the individual pieces below
are what actually determines correctness.
"""
import papis.collectors.uv as uv_mod
from papis.collectors.uv import UvCollector, _strip_dep_name
from tests.conftest import FakeCompletedProcess


class TestStripDepName:

    def test_basic_version_specifier(self):
        assert _strip_dep_name("requests>=2.28.0") == "requests"

    def test_extras_bracket(self):
        assert _strip_dep_name("fastapi[all]>=0.100") == "fastapi"

    def test_environment_marker(self):
        assert _strip_dep_name('requests; python_version>="3.8"') == "requests"

    def test_at_url_reference(self):
        assert _strip_dep_name("mypackage @ git+https://example.com/x") == "mypackage"

    def test_lowercased(self):
        assert _strip_dep_name("Requests") == "requests"

    def test_bare_name_no_specifier(self):
        assert _strip_dep_name("httpx") == "httpx"


class TestExplicitFromPyproject:

    def test_pep517_dependencies_lowercased_hyphens_preserved(self, tmp_path):
        """Unlike cargo.py (which normalizes to underscores for Cargo.lock
        matching), uv.py's comparison in _collect_project_venvs uses
        name.lower() directly against this set — so hyphens must be
        preserved here, not converted, for the comparison to work."""
        p = tmp_path / "pyproject.toml"
        p.write_text('''
[project]
dependencies = ["Fast-API>=0.100", "python-dotenv"]
''')
        names = UvCollector._explicit_from_pyproject(tmp_path)
        assert names == {"fast-api", "python-dotenv"}

    def test_missing_file_returns_empty_set(self, tmp_path):
        # tmp_path itself has no pyproject.toml in it
        assert UvCollector._explicit_from_pyproject(tmp_path) == set()

    def test_malformed_toml_returns_empty_set(self, tmp_path):
        p = tmp_path / "pyproject.toml"
        p.write_text("not [[[ valid toml")
        assert UvCollector._explicit_from_pyproject(tmp_path) == set()

    def test_no_dependencies_key_returns_empty_set(self, tmp_path):
        p = tmp_path / "pyproject.toml"
        p.write_text('[project]\nname = "x"\n')
        assert UvCollector._explicit_from_pyproject(tmp_path) == set()


class TestFindVenvs:

    def test_finds_venv_in_immediate_subdirectory(self, tmp_path):
        proj = tmp_path / "myproject"
        venv = proj / ".venv"
        venv.mkdir(parents=True)

        collector = UvCollector.__new__(UvCollector)   # skip __init__ (avoids subprocess)
        found = collector._find_venvs(tmp_path, depth=0)
        assert venv in found

    def test_skips_node_modules(self, tmp_path):
        nm = tmp_path / "node_modules" / ".venv"
        nm.mkdir(parents=True)

        collector = UvCollector.__new__(UvCollector)
        found = collector._find_venvs(tmp_path, depth=0)
        assert found == []

    def test_no_venv_anywhere_returns_empty_list(self, tmp_path):
        (tmp_path / "somedir").mkdir()
        collector = UvCollector.__new__(UvCollector)
        assert collector._find_venvs(tmp_path, depth=0) == []


class TestPipShow:

    def test_parses_requires_and_required_by(self, fake_subprocess_run):
        collector = UvCollector.__new__(UvCollector)
        collector._uv = "uv"
        fake_subprocess_run(uv_mod, {
            ("uv", "pip", "show", "fastapi"): FakeCompletedProcess(
                stdout="Name: fastapi\n"
                       "Version: 0.100.0\n"
                       "Summary: A web framework\n"
                       "Requires: starlette, pydantic\n"
                       "Required-by: myapp\n"
            ),
        })
        info = collector._pip_show("fastapi")
        assert info["requires"] == ["starlette", "pydantic"]
        assert info["required_by"] == ["myapp"]
        assert info["summary"] == "A web framework"

    def test_none_values_produce_empty_lists(self, fake_subprocess_run):
        collector = UvCollector.__new__(UvCollector)
        collector._uv = "uv"
        fake_subprocess_run(uv_mod, {
            ("uv", "pip", "show", "isolated-pkg"): FakeCompletedProcess(
                stdout="Name: isolated-pkg\nRequires: \nRequired-by: \n"
            ),
        })
        info = collector._pip_show("isolated-pkg")
        assert info["requires"] == []
        assert info["required_by"] == []


class TestInferExplicitSet:

    def test_package_required_by_nothing_is_explicit(self, fake_subprocess_run):
        collector = UvCollector.__new__(UvCollector)
        collector._uv = "uv"
        # fastapi depends on starlette; starlette is required by fastapi
        # so starlette should NOT be explicit, fastapi SHOULD be.
        fake_subprocess_run(uv_mod, {
            ("uv", "pip", "show", "fastapi"): FakeCompletedProcess(
                stdout="Requires: starlette\n"
            ),
            ("uv", "pip", "show", "starlette"): FakeCompletedProcess(
                stdout="Requires: \n"
            ),
        })
        explicit = collector._infer_explicit_set([
            {"name": "fastapi", "version": "0.100.0"},
            {"name": "starlette", "version": "0.30.0"},
        ])
        assert "fastapi" in explicit
        assert "starlette" not in explicit


class TestCollectProjectVenvsEndToEnd:
    """
    Integration test for the whole 'mode 3' chain: find .venv → run uv pip
    list against it → read pyproject.toml → mark explicit vs dependency
    correctly. Verifies the pieces tested individually above actually
    compose correctly together.
    """

    def test_explicit_and_dependency_split_via_real_pyproject(
        self, tmp_path, fake_subprocess_run, monkeypatch
    ):
        proj = tmp_path / "myproject"
        venv = proj / ".venv"
        venv_bin = venv / "bin"
        venv_bin.mkdir(parents=True)
        (venv_bin / "python").write_text("#!/bin/sh\n")   # just needs to exist

        (proj / "pyproject.toml").write_text('''
[project]
dependencies = ["fastapi"]
''')

        collector = UvCollector.__new__(UvCollector)
        collector._uv = "uv"
        monkeypatch.setattr(collector, "PROJECT_ROOTS", [tmp_path])

        python_path = str(venv_bin / "python")
        fake_subprocess_run(uv_mod, {
            ("uv", "pip", "list", "--format", "json", "--python", python_path):
                FakeCompletedProcess(
                    stdout='[{"name": "fastapi", "version": "0.100.0"}, '
                           '{"name": "starlette", "version": "0.30.0"}]'
                ),
        })

        pkgs = {p.name: p for p in collector._collect_project_venvs()}

        assert pkgs["fastapi"].install_type.value == "explicit"
        assert pkgs["starlette"].install_type.value == "dependency"
