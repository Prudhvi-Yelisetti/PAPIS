class FlatpakCollector(BaseCollector):
    def is_available(self) -> bool:
        return subprocess.run(["which", "flatpak"], capture_output=True).returncode == 0

    def collect(self) -> list[PackageInfo]:
        result = subprocess.run(
            ["flatpak", "list", "--columns=application,version,size"],
            capture_output=True, text=True
        )
        pkgs = []
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                pkgs.append(PackageInfo(
                    name    = parts[0],
                    version = parts[1] if len(parts) > 1 else "unknown",
                    source  = InstallSource.flatpak,
                ))
        return pkgs