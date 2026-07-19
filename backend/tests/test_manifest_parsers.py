# backend/tests/test_manifest_parsers.py
"""
Tests for the per-ecosystem manifest parsers and the _extract_deps
dispatcher. Each parser gets real files written to tmp_path — this
exercises actual TOML/JSON parsing, not a mocked substitute.
"""
from papis.scanner import (
    _parse_pyproject, _parse_requirements, _parse_cargo,
    _parse_package_json, _parse_go_mod, _extract_deps,
)


class TestParsePyproject:

    def test_pep517_dependencies(self, tmp_path):
        p = tmp_path / "pyproject.toml"
        p.write_text('''
[project]
name = "x"
dependencies = ["fastapi>=0.100", "sqlalchemy==2.0.0", "httpx"]
''')
        assert _parse_pyproject(p) == ["fastapi", "sqlalchemy", "httpx"]

    def test_poetry_dependencies_excludes_python(self, tmp_path):
        p = tmp_path / "pyproject.toml"
        p.write_text('''
[tool.poetry.dependencies]
python = "^3.11"
fastapi = "^0.100"
requests = "^2.28"
''')
        deps = _parse_pyproject(p)
        assert "python" not in deps
        assert "fastapi" in deps
        assert "requests" in deps

    def test_uv_dependencies(self, tmp_path):
        p = tmp_path / "pyproject.toml"
        p.write_text('''
[tool.uv]
dependencies = ["ruff>=0.4", "mypy"]
''')
        assert set(_parse_pyproject(p)) == {"ruff", "mypy"}

    def test_deduplicates_preserving_order(self, tmp_path):
        p = tmp_path / "pyproject.toml"
        p.write_text('''
[project]
dependencies = ["fastapi", "httpx"]
[tool.poetry.dependencies]
fastapi = "^1.0"
''')
        deps = _parse_pyproject(p)
        assert deps.count("fastapi") == 1

    def test_empty_pyproject_returns_empty_list(self, tmp_path):
        p = tmp_path / "pyproject.toml"
        p.write_text("[project]\nname = \"x\"\n")
        assert _parse_pyproject(p) == []


class TestParseRequirements:

    def test_basic_requirements(self, tmp_path):
        p = tmp_path / "requirements.txt"
        p.write_text("fastapi>=0.100\nrequests==2.28.0\nhttpx\n")
        assert _parse_requirements(p) == ["fastapi", "requests", "httpx"]

    def test_skips_comments_and_blank_lines(self, tmp_path):
        p = tmp_path / "requirements.txt"
        p.write_text("# a comment\n\nfastapi\n\n# another\nhttpx\n")
        assert _parse_requirements(p) == ["fastapi", "httpx"]

    def test_skips_dash_flags(self, tmp_path):
        p = tmp_path / "requirements.txt"
        p.write_text("-r base.txt\n--index-url https://example.com\nfastapi\n")
        assert _parse_requirements(p) == ["fastapi"]


class TestParseCargo:

    def test_dependencies_and_dev_dependencies(self, tmp_path):
        p = tmp_path / "Cargo.toml"
        p.write_text('''
[package]
name = "x"
version = "0.1.0"

[dependencies]
serde = "1.0"
tokio = { version = "1", features = ["full"] }

[dev-dependencies]
mockito = "1.0"
''')
        deps = set(_parse_cargo(p))
        assert deps == {"serde", "tokio", "mockito"}

    def test_no_dependencies_section(self, tmp_path):
        p = tmp_path / "Cargo.toml"
        p.write_text('[package]\nname = "x"\nversion = "0.1.0"\n')
        assert _parse_cargo(p) == []


class TestParsePackageJson:

    def test_dependencies_and_dev_dependencies(self, tmp_path):
        p = tmp_path / "package.json"
        p.write_text('''{
            "name": "x",
            "dependencies": {"react": "^18.0.0", "vite": "^5.0.0"},
            "devDependencies": {"typescript": "^5.0.0"}
        }''')
        deps = set(_parse_package_json(p))
        assert deps == {"react", "vite", "typescript"}

    def test_no_dependencies_key(self, tmp_path):
        p = tmp_path / "package.json"
        p.write_text('{"name": "x"}')
        assert _parse_package_json(p) == []


class TestParseGoMod:

    def test_extracts_module_names_from_require_lines(self, tmp_path):
        p = tmp_path / "go.mod"
        p.write_text('''module example.com/x

go 1.21

require github.com/gin-gonic/gin v1.9.0
require golang.org/x/text v0.10.0
''')
        deps = _parse_go_mod(p)
        assert "gin" in deps
        assert "text" in deps


class TestExtractDepsDispatch:

    def test_dispatches_to_correct_parser_by_type(self, tmp_path):
        p = tmp_path / "requirements.txt"
        p.write_text("fastapi\n")
        assert _extract_deps(p, "requirements") == ["fastapi"]

    def test_unknown_type_returns_empty_list(self, tmp_path):
        p = tmp_path / "weird.toml"
        p.write_text("garbage")
        assert _extract_deps(p, "totally-unknown-type") == []

    def test_malformed_file_does_not_raise(self, tmp_path):
        """A broken manifest should degrade to an empty list, never crash
        the whole scan — one bad file shouldn't take down a bulk scan."""
        p = tmp_path / "pyproject.toml"
        p.write_text("this is not valid toml [[[")
        assert _extract_deps(p, "pyproject") == []

    def test_malformed_json_does_not_raise(self, tmp_path):
        p = tmp_path / "package.json"
        p.write_text("{not valid json")
        assert _extract_deps(p, "npm") == []
