from .pacman   import PacmanCollector
from .pip      import PipCollector
from .uv       import UvCollector          # ← new
from .npm      import NpmCollector
from .flatpak  import FlatpakCollector
from .base     import BaseCollector, PackageInfo

ALL_COLLECTORS: list[BaseCollector] = [
    PacmanCollector(),
    UvCollector(),          # before pip so uv-managed pkgs get source=uv
    PipCollector(),         # pip collector runs after; won't re-insert duplicates
    NpmCollector(),
    FlatpakCollector(),
]


def collect_all() -> list[PackageInfo]:
    """
    Run every available collector and return a deduplicated list of PackageInfo.

    Deduplication key: (name.lower(), source)
    When the same package name appears from both uv and pip collectors,
    the uv entry wins (higher priority in ALL_COLLECTORS order).
    """
    seen: dict[tuple[str, str], PackageInfo] = {}
    errors: list[str] = []

    for collector in ALL_COLLECTORS:
        if not collector.is_available():
            continue
        try:
            for pkg in collector.collect():
                key = (pkg.name.lower(), pkg.source)
                if key not in seen:
                    seen[key] = pkg
        except Exception as exc:
            errors.append(f"{collector.__class__.__name__}: {exc}")

    if errors:
        import logging
        logging.getLogger("papis.collectors").warning(
            "Collector errors: %s", "; ".join(errors)
        )

    return list(seen.values())