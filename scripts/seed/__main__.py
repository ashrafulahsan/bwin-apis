"""The `python -m scripts.seed` command line.

    python -m scripts.seed                  # everything, in registry order
    python -m scripts.seed --list           # what is registered
    python -m scripts.seed --only reference # what a real environment wants
    python -m scripts.seed --skip blogs

Nothing here knows what any particular seeder does. Adding one to the
registry gives it a name on `--only` and `--skip` and a line in `--list`
without this file changing.
"""

import argparse
import asyncio
import sys

from scripts.seed.base import Seeder, SeedOptions
from scripts.seed.registry import SEEDER_NAMES, SEEDERS, select
from scripts.seed.runner import guard_production, seed
from scripts.seed.users import DEFAULT_PASSWORD


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.seed",
        description="Seed the database with reference data and demo content.",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        default=[],
        metavar="SEEDER",
        help=f"Run only these seeders: {', '.join(SEEDER_NAMES)}.",
    )
    parser.add_argument(
        "--skip",
        nargs="+",
        default=[],
        metavar="SEEDER",
        help="Run everything except these seeders.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Show the registered seeders and what each one does.",
    )
    parser.add_argument(
        "--password",
        default=DEFAULT_PASSWORD,
        help="Password given to every demo account.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow seeding even when ENVIRONMENT is production.",
    )
    parser.add_argument(
        "--skip-users",
        action="store_true",
        help=argparse.SUPPRESS,  # Superseded by `--skip users`.
    )
    return parser.parse_args(argv)


def show_seeders() -> None:
    print("\n  SEEDER      RUNS AFTER   DESCRIPTION")
    print("  " + "-" * 74)

    for seeder in SEEDERS:
        after = ", ".join(seeder.requires) or "-"
        print(f"  {seeder.name:<12}{after:<13}{seeder.description}")

    print()


def selection(args: argparse.Namespace) -> tuple[Seeder, ...]:
    """The seeders these arguments ask for, deprecated spellings included."""
    skip = [*args.skip, *(["users"] if args.skip_users else [])]

    return select(only=args.only, skip=skip)


def run(args: argparse.Namespace) -> None:
    if args.list:
        show_seeders()
        return

    guard_production(force=args.force)

    selected = selection(args)

    if not selected:
        raise SystemExit("That selection leaves nothing to seed. See --list.")

    asyncio.run(seed(selected, SeedOptions(password=args.password)))


if __name__ == "__main__":
    # `parse_args` outside the guard: argparse exits through SystemExit for
    # `--help` too, and that is not an error worth printing to stderr.
    arguments = parse_args()

    try:
        run(arguments)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        raise
