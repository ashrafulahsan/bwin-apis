"""Seed the database with reference data and demo content.

    python -m scripts.seed

Reference data - roles, permissions and their default grants - is also
applied by migration, so seeding only fills gaps. Translations, demo accounts
and the demo blog content are not, so this is how they get in.

Demo accounts share one known password, which is exactly why this is a script
and not a migration: a migration would create them on every deployment,
including production, leaving well-known credentials on a live system.
Seeding refuses to run against production unless explicitly forced.

Every run is idempotent - anything already there is left alone.

## Layout

One module per domain, and one line per domain in the registry:

    base.py         what a seeder is, and the helpers they share
    registry.py     every seeder, in the order they have to run
    runner.py       the production guard, the session, the run itself
    __main__.py     the command line
    reference.py    roles, permissions, settings, translations
    users.py        demo accounts
    blogs.py        blog categories, tags and posts
    data/           the specs, separated from the code that applies them

## Adding a seeder

Write `<domain>.py` with a `Seeder` subclass - a `name`, a `description`,
whatever it `requires`, an idempotent `run`, and a `report` if there is
something worth printing. Put the rows themselves in `data/<domain>.py`, so a
long list of demo content never crowds out the logic that applies it. Then
add the class to `SEEDERS` in `registry.py`, in the position its dependencies
need. The command line picks it up from there.
"""

from scripts.seed.base import AllPages, Seeder, SeedOptions, heading
from scripts.seed.blogs import (
    BlogSeeder,
    seed_blog_content,
    seed_blog_vocabulary,
    seed_demo_blogs,
)
from scripts.seed.reference import ReferenceSeeder, seed_reference_data
from scripts.seed.registry import (
    SEEDER_NAMES,
    SEEDERS,
    missing_requirements,
    select,
)
from scripts.seed.runner import guard_production, seed, summarize
from scripts.seed.users import DEFAULT_PASSWORD, UserSeeder, seed_demo_users

__all__ = [
    "SEEDERS",
    "SEEDER_NAMES",
    "AllPages",
    "BlogSeeder",
    "DEFAULT_PASSWORD",
    "ReferenceSeeder",
    "SeedOptions",
    "Seeder",
    "UserSeeder",
    "guard_production",
    "heading",
    "missing_requirements",
    "seed",
    "seed_blog_content",
    "seed_blog_vocabulary",
    "seed_demo_blogs",
    "seed_demo_users",
    "seed_reference_data",
    "select",
    "summarize",
]
