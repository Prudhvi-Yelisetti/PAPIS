class NpmCollector(BaseCollector):
    def is_available(self) -> bool:
        return subprocess.run(["which", "npm"], capture_output=True).returncode == 0

    def collect(self) -> list[PackageInfo]:
        result = subprocess.run(
            ["npm", "list", "-g", "--json", "--depth=0"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return []
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return []

        pkgs = []
        for name, meta in data.get("dependencies", {}).items():
            pkgs.append(PackageInfo(
                name    = name,
                version = meta.get("version", "unknown"),
                source  = InstallSource.npm,
            ))
        return pkgs