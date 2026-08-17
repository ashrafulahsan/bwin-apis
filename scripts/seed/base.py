"""What a seeder is, and the few helpers every one of them shares.

A seeder owns one domain's data. It knows how to fill an empty database and
how to leave an already-filled one alone, and nothing else: the order they
run in, which of them a command line asked for, and the session they share
all belong to the runner. That is what keeps adding a domain down to a module
and a line in the registry, rather than an edit to the entry point.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class SeedOptions:
    """Whatever a seeder needs from the command line, in one object.

    One object rather than a widening parameter list: a seeder written next
    year that needs something new adds a field here, and no existing
    signature changes.
    """

    password: str


class Seeder(ABC):
    """One domain's worth of seed data."""

    #: How the registry, the command line and the run output refer to this.
    name: ClassVar[str]

    #: One line for `--list`.
    description: ClassVar[str]

    #: Seeders that should have run first. Registry order is not enough on
    #: its own, because `--only` can select any subset of it.
    #:
    #: The runner warns rather than refuses: seeding blogs without users
    #: gives posts with no byline, which is degraded but still useful, and a
    #: seeder that genuinely cannot proceed is better off saying so itself,
    #: in terms of what is actually missing.
    requires: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    async def run(self, session: AsyncSession, options: SeedOptions) -> dict[str, int]:
        """Create whatever is missing, and return what was created.

        Idempotent by contract: a second run against the same database must
        create nothing and come back with zeroes.

        The keys are printed as written, so they read as plural nouns -
        `{"roles": 7}` becomes `7 roles`.
        """

    async def report(self, session: AsyncSession, options: SeedOptions) -> None:
        """Print what is in the database now.

        Optional, and silent unless a seeder overrides it. Reports run after
        every seeder has finished, so one can describe rows another created.
        """
        return None

    def __repr__(self) -> str:
        return f"<Seeder {self.name}>"


class AllPages:
    """Pagination stand-in for a report that wants everything."""

    page = 1
    page_size = 100


def heading(columns: str, *, width: int = 58) -> None:
    """Open a report table with its column header and a rule underneath."""
    print(f"\n  {columns}")
    print("  " + "-" * width)
