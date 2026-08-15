"""Alembic environment configuration.

Migrations run against the blocking `psycopg` DSN from application settings,
so the async engine the app uses at runtime is never involved here. The URL is
read from `.env` rather than `alembic.ini`, keeping credentials out of version
control.
"""

import importlib
import pkgutil
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import app.modules
from app.core.config import settings
from app.core.database import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# `%` is ConfigParser's interpolation marker, so a password containing one
# would otherwise blow up here.
config.set_main_option("sqlalchemy.url", settings.sync_database_url.replace("%", "%%"))


def import_all_models() -> None:
    """Import every `app.modules.<module>.models` package.

    Autogenerate only sees tables whose model classes have been imported.
    Walking the module packages means a new feature module is picked up
    automatically, instead of failing silently because someone forgot to add
    an import here.
    """
    for module_info in pkgutil.iter_modules(
        app.modules.__path__, f"{app.modules.__name__}."
    ):
        if not module_info.ispkg:
            continue

        models_package = f"{module_info.name}.models"
        # `find_spec` first, so a genuine ImportError inside a models package
        # propagates instead of being swallowed as "module not found".
        if importlib.util.find_spec(models_package) is not None:
            importlib.import_module(models_package)


import_all_models()

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting - `alembic upgrade head --sql`."""
    context.configure(
        url=settings.sync_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the database and apply migrations."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Detect column type and server default changes, which Alembic
            # ignores by default.
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
