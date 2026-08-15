# Migration Workflow

Schema changes are made through Alembic. Never edit a table by hand in pgAdmin —
the migration history is the source of truth for every environment.

## Setup

Alembic reads its connection string from `settings.sync_database_url`, which is
built from the `POSTGRES_*` values in `.env`. `alembic.ini` intentionally has no
`sqlalchemy.url`, so no credentials are committed.

| File                     | Role                                                        |
| ------------------------ | ----------------------------------------------------------- |
| `alembic.ini`            | Script location, file naming, post-write hooks, logging      |
| `alembic/env.py`         | Wires Alembic to app settings and `Base.metadata`            |
| `alembic/script.py.mako` | Template for generated revisions                             |
| `alembic/versions/`      | The revision history — commit every file here                |

## Adding a Change

1. Write or edit the model under `app/modules/<module>/models/`.
2. Make sure the class is exported from that package's `__init__.py`.
   `env.py` imports every `app.modules.<module>.models` package automatically,
   so a model that is not re-exported there is invisible to autogenerate and
   will be silently skipped.
3. Generate the revision:

   ```bash
   alembic revision --autogenerate -m "add courses table"
   ```

4. **Read the generated file before applying it.** Autogenerate is a first
   draft, not an answer. It reliably misses renames (it emits a drop plus an
   add, which loses data), `CHECK` constraints, and anything needing a data
   backfill.
5. Apply it:

   ```bash
   alembic upgrade head
   ```

6. Confirm the rollback path works before committing:

   ```bash
   alembic downgrade -1 && alembic upgrade head
   ```

7. Commit the model and the revision file together, in the same commit.

## Command Reference

| Command                                    | Effect                                         |
| ------------------------------------------ | ---------------------------------------------- |
| `alembic upgrade head`                     | Apply every pending revision                   |
| `alembic upgrade +1`                       | Apply the next revision only                   |
| `alembic downgrade -1`                     | Revert the most recent revision                |
| `alembic downgrade base`                   | Revert everything                              |
| `alembic current`                          | Show the revision the database is on           |
| `alembic history --verbose`                | Show the full revision graph                   |
| `alembic heads`                            | Show head revisions — more than one means a bad merge |
| `alembic check`                            | Fail if models have drifted from migrations    |
| `alembic revision -m "msg"`                | Create an empty revision to hand-write         |
| `alembic upgrade head --sql`               | Print SQL instead of executing it              |

## Key Conventions

Every table has a **single-column UUID `id` primary key**, including the
association tables `user_roles` and `role_permissions`. That keeps every row
addressable by one value, matches the rest of the schema, and lets an
association later gain columns such as `assigned_by` or `expires_at` without a
key change.

An association table therefore **must** also carry a `UNIQUE` constraint on
its natural key:

```python
UniqueConstraint("user_id", "role_id", name="uq_user_roles_user_role")
```

That constraint is doing the job the composite primary key used to do. Drop it
and the same role can be assigned to a user twice. `tests/test_schema.py`
asserts both the `id` primary keys and these unique constraints, and proves the
duplicate rejection against PostgreSQL rather than trusting the metadata.

Add an index on the **second** column of the pair as well. The unique index
only serves queries leading with the first column, so "which users hold this
role" would otherwise scan the table.

## Editing an Applied Migration

Only safe before a revision has been deployed anywhere. Editing one that other
databases already ran produces a `downgrade()` that no longer matches their
schema — dropping an index the old version never created, for example.

Before deploy: edit the revision, then rebuild the local database. If the
edited `downgrade()` can no longer run, drop the affected tables, rewind
`alembic_version` to the previous revision, and `alembic upgrade head`.

After deploy: never edit. Write a new revision with `op.add_column`,
`op.create_unique_constraint` and friends.

## Conventions

- **One head, always.** `alembic heads` must return a single revision. If two
  branches each added a migration, run `alembic merge heads` and commit the
  merge revision.
- **Every revision is reversible.** `downgrade()` must undo `upgrade()`. A
  revision that cannot be reverted should raise, not silently `pass`.
- **Constraint names are deterministic.** `NAMING_CONVENTION` in
  [app/core/database.py](../app/core/database.py) yields `pk_users`,
  `fk_courses_author_id_users`, `ix_users_email` and so on. This is what lets
  autogenerate produce clean diffs instead of churn against PostgreSQL's
  generated names.
- **Generated files are formatted automatically.** `alembic.ini` runs Black and
  Ruff as post-write hooks, so revisions pass the same gate as hand-written
  code.

## Deploying

Run migrations before starting the new application version:

```bash
alembic upgrade head && uvicorn app.main:app
```

For a review of what a deploy will execute, generate the SQL offline:

```bash
alembic upgrade <current_rev>:head --sql > deploy.sql
```

## Troubleshooting

**`Target database is not up to date`** — the database is behind the latest
revision. Run `alembic upgrade head`.

**`Can't locate revision identified by '<rev>'`** — `alembic_version` names a
revision that no longer exists in `alembic/versions/`, usually after a branch
switch. Check out the branch that has the file, downgrade, then switch back.

**Autogenerate produced an empty migration** — the model was never imported.
Confirm it is exported from `app/modules/<module>/models/__init__.py`.

**Autogenerate wants to drop and recreate a table you renamed** — it cannot
detect renames. Replace the generated operations with
`op.rename_table()` / `op.alter_column(new_column_name=...)` by hand.
