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
  the app refuses to boot if `SECRET_KEY` is still the default, shorter than
  32 bytes, or `DEBUG` is on.
- `ENVIRONMENT=testing` switches the connection pool off. A pooled connection
  belongs to the event loop that opened it, and the suite runs more than one —
  the `TestClient` drives the app in its own loop while async fixtures run in
  pytest's.

Inject settings into a route with `SettingsDep` from
[app/core/dependencies.py](app/core/dependencies.py), which also provides
`PaginationDep`, `SortDep` and `SearchDep`. Authentication adds `CurrentUser`,
`OptionalUser` and the `require_permission` / `require_role` guards, in
[app/modules/auth/dependencies.py](app/modules/auth/dependencies.py).

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

## Languages (i18n)

The platform serves **English (`en`, default)** and **Bengali (`bn`)**.

Language is resolved per request, with `?lang=` taking precedence over the
header — a reader clicking "বাংলা" should get Bengali even though their browser
still sends `Accept-Language: en`:

```bash
curl /api/v1/health                                   # -> en
curl /api/v1/health?lang=bn                           # -> bn
curl -H "Accept-Language: bn-BD,bn;q=0.9" /api/v1/health   # -> bn
curl /api/v1/health?lang=fr                           # -> en (falls back)
```

Every response carries `Content-Language`, plus `Vary: Accept-Language` so
shared caches key on the header rather than the URL alone.

**Reading the language.** In a router, take the dependency — this is also what
puts `?lang=` in the OpenAPI schema:

```python
@router.get("/{course_id}")
async def get_course(course_id: UUID, language: LanguageDep) -> ...:
```

Anywhere without a request — services, repositories, jobs — read the context
variable the middleware established:

```python
from app.core.i18n import get_current_language

language = get_current_language()
```

**Helpers** live in [app/shared/utils/language.py](app/shared/utils/language.py):

```python
normalize_language("bn-BD")            # Language.BN  (region subtags dropped)
parse_accept_language(header)          # [('bn', 0.9), ('en', 0.8)] by quality
negotiate_language(header)             # best supported match
language_display_name(Language.BN)     # 'বাংলা'
pick_translation({"en": ..., "bn": ...}, language)
localized_field_name("title", Language.BN)   # 'title_bn'
```

Nothing here raises on bad input. An unrecognised tag or a malformed header
from a proxy falls back to the default — a language preference must never turn
a working page into an error.

`pick_translation` suits translations stored as JSONB; `localized_field_name`
suits per-language columns. Which one the content modules use is decided when
the CMS models land.

## Authentication

Sign in with a password, or with a Google or Facebook identity the caller has
already verified. `identifier` takes an **email address or a phone number** in
either format — the API works out which was given.

```
POST /api/v1/auth/login        {"identifier": "...", "password": "..."}
POST /api/v1/auth/social       {"provider": "google", "provider_user_id": "..."}
POST /api/v1/auth/refresh      {"refresh_token": "..."}
POST /api/v1/auth/logout       {"refresh_token": "..."}      requires a token
POST /api/v1/auth/logout-all                                 requires a token
GET  /api/v1/auth/me                                         requires a token
GET  /api/v1/auth/sessions                                   requires a token
```

Sign-in returns the account, its roles and its permission codes alongside the
tokens, so a client can render its navigation without a second request.

**Two tokens, with different jobs.** The access token proves who you are and
lasts 30 minutes; the refresh token only mints new access tokens and lasts 7
days. Send the access token as `Authorization: Bearer <token>`.

**The access token carries no roles or permissions** — only a subject, a type,
an id and an expiry. Authorization is read from the database on each request,
which costs one indexed query and means **a revoked role stops working
immediately** rather than lingering until the token expires.

**Sessions are rows, which is what makes logout mean something.** A signed JWT
is valid until it expires no matter what the server thinks, so every refresh
token gets a row in `refresh_tokens`; logout marks it revoked and refreshing
checks it. Only the **SHA-256 digest** is stored — a leaked database dump hands
over no usable sessions.

**Refresh tokens rotate.** Each one works exactly once; refreshing retires the
token presented and issues a new pair. Presenting an already-rotated token
means two parties hold it, and there is no way to tell the thief from the real
user — so **every session on the account ends** and the user signs in again.
A token revoked by an ordinary sign-out is *not* treated this way: a client
racing its own logout is a timing accident, not an attack.

**What logout does and does not do.** It revokes the refresh token, ending the
session. The access token is not revocable and stays usable until it expires,
which is exactly why its lifetime is short — clients should discard it on
sign-out. A *password change* is the exception: that stamps
`tokens_valid_from` on the user and every older access token fails at once,
because there the whole point is to cut someone off now rather than in half an
hour.

Guarding a route is declarative, so the check cannot be forgotten in a handler:

```python
from app.modules.auth.dependencies import CurrentUser, require_permission

@router.post("", dependencies=[Depends(require_permission("user.create"))])
async def create_user(user: CurrentUser, ...): ...
```

`CurrentUser` requires a token; `OptionalUser` allows anonymous callers but
still rejects a bad token, rather than quietly treating it as signed out.

A few deliberate choices worth knowing:

- **Failed sign-ins are indistinguishable.** A wrong password and an unknown
  address return the same message, and an unknown account still pays for a
  bcrypt hash so it is not measurably faster to reject. A *suspended* account
  is told why — the password was already proven, so nothing leaks.
- **`SECRET_KEY` must be at least 32 bytes.** HS256 signs every token with it,
  and RFC 7518 requires a key at least as long as the hash. The application
  refuses to boot in production with a shorter one, or with the placeholder.
- **`alg: none` cannot get through** — the decoder names the algorithm it
  accepts rather than trusting the token's header.
- **Deleting or suspending a user stops their tokens working** without anyone
  revoking anything, because the user is loaded on every request.

### Password recovery

```
POST /api/v1/auth/forgot-password        {"identifier": "..."}
POST /api/v1/auth/reset-password/verify  {"token": "..."}
POST /api/v1/auth/reset-password         {"token": "...", "new_password": "..."}
POST /api/v1/auth/change-password        requires a token
```

`identifier` takes an email address **or a phone number**, the same as
sign-in, and the link is sent back the way it was asked for.

**`/forgot-password` answers identically whatever happens** — unknown address,
suspended account, or a request that tripped the throttle all return the same
message with the same status. A form open to the internet that behaved
differently for a registered address would be a way to enumerate the
platform's users. Nothing is raised for an unknown account; the refusals are
logged where the person asking cannot see them.

Requests are throttled per account — one a minute, five an hour — so this
cannot be used to flood someone's inbox. The throttle is invisible in the
response, for the same reason.

**A link works exactly once, and asking for a new one retires the old.** Both
matter: without the second, an attacker who triggered a reset earlier still
holds a working token after the real owner has been through the flow. Links
last an hour, and only the SHA-256 digest is stored — a database dump gives up
no working links.

**A successful reset invalidates every token on the account — access tokens
included.** Revoking refresh tokens alone would leave whoever prompted the
reset holding a working access token for the rest of its lifetime, which is
the half hour the reset was meant to take away from them. A `tokens_valid_from`
stamp on the user makes older access tokens fail on their next request. It
also **marks the contact verified**: receiving the link proves control of the
address, which is exactly what verification means, so an account that never
clicked its confirmation email comes out unstuck and active.

`/reset-password/verify` exists so the page behind the link can say it has
expired *before* asking someone to think of a new password. It returns a
masked identifier — `lo•••••@bwin.example.com` — enough to recognise your own
account, not enough for a stranger holding the link to learn whose it is.

`/change-password` is the companion for someone already signed in: no link,
since the access token already proves who they are. It retires every token the
account held — **including the one that made the request** — and hands back a
replacement pair in the response, so the client changing the password stays
signed in while everything else is cut off. Pass
`sign_out_other_sessions: false` to opt out of all of it.

> **Delivery is not built yet.** There is no mail or SMS transport until the
> notifications module lands, so links go behind a `ResetLinkSender`
> interface whose default writes them to the log. Outside production it logs
> the whole link, which is how you complete the flow without a mailbox; in
> production it logs only *that* one was sent, since a log file should not be
> a way into every account. Swapping in a real sender changes nothing in the
> service.

## Social Login (Google and Facebook)

The full OAuth 2.0 authorization code flow, in two steps per provider:

```
GET /api/v1/auth/google/login        →  302 to Google's consent screen
GET /api/v1/auth/google/callback     →  exchanges the code, signs the user in
GET /api/v1/auth/facebook/login
GET /api/v1/auth/facebook/callback
GET /api/v1/auth/providers           →  which buttons a sign-in page should show
```

The client secret never touches the browser: the code-for-token exchange
happens server to server. On success the browser is redirected to the frontend
with the **same JWT pair** a password sign-in returns.

**Nothing is hardcoded.** Every value comes from the `settings` table and can
be changed by an administrator without a deployment:

| Key | |
| --- | --- |
| `google_auth_enabled` / `facebook_auth_enabled` | Off until credentials are filled in |
| `google_client_id` / `google_client_secret` | From the Google Cloud console |
| `facebook_app_id` / `facebook_app_secret` | From Meta for Developers |
| `google_callback_url` / `facebook_callback_url` | Optional — derived from `app_base_url` when blank |
| `app_base_url`, `frontend_url`, `social_login_redirect_path` | Where the API and the frontend live |

Manage them through `/api/v1/settings`, which **requires `setting.view` /
`setting.update`** — these rows hold client secrets, so an open settings API
would be a credential leak with a URL. Secrets come back as `********`, and
saving that mask back is refused rather than overwriting the real value.

### Setting a provider up

1. Register the callback with the provider. It must match **exactly** —
   Google and Facebook both compare it byte for byte:
   `https://your-api/api/v1/auth/google/callback`
2. `PATCH /api/v1/settings` with the client id, secret and
   `google_auth_enabled: "true"`.
3. `GET /api/v1/auth/providers` — `usable` turns true, and any missing key is
   named in `missing`.

### What the flow guarantees

- **State is bound to the browser.** A signed `state` alone is not enough, since
  an attacker can start a sign-in and collect one. So the state carries only
  the *digest* of a nonce, and the nonce goes to the browser in an HttpOnly,
  SameSite=Lax cookie. Finishing needs both halves — which is what stops a
  sign-in being completed inside someone else's session.
- **Tokens come back in the URL fragment**, not the query string. A fragment
  is never sent to a server, so it stays out of access logs, `Referer` headers
  and proxy records.
- **`redirect_to` cannot leave the site.** A target is honoured only on the
  configured frontend's origin; anything else falls back to the default. An
  open redirect on a page carrying tokens hands them to whoever asked.
- **An unverified address is never linked to an existing account.** Anyone can
  put someone else's address on a profile, so linking on that basis would be
  account takeover. Such a sign-in is refused with a message pointing at the
  safe route: sign in normally, then link from your profile. A *verified*
  address links, which is what stops a duplicate account per provider.
- **A cancelled sign-in returns to the frontend** with a readable error. A
  browser mid-redirect cannot show a JSON error body.
- Facebook accounts registered with a phone number arrive **without an email**;
  that is refused with an explanation rather than crashing.

With no `frontend_url` set, the callback returns the tokens as JSON instead —
which is what makes the flow usable, and testable, without a frontend.

### Fields on `users`

`google_id`, `facebook_id`, `social_provider` and `is_social_login` sit on the
user row for filtering and sorting without a join. **`user_identities` remains
the source of truth** — it holds the uniqueness constraints and can carry
several providers per account. The columns are written in exactly one place,
`UserRepository._sync_social_columns`, which recomputes them from the identity
rows rather than patching them, so the two cannot drift apart.

## Users

An account is identified by an **email address, a phone number, or both** —
and either one signs in. Both columns are nullable, with a `CHECK` constraint
guaranteeing at least one is present, so an account can never exist with no way
to reach it.

**Phone numbers are stored in E.164** and normalized on the way in, so however
someone types theirs it matches the same account:

```
01712345678  →  +8801712345678      01712-345678  →  +8801712345678
8801712345678 → +8801712345678      017 1234 5678 →  +8801712345678
```

The default country code is `+880`. A bare number already carrying the country
code is recognised only when its length works out, so a local number that
happens to start with those digits is not mangled.

**Look a user up without knowing which credential they used:**

```
GET /api/v1/users/by-identifier?identifier=ali@example.com
GET /api/v1/users/by-identifier?identifier=01712345678
```

**Social login** — Google and Facebook — lives in a separate `user_identities`
table rather than columns on `users`, so one account can hold a password *and*
several linked providers, and adding a provider needs no migration.

```python
user, created = await service.resolve_social_login(payload)
```

- A returning social login finds the existing account.
- A social login whose verified email already has an account **links to it**
  rather than creating a duplicate person.
- A social sign-up arrives `active` and `email_verified`, because the provider
  already proved the address.
- Unlinking is **refused when it is the only way in** — set a password first.
- Facebook without an email cannot create an account, since there would be no
  identifier to satisfy the `CHECK` constraint.

The caller must have verified the identity with the provider first; exchanging
the authorization code belongs to the caller, and `POST /api/v1/auth/social`
turns the verified result into a session.

**Passwords** are bcrypt, work factor 12, in
[app/core/security.py](app/core/security.py). Over 72 bytes is **refused, not
truncated** — bcrypt ignores the remainder, which would let two different
passwords open the same account. Changing an existing password requires the
current one, so a hijacked session cannot lock the owner out; an account
created through Google has none and can set its first without it.

**Roles are many-to-many.** An instructor who also manages content needs both,
and one-role-per-user is just the common case. A user's permissions are the
union across their roles:

```python
user.has_permission("course.create")   user.role_slugs
user.highest_level                     user.linked_providers()
```

New accounts become **students** unless `role_ids` says otherwise.

## Roles

Seven roles ship with the platform, seeded by migration so every environment
starts identical:

| Slug              | Name            | Level | Purpose                                    |
| ----------------- | --------------- | ----- | ------------------------------------------ |
| `super-admin`     | Super Admin     | 100   | Unrestricted access                        |
| `admin`           | Admin           | 90    | Users, roles, platform settings            |
| `content-manager` | Content Manager | 70    | Owns the content library, publishes pages  |
| `editor`          | Editor          | 60    | Writes and edits, cannot publish           |
| `instructor`      | Instructor      | 50    | Creates and teaches courses                |
| `support`         | Support         | 40    | Assists learners                           |
| `student`         | Student         | 10    | Enrols and tracks progress                 |

`level` orders privilege for comparisons such as "may this user edit that
one" — `role.outranks(other)`. The gaps are deliberate, leaving room for
custom roles to sit between the built-in ones.

**Endpoints** — `GET|POST /api/v1/roles`, `GET|PATCH|DELETE /api/v1/roles/{id}`,
plus `GET /roles/all` for pickers, `GET /roles/slug/{slug}`, and
`POST /roles/{id}/restore`.

Three rules protect the platform from locking itself out:

- **System roles cannot be deleted.** Removing Super Admin would shut every
  administrator out with no way back.
- **A system role's `level` is immutable.** Authorization compares levels, so
  demoting a built-in role could silently give a Student more power than an
  Admin. Renaming is allowed — the slug is what code depends on.
- **Slugs never change.** They are derived from the name at creation and fixed
  thereafter, so renaming "Instructor" to "Teacher" breaks nothing.

Deletion is soft. Note that `name` and `slug` carry database-level unique
constraints that ignore `deleted_at`, so a deleted role keeps its name — the
API says so explicitly and points you at restore.

Permission enforcement arrives with authentication; `permissions.py` already
reserves the names.

## Permissions

Permissions are `resource.action` codes — `user.view`, `course.create`. The
resource and action are also stored as separate columns, so an admin screen can
render the familiar grid of resources down the side and actions across the top.

50 permissions across 13 resources are seeded by migration, along with a
starting grant matrix:

| Role            | Grants | Shape                                             |
| --------------- | ------ | ------------------------------------------------- |
| Super Admin     | 50     | everything                                        |
| Admin           | 47     | everything except defining new permissions        |
| Content Manager | 16     | pages, media, categories — including publish      |
| Editor          | 8      | writes pages, **cannot publish or delete**        |
| Instructor      | 12     | courses, lessons, grading                         |
| Support         | 7      | read access plus sending notifications            |
| Student         | 4      | read-only                                         |

This is a starting point, not a constraint — administrators can change any of
it, and re-running the seed will not undo their changes.

**Endpoints**

| Endpoint                                          | Purpose                          |
| ------------------------------------------------- | -------------------------------- |
| `GET|POST /api/v1/permissions`                     | List and define permissions      |
| `GET|PATCH|DELETE /api/v1/permissions/{id}`        | Single permission                |
| `GET /api/v1/permissions/grouped`                  | Shaped for a permission grid     |
| `GET /api/v1/permissions/resources`                | Distinct resources               |
| `GET /api/v1/roles/{id}/permissions`               | A role's grants                  |
| `PUT /api/v1/roles/{id}/permissions`               | Replace — what a grid submits    |
| `POST /api/v1/roles/{id}/permissions`              | Grant, additive                  |
| `POST /api/v1/roles/{id}/permissions/revoke`       | Revoke                           |
| `GET /api/v1/roles/{id}/permissions/{code}`        | Check one code                   |

Revoke is a POST because the codes travel in the body and some proxies strip
bodies from DELETE requests.

**In code**, a loaded role carries its permissions eagerly:

```python
role.has_permission("page.publish")   # False for Editor
role.permission_codes                 # {"page.view", "page.create", ...}
```

The relationship is `lazy="selectin"` by design — under asyncio a lazy load
outside the original await raises `MissingGreenlet`, and a role's permission
set is small.

Four rules keep grants honest:

- **Unknown codes are rejected, never skipped.** Granting `["course.view",
  "typo.action"]` fails the whole request rather than silently granting one
  and leaving an administrator believing both went through.
- **System permissions cannot be deleted.**
- **A permission still granted to any role cannot be deleted** — that would
  strip access silently instead of making someone revoke it deliberately.
- **Re-granting is a no-op**, not a primary key violation.

## Categories

Two levels of structure. A **category type** names a taxonomy — "Blog Topics",
"Course Subjects" — and the **categories** inside it form a tree. Keeping the
taxonomy in its own table means a new one is a row rather than a migration,
and stops unrelated vocabularies sharing a namespace.

```
GET    /api/v1/category-types            POST   /api/v1/category-types
GET    /api/v1/category-types/{id}       PATCH  /api/v1/category-types/{id}
DELETE /api/v1/category-types/{id}       POST   /api/v1/category-types/{id}/restore

GET    /api/v1/categories                POST   /api/v1/categories
GET    /api/v1/categories/tree           PATCH  /api/v1/categories/{id}
GET    /api/v1/categories/{id}           PUT    /api/v1/categories/{id}/parent
DELETE /api/v1/categories/{id}           POST   /api/v1/categories/{id}/restore
GET    /api/v1/categories/{id}/children  GET    /api/v1/categories/{id}/ancestors
```

**Every route requires Super Admin or Admin.** The guard names roles rather
than permission codes, which is the exception `require_role` exists for: a
taxonomy is structural rather than editorial, and reshaping one moves every
piece of content filed under it. Content managers hold `category.create` as a
permission and are still refused here — deliberately. When the CMS and LMS
modules need editors to *read* categories to tag their work, the read routes
can move to `require_permission(CategoryPermission.VIEW)`, which those roles
already have.

### What the tree guarantees

A parent pointer is easy to store and easy to corrupt, so the service enforces
what the column cannot:

- **A category is never its own ancestor.** Moving one under its own
  descendant is refused — it would cut that branch out of the tree and leave
  it pointing round in a ring, reachable from nothing.
- **A parent must belong to the same category type**, or a tree read returns
  categories that do not belong to it.
- **Nesting stops at 5 levels.** Deeper reads badly in a menu and costs a
  query per level.
- **Deleting is refused while children exist**, and deleting a taxonomy is
  refused while it holds categories. Cascading would remove a whole branch on
  one click; the refusal says exactly what is in the way.
- **Changing a category's taxonomy is refused when it has a parent or
  children**, which would otherwise leave half a branch behind.

Names are unique *within* a taxonomy, so "Design" can be both a blog topic and
a course subject. Slugs are unique platform-wide, so a URL resolves without
knowing the type, and a slug never changes when its name does — it is already
in links.

`GET /categories/tree` returns a whole taxonomy nested, in one flat query
linked up in memory. With `active_only`, a category whose parent was filtered
out is promoted to the top rather than dropped, so nothing vanishes from a
menu without being deleted.

`created_by` and `updated_by` are filled from the access token and are
`ON DELETE SET NULL` — deleting the administrator who made a category must not
delete the category. Both tables also carry `deleted_at`: `status` answers
"should this be offered for new content?", which is a different question from
"does this still exist?".

## Translations

UI strings live in the `translations` table, one row per key per language.
Keys are dot-namespaced (`dashboard.title`, `login.button`, `course.enroll`),
and the first segment is stored as `namespace` so a screen can fetch only the
group it needs.

**Seed files** live in
[app/modules/translations/locales/](app/modules/translations/locales/) as
`en.json` and `bn.json`, reviewable in a pull request. They may be nested or
flat; both produce the same keys:

```json
{ "dashboard": { "title": "Dashboard" } }   →  dashboard.title
{ "dashboard.title": "Dashboard" }          →  dashboard.title
```

Import them with `TranslationService.sync_all_locales()`. It upserts via
`ON CONFLICT (key, language)`, so re-importing updates changed strings rather
than failing.

**Endpoints**

| Endpoint                                   | Purpose                              |
| ------------------------------------------ | ------------------------------------ |
| `GET /api/v1/translations`                  | Flat bundle for the negotiated language |
| `GET /api/v1/translations?namespace=login`  | Just one key group                   |
| `GET /api/v1/translations/namespaces`       | Available groups                     |
| `GET /api/v1/translations/missing?language=bn` | Untranslated keys — the translator's to-do list |
| `GET /api/v1/translations/entries`          | Paginated rows for an admin screen   |

The bundle honours the language rules from the i18n section, so `?lang=bn` and
`Accept-Language: bn` both work.

**Fallback is layered**, so an interface never shows a blank:

1. The requested language.
2. English, for keys not yet translated.
3. The key itself (`course.enroll`), which is obvious in review — unlike an
   empty string, which nobody notices.

**Interpolation** uses `{placeholders}`:

```python
await service.translate("dashboard.welcome", Language.BN, name="আশরাফুল")
# "স্বাগতম, আশরাফুল"
```

A translator who drops a placeholder gets the raw template back and a logged
warning, rather than a `KeyError` in production.

Write endpoints (create, update, delete, import) are deliberately not exposed
yet — they land with the roles module, since an unauthenticated write endpoint
would let anyone rewrite the interface. The service methods already exist.

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

### Seeding

```bash
python -m scripts.seed
```

Fills in roles, permissions, their default grants, translations, and a set of
demo accounts — one per role, so every role has someone to test with. Safe to
re-run: anything already present is left alone.

| Account                            | Role(s)                      | Notes                    |
| ---------------------------------- | ---------------------------- | ------------------------ |
| `superadmin@bwin.example.com`      | Super Admin                  | all 50 permissions       |
| `admin@bwin.example.com`           | Admin                        | 47 permissions           |
| `content@bwin.example.com`         | Content Manager              | Bengali interface        |
| `editor@bwin.example.com`          | Editor                       | cannot publish           |
| `instructor@bwin.example.com`      | Instructor                   |                          |
| `support@bwin.example.com`         | Support                      | Bengali interface        |
| `student@bwin.example.com`         | Student                      |                          |
| `lead.instructor@bwin.example.com` | Instructor + Content Manager | two roles at once        |
| `google.user@bwin.example.com`     | Student                      | Google only, no password |
| `pending@bwin.example.com`         | Student                      | unverified               |
| `suspended@bwin.example.com`       | Student                      | blocked                  |

Password: `BwinDemo#2026` (override with `--password`). Phone numbers run
`+8801700000001` upward, and either identifier signs in.

**Seeding is a script, not a migration, on purpose.** These accounts share one
known password, so a migration would plant well-known credentials on every
deployment including production. The script refuses to run when
`ENVIRONMENT=production` unless given `--force`. Addresses use
`bwin.example.com` — `example.com` is reserved by RFC 2606 and can never
receive mail.

`--skip-users` seeds only the reference data, which is what a real environment
wants.

### Testing

The suite runs against a **separate `bwindb_test` database**, created and
migrated automatically on first run. This is not optional: services commit for
real and some fixtures truncate tables, so running against `bwindb` would
destroy its seeded roles and translations. `tests/conftest.py` sets
`POSTGRES_DB` before importing the app and refuses to start if it still points
at `bwindb`. Override the name with `TEST_POSTGRES_DB` if it collides.

Because the test database is brought up with `alembic upgrade head`, the suite
also exercises the real migrations rather than a `create_all` shortcut.
