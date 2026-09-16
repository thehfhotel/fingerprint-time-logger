from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.models.models import Base
from app.models import staff_leave  # noqa: F401 — register leave tables for autogenerate
from app.services.deploy_backup import before_migrations

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Render SQL only. Does not access the production database."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    try:
        if connectable.url.get_backend_name() != 'sqlite':
            raise RuntimeError('This application requires a SQLite migration backup')
        # No writable DB connection or migration can happen before this gate.
        # The context also keeps concurrent migration processes serialized.
        with before_migrations(connectable.url.database or ''):
            with connectable.connect() as connection:
                context.configure(connection=connection, target_metadata=target_metadata)
                with context.begin_transaction():
                    context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
