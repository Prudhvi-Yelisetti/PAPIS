# backend/tests/test_collector_conda.py
import papis.collectors.conda as conda_mod
from papis.collectors.conda import CondaCollector, _detect_conda
from papis.models import InstallSource
from tests.conftest import FakeCompletedProcess


class TestDetectConda:

    def test_prefers_micromamba_first(self, fake_subprocess_run, monkeypatch):
        monkeypatch.delenv("PAPIS_CONDA_BIN", raising=False)
        fake_subprocess_run(conda_mod, {
            ("micromamba", "--version"): FakeCompletedProcess(stdout="1.5.0"),
        })
        assert _detect_conda() == "micromamba"

    def test_falls_back_to_conda_when_micromamba_and_mamba_missing(
        self, fake_subprocess_run, monkeypatch
    ):
        monkeypatch.delenv("PAPIS_CONDA_BIN", raising=False)
        fake_subprocess_run(conda_mod, {
            ("micromamba", "--version"): FakeCompletedProcess(returncode=1),
            ("mamba", "--version"): FakeCompletedProcess(returncode=1),
            ("conda", "--version"): FakeCompletedProcess(stdout="conda 24.0"),
        })
        assert _detect_conda() == "conda"

    def test_env_override_used_when_it_works(self, fake_subprocess_run, monkeypatch):
        monkeypatch.setenv("PAPIS_CONDA_BIN", "/custom/path/conda")
        fake_subprocess_run(conda_mod, {
            ("/custom/path/conda", "--version"): FakeCompletedProcess(stdout="conda 24.0"),
        })
        assert _detect_conda() == "/custom/path/conda"

    def test_nothing_available_returns_none(self, fake_subprocess_run, monkeypatch):
        monkeypatch.delenv("PAPIS_CONDA_BIN", raising=False)
        fake_subprocess_run(conda_mod, {
            ("micromamba", "--version"): FakeCompletedProcess(returncode=1),
            ("mamba", "--version"): FakeCompletedProcess(returncode=1),
            ("conda", "--version"): FakeCompletedProcess(returncode=1),
        })
        assert _detect_conda() is None


class TestListEnvironments:

    def test_parses_env_list_json(self, fake_subprocess_run):
        collector = CondaCollector()
        collector._bin = "conda"
        fake_subprocess_run(conda_mod, {
            ("conda", "env", "list", "--json"): FakeCompletedProcess(
                stdout='{"envs": ["/home/u/miniconda3", "/home/u/miniconda3/envs/ml"]}'
            ),
        })
        envs = collector._list_environments()
        names = {name for name, _ in envs}
        assert "base" in names
        assert "ml" in names

    def test_skips_pkgs_cache_directory(self, fake_subprocess_run):
        collector = CondaCollector()
        collector._bin = "conda"
        fake_subprocess_run(conda_mod, {
            ("conda", "env", "list", "--json"): FakeCompletedProcess(
                stdout='{"envs": ["/home/u/miniconda3", "/home/u/miniconda3/pkgs/somepkg"]}'
            ),
        })
        envs = collector._list_environments()
        assert len(envs) == 1   # only base, pkgs/ is excluded

    def test_malformed_json_returns_empty_list(self, fake_subprocess_run):
        collector = CondaCollector()
        collector._bin = "conda"
        fake_subprocess_run(conda_mod, {
            ("conda", "env", "list", "--json"): FakeCompletedProcess(stdout="not json"),
        })
        assert collector._list_environments() == []


class TestListEnvPackages:

    def test_pypi_channel_packages_tagged_as_pip_source(self, fake_subprocess_run):
        """Packages installed via pip inside a conda env should be
        cross-tracked as source=pip, not source=conda."""
        collector = CondaCollector()
        collector._bin = "conda"
        fake_subprocess_run(conda_mod, {
            ("conda", "list", "--json", "-n", "ml"): FakeCompletedProcess(
                stdout='[{"name": "numpy", "version": "1.26.0", "channel": "conda-forge"},'
                       ' {"name": "some-pip-tool", "version": "2.0.0", "channel": "pypi"}]'
            ),
        })
        pkgs = {p.name: p for p in collector._list_env_packages("ml", "/envs/ml")}
        assert pkgs["numpy"].source == InstallSource.conda
        assert pkgs["some-pip-tool"].source == InstallSource.pip

    def test_base_env_uses_no_dash_n_flag(self, fake_subprocess_run):
        collector = CondaCollector()
        collector._bin = "conda"
        fake_subprocess_run(conda_mod, {
            ("conda", "list", "--json"): FakeCompletedProcess(
                stdout='[{"name": "python", "version": "3.12.0", "channel": "conda-forge"}]'
            ),
        })
        pkgs = collector._list_env_packages("base", "/envs/base")
        assert len(pkgs) == 1
        assert pkgs[0].name == "python"

    def test_malformed_json_returns_empty_list(self, fake_subprocess_run):
        collector = CondaCollector()
        collector._bin = "conda"
        fake_subprocess_run(conda_mod, {
            ("conda", "list", "--json", "-n", "ml"): FakeCompletedProcess(stdout="garbage"),
        })
        assert collector._list_env_packages("ml", "/envs/ml") == []


class TestPkgSize:

    def test_no_conda_meta_directory_returns_none(self, tmp_path):
        collector = CondaCollector()
        assert collector._pkg_size(str(tmp_path), "numpy") is None

    def test_sums_file_sizes_from_metadata_record(self, tmp_path):
        collector = CondaCollector()
        meta_dir = tmp_path / "conda-meta"
        meta_dir.mkdir()

        f1 = tmp_path / "lib" / "numpy.so"
        f1.parent.mkdir(parents=True)
        f1.write_bytes(b"x" * 100)

        import json as json_mod
        (meta_dir / "numpy-1.26.0-py312.json").write_text(
            json_mod.dumps({"files": ["lib/numpy.so"]})
        )

        assert collector._pkg_size(str(tmp_path), "numpy") == 100


class TestDeduplicationAcrossEnvs:

    def test_same_package_in_multiple_envs_counted_separately(self, fake_subprocess_run):
        """(name, env) is the dedup key — the same package installed in
        two different envs should appear twice, not be collapsed."""
        collector = CondaCollector()
        collector._bin = "conda"
        fake_subprocess_run(conda_mod, {
            ("conda", "env", "list", "--json"): FakeCompletedProcess(
                stdout='{"envs": ["/home/u/miniconda3", "/home/u/miniconda3/envs/a", '
                       '"/home/u/miniconda3/envs/b"]}'
            ),
            ("conda", "list", "--json", "-n", "a"): FakeCompletedProcess(
                stdout='[{"name": "numpy", "version": "1.26.0", "channel": "conda-forge"}]'
            ),
            ("conda", "list", "--json", "-n", "b"): FakeCompletedProcess(
                stdout='[{"name": "numpy", "version": "1.25.0", "channel": "conda-forge"}]'
            ),
            ("conda", "list", "--json"): FakeCompletedProcess(stdout="[]"),
        })
        pkgs = collector.collect()
        numpy_entries = [p for p in pkgs if p.name == "numpy"]
        assert len(numpy_entries) == 2
