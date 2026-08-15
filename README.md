# BWIN Consultants API

CMS + LMS platform backend built with FastAPI.

## Technology Stack

| Layer      | Technology                                        |
| ---------- | ------------------------------------------------- |
| Framework  | FastAPI                                           |
| ORM        | SQLAlchemy 2.x                                    |
| Database   | PostgreSQL                                        |
| Migrations | Alembic                                           |
| Validation | Pydantic v2                                       |
| Cache      | Redis                                             |
| Auth       | JWT                                               |
| Tooling    | Black, Ruff, Pytest, Pre-Commit, Docker           |

## Requirements

- Python 3.11+

## Getting Started

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS / Linux

# 2. Install dependencies
pip install -r requirements/dev.txt

# 3. Configure the environment
copy .env.example .env        # Windows
cp .env.example .env          # macOS / Linux

# 4. Run the development server
uvicorn app.main:app --reload
```

The API is then served at `http://127.0.0.1:8000`.

| Resource       | URL                                        |
| -------------- | ------------------------------------------ |
| Swagger UI     | http://127.0.0.1:8000/docs                 |
| ReDoc          | http://127.0.0.1:8000/redoc                |
| OpenAPI schema | http://127.0.0.1:8000/openapi.json         |
| Health check   | http://127.0.0.1:8000/api/v1/health        |

Docs are disabled automatically when `ENVIRONMENT=production`.

## Project Structure

```text
bwin_apis/
│
├── app/
│   ├── core/           # Config, database, security, dependencies, exceptions
│   ├── api/v1/         # Versioned route registration
│   ├── modules/        # Feature modules (auth, users, roles, cms, lms, ...)
│   ├── shared/         # Cross-module services, repositories, schemas, utils
│   ├── jobs/           # Background jobs
│   ├── storage/        # Uploads and exports
│   └── main.py         # Application factory and entrypoint
│
├── tests/
├── docs/
├── requirements/
└── README.md
```

Every feature module follows the same layout:

```text
modules/<module>/
├── models/
├── schemas/
├── repositories/
├── services/
├── routers/
├── permissions.py
└── constants.py
```

## Architecture Rules

- Feature-based architecture
- Request flow: **Router → Service → Repository → Database**
- Business logic lives only in services
- Database queries live only in repositories
- Routers stay thin
- Dependency injection everywhere
- `snake_case` naming, plural table names
- REST standards, versioned under `/api/v1/`

## Database

PostgreSQL 13+ is required (`gen_random_uuid()` must be built in). Create the
database once, then point `.env` at it:

```sql
CREATE DATABASE bwindb;
```

[app/core/database.py](app/core/database.py) owns the async engine, the session
factory and the declarative `Base`. Models inherit `Base` plus the mixins they
need:

```python
from app.core.database import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CourseModule(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    title: Mapped[str] = mapped_column(String(255))
    # __tablename__ is derived automatically -> "course_modules"
```

| Piece                  | Behaviour                                                            |
| ---------------------- | -------------------------------------------------------------------- |
| `Base`                 | Derives `__tablename__` as the snake_case plural of the class name    |
| `UUIDPrimaryKeyMixin`  | `id` UUID, defaulted server-side by `gen_random_uuid()`               |
| `TimestampMixin`       | `created_at` / `updated_at`, both maintained by PostgreSQL            |
| `SoftDeleteMixin`      | Nullable indexed `deleted_at` plus an `is_deleted` property           |
| `NAMING_CONVENTION`    | Deterministic constraint names, so Alembic diffs stay stable          |

Inject a session with `DbSession` from
[app/core/dependencies.py](app/core/dependencies.py):

```python
@router.get("/{course_id}")
async def get_course(course_id: UUID, db: DbSession) -> APIResponse[CourseRead]: ...
```

The dependency rolls back and closes automatically. **Services own the
transaction and call `await db.commit()` explicitly** — FastAPI runs dependency
teardown after the response has been sent, so committing there would fail
silently with the client already told the request succeeded.

`GET /api/v1/health/ready` verifies connectivity and returns 503 when the
database is unreachable.

## Migrations

Alembic owns the schema. It reads its connection string from `.env` via
`settings.sync_database_url`, so `alembic.ini` holds no credentials.

```bash
alembic upgrade head                              # apply pending revisions
alembic revision --autogenerate -m "add courses"  # generate from model changes
alembic downgrade -1                              # revert the last revision
alembic current                                   # what the database is on
alembic check                                     # fail if models drifted
```

`env.py` imports every `app/modules/<module>/models` package automatically, so
a new module is picked up without editing it — but a model must be exported
from that package's `__init__.py` to be visible to autogenerate.

Always read a generated revision before applying it, and verify the rollback
with `alembic downgrade -1 && alembic upgrade head`.

The full workflow, conventions and troubleshooting are in
[docs/migrations.md](docs/migrations.md).

## Configuration

All settings live in [app/core/config.py](app/core/config.py) and are read from
the environment, falling back to `.env`. Copy `.env.example` to `.env` and edit
it — see that file for every available key.

- Secrets (`SECRET_KEY`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`) are `SecretStr`,
  so they never appear in logs, tracebacks, or `model_dump()` output.
- Connection strings are assembled from parts: `settings.database_url`,
  `settings.sync_database_url` (Alembic), `settings.redis_url`.
- `ENVIRONMENT=production` disables `/docs`, `/redoc` and `/openapi.json`, and
  the app refuses to boot if `SECRET_KEY` is still the default or `DEBUG` is on.

Inject settings into a route with `SettingsDep` from
[app/core/dependencies.py](app/core/dependencies.py), which also provides
`PaginationDep`, `SortDep` and `SearchDep`.

## Response Format

Every successful endpoint returns the same envelope:

```json
{
  "success": true,
  "message": "Operation completed",
  "data": {}
}
```

Failures keep that shape and add `error_code`, plus `errors` for field level
validation problems:

```json
{
  "success": false,
  "message": "Request validation failed.",
  "data": null,
  "error_code": "VALIDATION_ERROR",
  "errors": [{ "field": "body.email", "message": "field required", "type": "missing" }]
}
```

## Repository Layer

Every module's repository subclasses `BaseRepository`, so routine CRUD is
written once:

```python
class CourseRepository(BaseRepository[Course]):
    model = Course
```

That yields `get`, `get_or_raise`, `get_by`, `get_by_field`, `list`, `count`,
`paginate`, `exists`, `create`, `create_many`, `update`, `delete`,
`soft_delete` and `restore`.

**Filtering** is declarative, so services build criteria without importing the
ORM. Conditions are combined with `AND`:

```python
courses, total = await repository.paginate(
    pagination,
    filters=[Filter.eq("status", "published"), Filter.gte("price", 100)],
    search=search.search,
    search_fields=["title", "summary"],
    sort_by=sort.sort_by,
    sort_order=sort.sort_order,
)
return paginated_response(courses, total, pagination)
```

Operators: `eq` `ne` `gt` `gte` `lt` `lte` `in_` `not_in` `contains`
`starts_with` `ends_with` `is_null` `between`, plus raw `like` / `ilike`.

Notes that matter in practice:

- **Field names are validated against the model.** A name that is not a mapped
  column raises `UnknownFieldError`, which renders as a 400 — these names
  usually arrive from query parameters, so a typo must not become a 500.
- **Search input is escaped.** A term containing `%` or `_` matches literally
  instead of behaving as a wildcard.
- **Ordering always ends with a primary key tiebreaker.** Without a total
  order, rows sharing a `created_at` can swap between queries, so a paginating
  client sees one row twice and never sees another.
- **Soft-deleted rows are excluded by default** on models carrying
  `deleted_at`. Pass `include_deleted=True` to see them.
- **Repositories never commit.** They `flush()` so the database assigns
  defaults; the service owns the transaction.

## Shared Utilities

Cross-module helpers live in [app/shared/](app/shared/) and are re-exported from
`app.shared.utils` and `app.shared.schemas`.

**Response builders** — [app/shared/schemas/response.py](app/shared/schemas/response.py)

```python
success_response(data, message)                            # 200
created_response(data)                                     # 201
deleted_response()                                         # no payload
paginated_response(items, total_items, pagination)         # page + metadata
```

**Pagination** — combine `PaginationDep` with `paginated_response`. The
repository returns the page slice and the total row count; the builder does
the rest:

```python
@router.get("")
async def list_courses(
    db: DbSession, pagination: PaginationDep
) -> APIResponse[Page[CourseRead]]:
    items, total = await service.list_courses(db, pagination)
    return paginated_response(items, total, pagination, "Courses fetched")
```

```json
{ "success": true, "message": "Courses fetched",
  "data": { "items": [...],
            "meta": { "page": 2, "page_size": 20, "total_items": 45,
                      "total_pages": 3, "has_next": true, "has_previous": true } } }
```

**Dates** — [app/shared/utils/dates.py](app/shared/utils/dates.py). Everything is
timezone-aware UTC; naive input is assumed UTC, never local time.

```python
utc_now()                     start_of_day(dt) / end_of_day(dt)
ensure_utc(dt)                add_days(dt, n) / days_between(a, b)
to_iso(dt) / parse_iso(s)     is_expired(dt) / is_future(dt)
time_ago(dt)                  # "3 hours ago", "in 2 days"
```

**Slugs** — [app/shared/utils/slug.py](app/shared/utils/slug.py)

```python
slugify("Café & Bar: São Paulo!")     # 'cafe-and-bar-sao-paulo'
slugify("CEO's Guide")                # 'ceos-guide'
await generate_unique_slug(title, repository.slug_exists)
```

`slugify` transliterates accents, spells out `&` and `@`, drops apostrophes,
and truncates at a word boundary. It returns `""` when nothing survives (a
title of only emoji, say) — `generate_unique_slug` handles that by falling
back to a random token, and appends `-2`, `-3`, … until the slug is free.

## Error Handling

Services raise the exceptions in [app/core/exceptions.py](app/core/exceptions.py)
rather than `HTTPException`, so business logic stays free of HTTP concerns:

| Exception                     | Status | `error_code`          |
| ----------------------------- | ------ | --------------------- |
| `BadRequestException`         | 400    | `BAD_REQUEST`         |
| `UnauthorizedException`       | 401    | `UNAUTHORIZED`        |
| `ForbiddenException`          | 403    | `FORBIDDEN`           |
| `NotFoundException`           | 404    | `NOT_FOUND`           |
| `ConflictException`           | 409    | `CONFLICT`            |
| `ValidationException`         | 422    | `VALIDATION_ERROR`    |
| `TooManyRequestsException`    | 429    | `RATE_LIMITED`        |
| `ServiceUnavailableException` | 503    | `SERVICE_UNAVAILABLE` |

```python
raise NotFoundException("Course")   # -> 404 {"message": "Course not found.", ...}
```

`register_exception_handlers()` also converts FastAPI's own aborts, request
validation errors, and unhandled exceptions into the same envelope. Unhandled
errors are logged with a full traceback and return a generic message whenever
`DEBUG` is off.

## Development

```bash
pytest              # run the test suite
black .             # format
ruff check .        # lint
pre-commit install  # enable git hooks
```
