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
