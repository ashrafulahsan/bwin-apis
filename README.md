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

## Response Format

Every endpoint returns the same envelope:

```json
{
  "success": true,
  "message": "Operation completed",
  "data": {}
}
```

## Development

```bash
pytest              # run the test suite
black .             # format
ruff check .        # lint
pre-commit install  # enable git hooks
```
