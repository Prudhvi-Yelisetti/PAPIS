# backend/tests/test_migrations.py
"""
Tests that the Alembic migration chain applies cleanly, end to end,
against a genuinely fresh database — not just via create_all(). This is
a real regression test for a bug found while testing the full-disk scan
feature: migration 001's initial schema already includes uv_mode (folded
in after 002 was written), and 002 unconditionally tried to add it again,
causing every fresh install's migration chain to silently fail and fall
back to create_all(). Fixed by making 002 check first.

Runs via a genuinely fresh subprocess with PAPIS_DB_PATH set in its
environment before the interpreter even starts — alembic/env.py reads
papis.database.DB_PATH, which is computed once at first import and
can't be overridden retroactively within an already-running test
process (module-level constants don't re-read os.environ after import).
This also matches how migrations are actually invoked in practice
(`make migrate`, `papis-api`) more faithfully than an in-process call
would.
"""
import os
import sqlite3
import subprocess
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")


def _run_fresh_migration(db_path: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c",
         "from papis.database import init_db; init_db(dev_mode=False)"],
        cwd=BACKEND_DIR,
        env={**os.environ, "PAPIS_DB_PATH": db_path},
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestMigrationChain:

    def test_full_chain_applies_cleanly_with_no_fallback(self, tmp_path):
        db_path = str(tmp_path / "fresh.db")
        proc = _run_fresh_migration(db_path)

        assert proc.returncode == 0, proc.stderr
        # The real regression: this used to log "falling back to
        # create_all()" because 001->002 raised a duplicate-column error.
        assert "falling back to create_all" not in proc.stderr
        assert "falling back to create_all" not in proc.stdout

    def test_uv_mode_column_present_after_fresh_migration(self, tmp_path):
        db_path = str(tmp_path / "fresh.db")
        _run_fresh_migration(db_path)

        conn = sqlite3.connect(db_path)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(packages)")}
        conn.close()
        assert "uv_mode" in cols

    def test_package_locations_table_created(self, tmp_path):
        db_path = str(tmp_path / "fresh.db")
        _run_fresh_migration(db_path)

        conn = sqlite3.connect(db_path)
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        conn.close()
        assert "package_locations" in tables

    def test_running_migration_twice_is_a_safe_noop(self, tmp_path):
        db_path = str(tmp_path / "fresh.db")
        first = _run_fresh_migration(db_path)
        second = _run_fresh_migration(db_path)
        assert first.returncode == 0
        assert second.returncode == 0
