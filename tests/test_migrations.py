"""Guardrails for the Alembic setup."""

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.config import BASE_DIR

ALEMBIC_INI = BASE_DIR / "alembic.ini"


@pytest.fixture(scope="module")
def script_directory() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))


def test_alembic_ini_exists() -> None:
    assert ALEMBIC_INI.is_file()


def test_alembic_ini_carries_no_credentials() -> None:
    """The URL comes from `.env`; a DSN here would leak into version control."""
    contents = ALEMBIC_INI.read_text(encoding="utf-8")

    for line in contents.splitlines():
        assert not line.strip().startswith("sqlalchemy.url")


def test_migrations_have_exactly_one_head(script_directory: ScriptDirectory) -> None:
    """Two heads mean a bad merge; `alembic upgrade head` would fail."""
    assert len(script_directory.get_heads()) == 1


def test_every_revision_is_reversible(script_directory: ScriptDirectory) -> None:
    """A revision without a `downgrade` breaks rollback of a bad release."""
    for revision in script_directory.walk_revisions():
        source = Path(revision.path).read_text(encoding="utf-8")
        assert "def downgrade()" in source, f"{revision.revision} has no downgrade()"


def test_revision_filenames_are_date_prefixed(
    script_directory: ScriptDirectory,
) -> None:
    for revision in script_directory.walk_revisions():
        name = Path(revision.path).name
        assert name[:4].isdigit(), f"{name} is not date prefixed"
