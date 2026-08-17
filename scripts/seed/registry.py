"""Every seeder there is, in the order they have to run.

An explicit list rather than a scan of the package, because the order is part
of the data - a blog post carries the byline of a demo account, so users come
first - and a scan would bury that in a filename convention.

Adding a domain is two lines here, on top of its own module.
"""

from collections.abc import Iterable, Sequence

from scripts.seed.base import Seeder
from scripts.seed.blogs import BlogSeeder
from scripts.seed.reference import ReferenceSeeder
from scripts.seed.users import UserSeeder

SEEDERS: tuple[Seeder, ...] = (
    ReferenceSeeder(),
    UserSeeder(),
    BlogSeeder(),
)

SEEDER_NAMES: tuple[str, ...] = tuple(seeder.name for seeder in SEEDERS)


def select(*, only: Sequence[str] = (), skip: Sequence[str] = ()) -> tuple[Seeder, ...]:
    """The seeders a command line asked for, in registry order.

    `only` names what to run and `skip` names what to leave out. Passing both
    is allowed and reads as "these, except those"; passing neither runs
    everything.
    """
    _reject_unknown([*only, *skip])

    wanted = set(only) if only else set(SEEDER_NAMES)
    wanted -= set(skip)

    return tuple(seeder for seeder in SEEDERS if seeder.name in wanted)


def missing_requirements(selected: Iterable[Seeder]) -> list[tuple[str, str]]:
    """`(seeder, dependency)` for each dependency left out of a selection.

    Reported rather than repaired: pulling a seeder in that was explicitly
    skipped would be the one thing the flag was asked to prevent.
    """
    running = {seeder.name for seeder in selected}

    return [
        (seeder.name, required)
        for seeder in selected
        for required in seeder.requires
        if required not in running
    ]


def _reject_unknown(names: Iterable[str]) -> None:
    unknown = sorted(set(names) - set(SEEDER_NAMES))

    if unknown:
        raise SystemExit(
            f"Unknown seeder: {', '.join(unknown)}. "
            f"Available: {', '.join(SEEDER_NAMES)}."
        )
