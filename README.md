# fastapi-starter

Opinionated FastAPI backend starter: async SQLAlchemy + asyncpg, Alembic
migrations, Pydantic v2 settings, JWT auth (access + rotating refresh tokens,
argon2 hashing), structlog logging, and a full test suite (pytest +
testcontainers). Tooling via `uv` and `mise`; linting/formatting with `ruff`,
type checking with `ty`, enforced by pre-commit and pre-push git hooks.

## Quick start

Prereqs: [`mise`](https://mise.jdx.dev), [`uv`](https://docs.astral.sh/uv),
and Docker (for the database and integration tests).

```bash
# 1. Install the pinned Python, sync deps, and install git hooks
mise run init

# 2. Configure environment
cp .env.example .env
mise run generate-secret-key   # paste into .env

# 3. Run migrations and start the dev server
mise run dev                   # http://localhost:8000
```

## Git hooks

`mise run init` installs both hook types via the pre-commit framework:

| Stage          | Runs                                                          |
| -------------- | ------------------------------------------------------------ |
| **pre-commit** | hygiene checks, `ruff check --fix`, `ruff format`, `ty check` |
| **pre-push**   | full `pytest` suite (unit + integration; needs Docker)        |

## Common tasks

```bash
mise tasks                 # list everything
mise run test              # run the test suite
mise run test-cov          # tests with coverage report
mise run migrate           # apply migrations
mise run generate-migration "message"   # autogenerate a migration
mise run db-up / db-down / db-reset      # manage the database container
```
