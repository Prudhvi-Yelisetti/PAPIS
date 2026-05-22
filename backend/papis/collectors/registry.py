from .pacman   import PacmanCollector
from .pip      import PipCollector
from .npm      import NpmCollector
from .flatpak  import FlatpakCollector

ALL_COLLECTORS: list[BaseCollector] = [
    PacmanCollector(),
    PipCollector(),
    NpmCollector(),
    FlatpakCollector(),
]

def collect_all() -> list[PackageInfo]:
    results = []
    for c in ALL_COLLECTORS:
        if c.is_available():
            try:
                results.extend(c.collect())
            except Exception as e:
                print(f"[papis] collector {c.__class__.__name__} failed: {e}")
    return results