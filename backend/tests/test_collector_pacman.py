# backend/tests/test_collector_pacman.py
"""
Tests for PacmanCollector — the highest-volume real data source in
production (1300+ AUR/pacman packages on the reference machine).
"""
import papis.collectors.pacman as pacman_mod
from papis.collectors.pacman import PacmanCollector
from papis.models import InstallSource, InstallType
from tests.conftest import FakeCompletedProcess


QE_OUTPUT = "ripgrep 14.1.0-1\nfastfetch 2.10.1-1\n"
Q_OUTPUT = "ripgrep 14.1.0-1\nfastfetch 2.10.1-1\nglibc 2.39-1\nopenssl 3.2.1-1\n"

PACMAN_QI_TEMPLATE = """Name            : {name}
Version         : {version}
Description     : {description}
Repository      : {repository}
Depends On      : {depends}
Required By     : {required_by}
Installed Size  : {size}
Install Date    : {install_date}
"""


def qi_output(
    name, version="1.0.0", description="A tool",
    repository="extra", depends="None", required_by="None",
    size="4.20 MiB", install_date="Mon 01 Jan 2024 12:00:00 PM UTC",
):
    return PACMAN_QI_TEMPLATE.format(
        name=name, version=version, description=description,
        repository=repository, depends=depends, required_by=required_by,
        size=size, install_date=install_date,
    )


class TestExplicitVsDependency:

    def test_explicit_and_dependency_split_correctly(self, fake_subprocess_run):
        fake_subprocess_run(pacman_mod, {
            ("which", "pacman"): FakeCompletedProcess(returncode=0),
            ("pacman", "-Qe", "--noconfirm"): FakeCompletedProcess(stdout=QE_OUTPUT),
            ("pacman", "-Q"): FakeCompletedProcess(stdout=Q_OUTPUT),
            ("pacman", "-Qi", "ripgrep"): FakeCompletedProcess(stdout=qi_output("ripgrep", "14.1.0-1")),
            ("pacman", "-Qi", "fastfetch"): FakeCompletedProcess(stdout=qi_output("fastfetch", "2.10.1-1")),
            ("pacman", "-Qi", "glibc"): FakeCompletedProcess(stdout=qi_output("glibc", "2.39-1")),
            ("pacman", "-Qi", "openssl"): FakeCompletedProcess(stdout=qi_output("openssl", "3.2.1-1")),
        })

        pkgs = {p.name: p for p in PacmanCollector().collect()}

        assert pkgs["ripgrep"].install_type == InstallType.explicit
        assert pkgs["fastfetch"].install_type == InstallType.explicit
        assert pkgs["glibc"].install_type == InstallType.dependency
        assert pkgs["openssl"].install_type == InstallType.dependency
        assert len(pkgs) == 4


class TestAurVsPacmanDetection:

    def test_package_with_repository_is_pacman_source(self, fake_subprocess_run):
        fake_subprocess_run(pacman_mod, {
            ("which", "pacman"): FakeCompletedProcess(returncode=0),
            ("pacman", "-Qe", "--noconfirm"): FakeCompletedProcess(stdout="ripgrep 14.1.0-1\n"),
            ("pacman", "-Q"): FakeCompletedProcess(stdout="ripgrep 14.1.0-1\n"),
            ("pacman", "-Qi", "ripgrep"): FakeCompletedProcess(
                stdout=qi_output("ripgrep", repository="extra")
            ),
        })
        pkgs = {p.name: p for p in PacmanCollector().collect()}
        assert pkgs["ripgrep"].source == InstallSource.pacman

    def test_package_with_no_repository_is_aur_source(self, fake_subprocess_run):
        """AUR packages show 'Repository : None' or blank in pacman -Qi."""
        fake_subprocess_run(pacman_mod, {
            ("which", "pacman"): FakeCompletedProcess(returncode=0),
            ("pacman", "-Qe", "--noconfirm"): FakeCompletedProcess(stdout="visual-studio-code-bin 1.0-1\n"),
            ("pacman", "-Q"): FakeCompletedProcess(stdout="visual-studio-code-bin 1.0-1\n"),
            ("pacman", "-Qi", "visual-studio-code-bin"): FakeCompletedProcess(
                stdout=qi_output("visual-studio-code-bin", repository="None")
            ),
        })
        pkgs = {p.name: p for p in PacmanCollector().collect()}
        assert pkgs["visual-studio-code-bin"].source == InstallSource.aur


class TestSizeParsing:

    def test_mib_size_converted_to_bytes(self, fake_subprocess_run):
        fake_subprocess_run(pacman_mod, {
            ("which", "pacman"): FakeCompletedProcess(returncode=0),
            ("pacman", "-Qe", "--noconfirm"): FakeCompletedProcess(stdout="foo 1.0-1\n"),
            ("pacman", "-Q"): FakeCompletedProcess(stdout="foo 1.0-1\n"),
            ("pacman", "-Qi", "foo"): FakeCompletedProcess(stdout=qi_output("foo", size="4.20 MiB")),
        })
        pkgs = {p.name: p for p in PacmanCollector().collect()}
        assert pkgs["foo"].size_bytes == int(4.20 * 1024 ** 2)

    def test_gib_size_converted_to_bytes(self, fake_subprocess_run):
        fake_subprocess_run(pacman_mod, {
            ("which", "pacman"): FakeCompletedProcess(returncode=0),
            ("pacman", "-Qe", "--noconfirm"): FakeCompletedProcess(stdout="foo 1.0-1\n"),
            ("pacman", "-Q"): FakeCompletedProcess(stdout="foo 1.0-1\n"),
            ("pacman", "-Qi", "foo"): FakeCompletedProcess(stdout=qi_output("foo", size="1.50 GiB")),
        })
        pkgs = {p.name: p for p in PacmanCollector().collect()}
        assert pkgs["foo"].size_bytes == int(1.50 * 1024 ** 3)

    def test_malformed_size_does_not_crash(self, fake_subprocess_run):
        fake_subprocess_run(pacman_mod, {
            ("which", "pacman"): FakeCompletedProcess(returncode=0),
            ("pacman", "-Qe", "--noconfirm"): FakeCompletedProcess(stdout="foo 1.0-1\n"),
            ("pacman", "-Q"): FakeCompletedProcess(stdout="foo 1.0-1\n"),
            ("pacman", "-Qi", "foo"): FakeCompletedProcess(stdout=qi_output("foo", size="unknown")),
        })
        pkgs = {p.name: p for p in PacmanCollector().collect()}
        assert pkgs["foo"].size_bytes is None


class TestDependsAndRequiredBy:

    def test_depends_on_parsed_into_list(self, fake_subprocess_run):
        fake_subprocess_run(pacman_mod, {
            ("which", "pacman"): FakeCompletedProcess(returncode=0),
            ("pacman", "-Qe", "--noconfirm"): FakeCompletedProcess(stdout="foo 1.0-1\n"),
            ("pacman", "-Q"): FakeCompletedProcess(stdout="foo 1.0-1\n"),
            ("pacman", "-Qi", "foo"): FakeCompletedProcess(
                stdout=qi_output("foo", depends="glibc  gcc-libs  zlib")
            ),
        })
        pkgs = {p.name: p for p in PacmanCollector().collect()}
        assert pkgs["foo"].depends_on == ["glibc", "gcc-libs", "zlib"]

    def test_none_depends_becomes_empty_list(self, fake_subprocess_run):
        fake_subprocess_run(pacman_mod, {
            ("which", "pacman"): FakeCompletedProcess(returncode=0),
            ("pacman", "-Qe", "--noconfirm"): FakeCompletedProcess(stdout="foo 1.0-1\n"),
            ("pacman", "-Q"): FakeCompletedProcess(stdout="foo 1.0-1\n"),
            ("pacman", "-Qi", "foo"): FakeCompletedProcess(stdout=qi_output("foo", depends="None")),
        })
        pkgs = {p.name: p for p in PacmanCollector().collect()}
        assert pkgs["foo"].depends_on == []


class TestInstallDateParsing:

    def test_valid_date_parsed(self, fake_subprocess_run):
        fake_subprocess_run(pacman_mod, {
            ("which", "pacman"): FakeCompletedProcess(returncode=0),
            ("pacman", "-Qe", "--noconfirm"): FakeCompletedProcess(stdout="foo 1.0-1\n"),
            ("pacman", "-Q"): FakeCompletedProcess(stdout="foo 1.0-1\n"),
            ("pacman", "-Qi", "foo"): FakeCompletedProcess(
                stdout=qi_output("foo", install_date="Mon 01 Jan 2024 12:00:00 PM UTC")
            ),
        })
        pkgs = {p.name: p for p in PacmanCollector().collect()}
        assert pkgs["foo"].install_date is not None
        assert pkgs["foo"].install_date.year == 2024

    def test_malformed_date_does_not_crash(self, fake_subprocess_run):
        fake_subprocess_run(pacman_mod, {
            ("which", "pacman"): FakeCompletedProcess(returncode=0),
            ("pacman", "-Qe", "--noconfirm"): FakeCompletedProcess(stdout="foo 1.0-1\n"),
            ("pacman", "-Q"): FakeCompletedProcess(stdout="foo 1.0-1\n"),
            ("pacman", "-Qi", "foo"): FakeCompletedProcess(
                stdout=qi_output("foo", install_date="not a real date")
            ),
        })
        pkgs = {p.name: p for p in PacmanCollector().collect()}
        assert pkgs["foo"].install_date is None


class TestAvailability:

    def test_is_available_true_when_pacman_on_path(self, fake_subprocess_run):
        fake_subprocess_run(pacman_mod, {
            ("which", "pacman"): FakeCompletedProcess(returncode=0),
        })
        assert PacmanCollector().is_available() is True

    def test_is_available_false_when_pacman_missing(self, fake_subprocess_run):
        fake_subprocess_run(pacman_mod, {
            ("which", "pacman"): FakeCompletedProcess(returncode=1),
        })
        assert PacmanCollector().is_available() is False


class TestEmptyOutput:

    def test_no_packages_installed_returns_empty_list(self, fake_subprocess_run):
        fake_subprocess_run(pacman_mod, {
            ("which", "pacman"): FakeCompletedProcess(returncode=0),
            ("pacman", "-Qe", "--noconfirm"): FakeCompletedProcess(stdout=""),
            ("pacman", "-Q"): FakeCompletedProcess(stdout=""),
        })
        assert PacmanCollector().collect() == []
