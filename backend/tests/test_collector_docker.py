# backend/tests/test_collector_docker.py
import papis.collectors.docker as docker_mod
from papis.collectors.docker import (
    _parse_timestamp, _parse_size, DockerCollector, _detect_runtime,
)
from papis.models import InstallSource, InstallType
from tests.conftest import FakeCompletedProcess


class TestParseTimestamp:

    def test_rfc3339_nano_format(self):
        ts = _parse_timestamp("2024-05-01T12:34:56.789012345Z")
        assert ts is not None
        assert ts.year == 2024
        assert ts.month == 5
        assert ts.day == 1

    def test_nil_returns_none(self):
        assert _parse_timestamp("<nil>") is None

    def test_empty_string_returns_none(self):
        assert _parse_timestamp("") is None

    def test_malformed_timestamp_does_not_crash(self):
        assert _parse_timestamp("not a real timestamp") is None


class TestParseSize:

    def test_integer_passthrough(self):
        assert _parse_size(1024) == 1024

    def test_mb_conversion(self):
        assert _parse_size("142MB") == int(142 * 1000 ** 2)

    def test_gb_conversion(self):
        assert _parse_size("1.2GB") == int(1.2 * 1000 ** 3)

    def test_kib_conversion(self):
        assert _parse_size("512KiB") == int(512 * 1024)

    def test_zero_bytes_returns_none(self):
        assert _parse_size("0B") == None

    def test_na_returns_none(self):
        assert _parse_size("N/A") is None

    def test_empty_string_returns_none(self):
        assert _parse_size("") is None

    def test_plain_integer_string(self):
        assert _parse_size("2048") == 2048

    def test_garbage_string_returns_none(self):
        assert _parse_size("not-a-size-at-all") is None


class TestCollectImages:

    def test_parses_images_with_inspect_enrichment(self, fake_subprocess_run, monkeypatch):
        collector = DockerCollector()
        monkeypatch.setattr(collector, "_runtime", "docker")

        image_line = (
            '{"id":"sha256:abc123","repository":"nginx","tag":"latest",'
            '"digest":"","created":"2024-05-01T12:00:00Z","size":"142MB"}'
        )
        fake_subprocess_run(docker_mod, {
            ("docker", "images", "--no-trunc", "--format", collector._IMAGE_FORMAT):
                FakeCompletedProcess(stdout=image_line + "\n"),
            ("docker", "inspect", "--type", "image", "sha256:abc123"):
                FakeCompletedProcess(stdout='[{"Size": 148897792, "RootFS": {"Layers": ["l1", "l2"]}}]'),
            ("docker", "ps", "-a", "--no-trunc", "--format", collector._CONTAINER_FORMAT):
                FakeCompletedProcess(stdout=""),
        })

        pkgs = collector.collect()
        images = [p for p in pkgs if p.install_type == InstallType.explicit]
        assert len(images) == 1
        assert images[0].name == "nginx:latest"
        assert images[0].size_bytes == 148897792   # from inspect, more accurate than the format string
        assert images[0].source == InstallSource.docker

    def test_duplicate_image_ids_deduplicated(self, fake_subprocess_run, monkeypatch):
        """Same image with multiple tags shouldn't produce duplicate id-based rows."""
        collector = DockerCollector()
        monkeypatch.setattr(collector, "_runtime", "docker")

        lines = (
            '{"id":"sha256:same","repository":"nginx","tag":"latest","digest":"",'
            '"created":"2024-05-01T12:00:00Z","size":"142MB"}\n'
            '{"id":"sha256:same","repository":"nginx","tag":"1.25","digest":"",'
            '"created":"2024-05-01T12:00:00Z","size":"142MB"}\n'
        )
        fake_subprocess_run(docker_mod, {
            ("docker", "images", "--no-trunc", "--format", collector._IMAGE_FORMAT):
                FakeCompletedProcess(stdout=lines),
            ("docker", "inspect", "--type", "image", "sha256:same"):
                FakeCompletedProcess(stdout="[]"),
            ("docker", "ps", "-a", "--no-trunc", "--format", collector._CONTAINER_FORMAT):
                FakeCompletedProcess(stdout=""),
        })

        pkgs = collector.collect()
        assert len(pkgs) == 1   # only the first tag survives, second id is a dup


class TestCollectContainers:

    def test_container_treated_as_dependency_of_its_image(self, fake_subprocess_run, monkeypatch):
        collector = DockerCollector()
        monkeypatch.setattr(collector, "_runtime", "docker")

        container_line = (
            '{"id":"c1","name":"/web","image":"nginx:latest","image_id":"i1",'
            '"status":"Up 2 hours","created":"2024-05-01T12:00:00Z","ports":"80/tcp"}'
        )
        fake_subprocess_run(docker_mod, {
            ("docker", "images", "--no-trunc", "--format", collector._IMAGE_FORMAT):
                FakeCompletedProcess(stdout=""),
            ("docker", "ps", "-a", "--no-trunc", "--format", collector._CONTAINER_FORMAT):
                FakeCompletedProcess(stdout=container_line + "\n"),
        })

        pkgs = collector.collect()
        assert len(pkgs) == 1
        assert pkgs[0].name == "nginx:latest/web"
        assert pkgs[0].install_type == InstallType.dependency
        assert pkgs[0].depends_on == ["nginx:latest"]

    def test_leading_slash_stripped_from_container_name(self, fake_subprocess_run, monkeypatch):
        collector = DockerCollector()
        monkeypatch.setattr(collector, "_runtime", "docker")

        container_line = (
            '{"id":"c1","name":"/my-container","image":"nginx:latest","image_id":"i1",'
            '"status":"Exited (0)","created":"2024-05-01T12:00:00Z","ports":""}'
        )
        fake_subprocess_run(docker_mod, {
            ("docker", "images", "--no-trunc", "--format", collector._IMAGE_FORMAT):
                FakeCompletedProcess(stdout=""),
            ("docker", "ps", "-a", "--no-trunc", "--format", collector._CONTAINER_FORMAT):
                FakeCompletedProcess(stdout=container_line + "\n"),
        })

        pkgs = collector.collect()
        assert "my-container" in pkgs[0].name
        assert "/my-container" not in pkgs[0].name.replace("nginx:latest/", "")


class TestRunFormatLines:
    """Docker's --format produces one JSON object PER LINE, not a JSON
    array — a real, easy-to-get-wrong parsing detail."""

    def test_one_json_object_per_line_not_a_json_array(self, fake_subprocess_run, monkeypatch):
        collector = DockerCollector()
        fake_subprocess_run(docker_mod, {
            ("docker", "images"): FakeCompletedProcess(
                stdout='{"id":"1"}\n{"id":"2"}\n{"id":"3"}\n'
            ),
        })
        rows = collector._run_format_lines(["docker", "images"])
        assert len(rows) == 3

    def test_malformed_line_is_skipped_not_fatal(self, fake_subprocess_run):
        collector = DockerCollector()
        fake_subprocess_run(docker_mod, {
            ("docker", "images"): FakeCompletedProcess(
                stdout='{"id":"1"}\nnot valid json\n{"id":"3"}\n'
            ),
        })
        rows = collector._run_format_lines(["docker", "images"])
        assert len(rows) == 2

    def test_nonzero_exit_returns_empty_list(self, fake_subprocess_run):
        collector = DockerCollector()
        fake_subprocess_run(docker_mod, {
            ("docker", "images"): FakeCompletedProcess(returncode=1),
        })
        assert collector._run_format_lines(["docker", "images"]) == []


class TestRuntimeDetection:

    def test_prefers_docker_over_podman(self, fake_subprocess_run, monkeypatch):
        monkeypatch.delenv("PAPIS_CONTAINER_RUNTIME", raising=False)
        fake_subprocess_run(docker_mod, {
            ("docker", "--version"): FakeCompletedProcess(returncode=0),
            ("podman", "--version"): FakeCompletedProcess(returncode=0),
        })
        assert _detect_runtime() == "docker"

    def test_falls_back_to_podman_when_docker_missing(self, fake_subprocess_run, monkeypatch):
        monkeypatch.delenv("PAPIS_CONTAINER_RUNTIME", raising=False)
        fake_subprocess_run(docker_mod, {
            ("docker", "--version"): FakeCompletedProcess(returncode=1),
            ("podman", "--version"): FakeCompletedProcess(returncode=0),
        })
        assert _detect_runtime() == "podman"

    def test_env_override_forces_specific_runtime(self, fake_subprocess_run, monkeypatch):
        monkeypatch.setenv("PAPIS_CONTAINER_RUNTIME", "podman")
        fake_subprocess_run(docker_mod, {
            ("podman", "--version"): FakeCompletedProcess(returncode=0),
        })
        assert _detect_runtime() == "podman"

    def test_neither_available_returns_none(self, fake_subprocess_run, monkeypatch):
        monkeypatch.delenv("PAPIS_CONTAINER_RUNTIME", raising=False)
        fake_subprocess_run(docker_mod, {
            ("docker", "--version"): FakeCompletedProcess(returncode=1),
            ("podman", "--version"): FakeCompletedProcess(returncode=1),
        })
        assert _detect_runtime() is None
