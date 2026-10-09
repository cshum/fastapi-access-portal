# Access Portal — FastAPI service

A self-service access-request service: members request membership of a group, an
approver grants or refuses it, and approval creates the membership. It stands in
for the class of internal tooling that replaces an email-and-SharePoint process.

**Why this exists:** I built it to learn FastAPI properly rather than read about
it. I had shipped auth, RBAC and onboarding flows in NestJS and Go, and wanted to
know where FastAPI's model actually differs — dependency injection, validation,
the test seam, and where async helps versus hurts. Every design decision below is
one I can explain and defend.

## Running it

```bash
uv venv --python 3.10 .venv
uv pip install --python .venv/bin/python -r requirements.txt

# Postgres (either works)
docker compose up -d db
# or a local server:
#   createdb portal && createuser portal

cp .env.example .env          # adjust DATABASE_URL if needed
.venv/bin/python -m uvicorn app.main:app --reload
```

Interactive docs: <http://127.0.0.1:8000/docs> (generated, not written by hand).

```bash
pytest -q                     # 7 tests, no database service required
```

## The flow

```
POST /auth/register                     first user becomes approver
POST /auth/token                        OAuth2 password flow -> JWT
GET  /auth/me

POST /admin/groups                      approver only
GET  /admin/groups

POST /requests                          member asks for a group
GET  /requests                          own requests

GET  /admin/requests?status_filter=     approver queue
POST /admin/requests/{id}/approve       -> creates Membership
POST /admin/requests/{id}/reject
GET  /admin/users/{id}/memberships
```

## NestJS -> FastAPI, the mapping I had to internalise

| NestJS | FastAPI | Where in this repo |
|---|---|---|
| `@Injectable()` provider | a plain function you list in `Depends()` | `app/db.py::get_db` |
| constructor injection | parameter default `x: Annotated[T, Depends(f)]` | every route |
| `@Controller` / `@Get` | `APIRouter(prefix=...)` / `@router.get` | `app/routers/*` |
| class-validator DTO | Pydantic model | `app/schemas.py` |
| `CanActivate` guard | a dependency that raises | `security.py::require_approver` |
| `@nestjs/swagger` decorators | nothing — OpenAPI is derived from the Pydantic types | `app/schemas.py` |
| `passport-jwt` strategy | `OAuth2PasswordBearer` + `jwt.decode` | `security.py` |
| Prisma / TypeORM | SQLAlchemy 2.0 (`Mapped[]`, `mapped_column`) | `app/models.py` |
| request-scoped provider | generator dependency (`yield`, then `finally`) | `app/db.py` |
| `Test.createTestingModule().overrideProvider()` | `app.dependency_overrides[get_db]` | `tests/conftest.py` |

The one that surprised me: **there is no DI container.** NestJS resolves a graph
at startup and gives you a container to reason about; FastAPI resolves per request
from the function signatures, and the "container" is just the call graph of your
own `Depends` functions. It is simpler, and there is no module wiring to trace —
but you also cannot ask the framework "who provides X".

## Questions this code answers

**Why is `get_db` a generator?**
Because the session must close *after* the response is sent. FastAPI runs the code
after `yield` as teardown, which is the same lifecycle a NestJS request-scoped
provider gets from the framework. Returning a session instead would leak
connections.

**How is authorisation done — middleware, decorators, guards?**
A dependency that raises. `require_approver` depends on `get_current_user`, which
depends on the token scheme and the DB session. FastAPI resolves the whole chain
per request, so an endpoint declaring `ApproverUser` cannot be reached without a
valid token *and* the approver role. It composes into the type signature, which
means an unauthorised route is visible in the code rather than in a decorator
string.

**Where does validation happen, and what status code?**
In the Pydantic model, before the handler runs — a body failing `min_length=8` on
`password` returns **422**, not 400, and the handler is never entered. In NestJS
the equivalent (a `ValidationPipe` plus a DTO) is opt-in and configured globally;
in FastAPI it is the default because the type *is* the schema.

**Sync or async handlers?**
All handlers here are plain `def`, so FastAPI runs them in a threadpool. That is
the right default for blocking SQLAlchemy calls — making them `async def` without
an async driver would block the event loop instead of offloading it, which is
slower under load. `async def` earns its place for genuinely non-blocking I/O
(an async HTTP client, an async DB driver such as `asyncpg`). The distinction is
not "async is faster"; it is "do not block the loop".

**Why is approval idempotent?**
Two guards. The handler refuses a request that is not `pending` (409), and
`memberships` carries a `UniqueConstraint(user_id, group_id)` so a duplicate row
is impossible at the database level as well. The check in Python gives a clean
error; the constraint is what makes it true under concurrency, where two
simultaneous approvals would both pass a Python-level check.

**How do you test without a database?**
`app.dependency_overrides[get_db] = override_get_db` swaps the session factory for
a per-test SQLite file. Nothing in the application changes — the seam exists
because the session was a dependency rather than a module-level import. This is
the single biggest practical payoff of `Depends`.

**Why does the first registered user become an approver?**
Bootstrap. Without it the service needs an out-of-band seed before anyone can
approve anything. It is a deliberate simplification for a learning project, and
the first thing I would remove in production (see below).

## What I would change for production

- **Migrations.** `Base.metadata.create_all` on startup is convenient and wrong —
  it cannot alter an existing schema. Alembic is the equivalent of Prisma
  Migrate, and the first thing I would add.
- **The bootstrap rule.** First-user-is-approver is fine locally and unacceptable
  in a real deployment; it needs an admin CLI or a seeded role.
- **Real group assignment.** `Group` here is a local table. Against Active
  Directory it becomes a Microsoft Graph call, with the local table as an
  outbox so a Graph failure cannot lose an approved request.
- **Refresh tokens and revocation.** A single 60-minute access token with no
  refresh and no deny-list.
- **An audit log.** `decided_by_id` and `decided_at` cover the approval itself;
  a real access-control system wants an append-only record of every state change.
- **Rate limiting on `/auth/token`.** Nothing currently slows a password-guessing
  loop.

## Layout

```
app/
  config.py     settings via pydantic-settings (env-driven, override in tests)
  db.py         engine, Base, get_db dependency
  models.py     SQLAlchemy: User, Group, AccessRequest, Membership
  schemas.py    Pydantic request/response models
  security.py   hashing, JWT, current-user and approver dependencies
  routers/      auth.py, requests.py, admin.py
  main.py       app, lifespan, router registration
tests/          conftest.py (the test seam), test_flow.py (end-to-end)
```
