"""
Alembic environment config.
Run migrations with:
  cd backend && alembic upgrade head
  cd backend && alembic revision --autogenerate -m "describe change"
"""
from logging.config import fileConfig
from pathlib import Path
import sys

from sqlalchemy import engine_from_config, pool
from alembic import context

# Make papis importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from papis.database import engine, DB_PATH
from papis.models import Base

config = context.config

if config.config_file_name:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url with the runtime DB path so it matches database.py
config.set_main_option("sqlalchemy.url", f"sqlite:///{DB_PATH}")

target_metadata = Base.metadata


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,      # required for SQLite ALTER TABLE support
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # required for SQLite ALTER TABLE support
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()