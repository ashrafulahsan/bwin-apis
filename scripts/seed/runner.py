"""Running a selection of seeders against one session.

The production guard lives here rather than in the entry point so that
anything driving the seeders - a test, a fixture, a future management command
- goes through it, and it runs before `app.core.database` is imported, so a
refusal happens before anything has opened a connection to the database it is
refusing to touch.
"""

from collections.abc import Sequence

from app.core.config import settings
from scripts.seed.base import Seeder, SeedOptions
from scripts.seed.registry import missing_requirements


def guard_production(*, force: bool) -> None:
    """Refuse to seed a production database unless explicitly forced."""
    if settings.is_production and not force:
        raise SystemExit(
            "Refusing to seed against production.\n"
            "Demo accounts share a known password, which must never exist on a "
            "live system. Pass --force only if you are certain."
        )


async def seed(seeders: Sequence[Seeder], options: SeedOptions) -> None:
    """Run each seeder in turn, then let each report on the result.

    All of them share one session, and each seeder commits its own work: they
    are separate units, and a failure in the third should not roll back the
    two that already succeeded and printed their counts.

    Reports run in a second pass, once every seeder has finished, so one can
    describe rows another created.
    """
    # Imported here so the production guard runs before any connection opens.
    from app.core.database import AsyncSessionFactory, dispose_engine

    print(f"Seeding {settings.postgres_db} ({settings.environment.value})")

    for seeder, required in missing_requirements(seeders):
        print(f"  note: '{seeder}' usually runs after '{required}', left out here")

    async with AsyncSessionFactory() as session:
        for seeder in seeders:
            counts = await seeder.run(session, options)
            print(f"  {seeder.name}: {summarize(counts)}")

        for seeder in seeders:
            await seeder.report(session, options)

    await dispose_engine()

    print()


def summarize(counts: dict[str, int]) -> str:
    """`{"roles": 7, "settings": 0}` reads back as `7 roles, 0 settings`."""
    if not counts:
        return "nothing to do"

    return ", ".join(f"{value} {label}" for label, value in counts.items())
