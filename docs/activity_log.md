# Activity Log

Every business action on this platform is recorded. Not "should be" — the
build fails when a service writes to the database without leaving a trace, so
this document describes a rule the test suite already enforces.

## The rule

A feature is not complete until all three of these are true:

1. the business logic is implemented,
2. its tests are implemented,
3. its activity logging is implemented.

This applies to every module that exists today and to every module added
later — CMS, LMS, Authentication, Settings, Media, Users, Roles, Permissions,
Reports, and whatever comes next.

## What must be logged

Create, Update, Delete, Login, Logout, Password Reset, Google Login, Facebook
Login, Role Changes, Permission Changes, Settings Changes, Media Upload and
Delete, Blog / Page / Course / Lesson operations, Enrolment operations, Status
Changes, Approvals, Publishing — and any business action a future module
invents.

Refusals count. A rejected sign-in is the entry an audit trail exists for, and
it is recorded with `status = failure`.

## Where the code lives

```
app/shared/services/activity_log_service.py   the one writer
app/core/context.py                           who is calling, and from where
app/modules/activity_logs/
  models/activity_log.py                      the table, actions, modules
  repositories/activity_log.py                reads
  services/activity_log.py                    the query service
  routers/activity_log.py                     GET /api/v1/activity-logs
  permissions.py                              activity_log.view / .export
```

The writer lives under `shared` because every module calls it. The table lives
in its own module, like every other table in the schema.

## Writing an entry

Bind the service to your module once, in the constructor:

```python
from app.modules.activity_logs.models.activity_log import (
    ActivityAction,
    ActivityModule,
)
from app.shared.services.activity_log_service import (
    ActivityLogService,
    diff,
    snapshot,
)


class CourseService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = CourseRepository(session)
        self.activity = ActivityLogService(session, ActivityModule.LMS)
```

Then record the action next to the change it describes, **before the commit**:

```python
    async def create(self, payload: CourseCreate) -> Course:
        course = await self.repository.create(**payload.model_dump())

        await self.activity.record(
            ActivityAction.CREATE,
            entity=course,
            description=f"Created course {course.title!r}",
            new_values=snapshot(course),
        )
        await self.session.commit()

        return course
```

For an update, record only what changed:

```python
        before = snapshot(course, fields=changes.keys())
        updated = await self.repository.update(course, **changes)
        old_values, new_values = diff(
            before, snapshot(updated, fields=changes.keys())
        )

        if old_values or new_values:
            await self.activity.record(
                ActivityAction.UPDATE,
                entity=updated,
                description=f"Updated course {updated.title!r}",
                old_values=old_values,
                new_values=new_values,
            )
```

`repository.update` mutates the instance in place, so anything the entry needs
from before the write has to be read before the write.

### Recording a refusal

An action that is about to raise cannot log into the caller's session — the
exception ends that transaction and takes the entry with it. Use the detached
writer, which commits on a session of its own:

```python
        await ActivityLogService.record_detached(
            ActivityAction.LOGIN_FAILED,
            module=ActivityModule.AUTH,
            description=f"Failed sign-in: wrong password for {identifier}",
            entity_type="User",
            entity_id=user.id,
        )
        raise UnauthorizedException(INVALID_CREDENTIALS_MESSAGE)
```

## The five design decisions

**One writer.** `ActivityLogService` is the only thing that constructs an
`ActivityLog`, and a test asserts it. Two writers means two vocabularies, and
a trail with two vocabularies cannot be queried.

**Service layer only.** A router knows the request but not what the operation
meant; a service knows what changed, what it changed from, and whether it
worked. Logging from a router also leaves every other caller of that service —
a job, a seeder, another service — unlogged. A test asserts no router imports
the writer.

**The entry and the change commit together.** `record()` adds a row to the
caller's session and flushes it; the service that made the change commits
both. A log entry that survives a rolled-back transaction describes something
that never happened, which is worse than no entry at all. `record_detached` is
the deliberate exception, for refusals.

**Only the diff is stored.** `old_values` and `new_values` hold the fields
that actually changed. A full row copy per edit buries the change and turns
the audit table into a second copy of the database. Large text — a blog post
body — is summarised rather than stored twice.

**Secrets never reach the trail.** `snapshot()` redacts any field whose name
contains `password`, `secret`, `token`, `api_key`, `private_key`,
`credential`, `authorization`, `otp` or `pin`, and settings marked
`is_secret` are redacted by value. Redacted rather than omitted, so a reader
can tell "this was hidden" from "this was empty".

## Reading the trail

```
GET /api/v1/activity-logs?module=blogs&action=delete&status=failure
GET /api/v1/activity-logs/history/Blog/{id}
GET /api/v1/activity-logs/{entry_id}
```

`activity_log.view` is held by Super Admin, Admin and Content Manager;
`activity_log.export` by Super Admin and Admin. There is no
`activity_log.create`, `.update` or `.delete`, and there is not meant to be —
the table has no `updated_at` and no `deleted_at` either. An audit row that
can be edited is not evidence of anything.

## What the tests enforce

`tests/test_activity_logs.py` ends with a policy suite that reads the source
of every module:

| Test | Rule |
| ---- | ---- |
| `test_every_service_that_writes_also_logs` | every public service method that commits also records activity |
| `test_no_router_imports_the_writer` | logging stays in the service layer |
| `test_the_centralized_service_is_the_only_writer` | nothing else constructs an `ActivityLog` |
| `test_every_mandatory_action_has_a_name_in_the_vocabulary` | the required actions are all expressible |
| `test_the_model_captures_every_required_field` | all sixteen captured fields exist |
| `test_the_trail_cannot_be_edited_or_soft_deleted` | append-only is a property of the schema |

A method that genuinely should not log goes in `LOGGING_EXEMPTIONS` with the
reason, next to the one entry already there. That list is a set of decisions,
not a backlog.

## Known gap

Several routers — `roles`, `users`, `permissions`, `settings`, `translations`
— do not yet require authentication. Actions taken through them are logged
in full, but with no `user_id`, `user_name` or `role_name`, because nothing
established who the caller was. Adding the permission guards those modules
already define in their `permissions.py` will fill those columns in with no
change to the logging.
