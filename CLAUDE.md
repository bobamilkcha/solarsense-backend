# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

FYP2 backend for **SolarSense** — an ESP32-based IoT device for hyperlocal solar site
assessment, targeting Malaysian solar B2B installers. It was bootstrapped from an
opinionated FastAPI starter template, so most of the current code (auth, config,
logging, DB session management) is generic starter scaffolding; the SolarSense-specific
domain (device readings, MQTT ingestion) has not been built yet.

**Current status:** only the auth module exists end-to-end (models, service, routes,
tests). The MQTT subscriber and sensor-reading models are drafted elsewhere / not yet
in this repo. Next planned work: Alembic migration for readings, a mock MQTT publish
test, then REST endpoints for dashboard consumption.

### Hardware / domain context (for when the readings feature lands)
- ESP32-WROOM-32U, reading: 5V/1W reference solar cell + 10Ω shunt resistor (voltage;
  current is *derived in the backend* as `voltage / 10.0`, not on-device), SHT31
  (ambient temp/humidity), LSM303DLHC/GY-511 (tilt X/Y/Z, magnetometer heading).
- MQTT topic: `solarsense/{device_id}/readings` — `device_id` lives in the topic path,
  not the payload. Payload: timestamp, cell_voltage, ambient_temp, humidity, tilt_x,
  tilt_y, tilt_z, heading.
- Convention: keep ESP32 firmware "dumb" (raw sensor values only); all derived
  calculations (current, irradiance, etc.) happen in the backend.

## Commands

Tooling is `mise` (task runner) + `uv` (Python package manager). Run `mise tasks` to
list everything.

```bash
mise run init                              # first-time setup: uv sync + install git hooks
mise run dev                               # migrate, then run uvicorn with --reload on :8000
mise run migrate                           # alembic upgrade head (depends on db-up)
mise run generate-migration "message"      # alembic revision --autogenerate -m "message"
mise run db-up / db-down / db-reset        # manage the Postgres container (docker compose)
mise run test                              # uv run pytest (extra args pass through, e.g. `mise run test -k auth`)
mise run test-cov                          # pytest with terminal coverage report
mise run test-cov-html                     # pytest, writes htmlcov/
mise run generate-secret-key               # print a random hex secret for SECRET_KEY
```

Running a single test directly (bypassing mise): `uv run pytest tests/unit/test_security.py::test_name -v`.

Integration tests spin up a real Postgres via `testcontainers` — Docker must be
running. Unit tests do not need Docker or a `.env`.

Linting/formatting/type-checking (also enforced by pre-commit):
```bash
uv run ruff check --fix .
uv run ruff format .
uv run ty check
```

Git hooks (installed by `mise run init`): **pre-commit** runs hygiene checks + ruff +
`ty check`; **pre-push** runs the full pytest suite (needs Docker for integration
tests). Don't bypass these with `--no-verify` unless explicitly asked.

## Architecture

**Layout:** `app/core/` is generic infrastructure (config, DB session, logging,
middleware); `app/modules/<name>/` is a self-contained vertical slice (router → service
→ schemas → exceptions, plus module-specific deps/security) — `auth` is the only module
so far and is the template for future ones (e.g. a future `devices`/`readings` module
should follow the same shape: `router.py`, `service.py`, `schemas.py`,
`exceptions.py`).

**Request flow:** `app/main.py` builds the FastAPI app, registers `LoggingMiddleware`
(assigns/propagates `X-Request-ID`/`X-Trace-ID`, structured-logs every request) and
CORS, then includes each module's router. Domain errors are raised as exceptions (e.g.
`AuthError` subclasses in `app/modules/auth/exceptions.py`) and translated to responses
by a single `@app.exception_handler` registered in `main.py` — routers never do manual
try/except-to-HTTPException mapping; new modules should add their own exception
hierarchy + a matching handler the same way.

**Config (`app/core/config/`):** `AppConfig` (Pydantic Settings, loads `.env`) is a
process-wide singleton (`app_config`, instantiated at import time). `BaseConfig`
enforces that any field listed in a subclass's `_default_secrets` isn't left at
`"changethis"` — but only when `ENVIRONMENT` is not `local`/`testing`, so local dev and
CI don't need real secrets. `ENVIRONMENT` also drives `refresh_cookie_secure` (cookies
are non-Secure outside local/testing so the test client can read them over plain HTTP)
and doc endpoint exposure (`/docs`/`/redoc` disabled in production).

**Database (`app/core/database/database.py`):** `DatabaseSessionManager` wraps a single
async SQLAlchemy engine/sessionmaker as a module-level singleton (`sessionmanager`),
created eagerly at import time from `app_config.postgres_url` (asyncpg driver). Routes
get a session via the `DBSession` dependency alias in `app/core/deps.py`
(`Annotated[AsyncSession, Depends(get_session)]`). The engine is disposed in
`main.py`'s `lifespan` on shutdown.

**Models (`app/models/`):** SQLAlchemy 2.0 declarative style (`Mapped`/`mapped_column`)
on a shared `Base`; `TimestampMixin` adds `created_at`. New models get exported from
`app/models/__init__.py`.

**Auth module (`app/modules/auth/`)** — the reference implementation for how a module
should be structured:
- `security.py`: argon2 password hashing (with `needs_rehash`-triggered rehashing on
  login) and PyJWT-based access/refresh token encode/decode. Login always performs a
  password-verify (real or `dummy_verify()` against a precomputed hash) even when the
  user doesn't exist, to avoid a timing oracle leaking email existence.
- `service.py` (`AuthService`): register/authenticate/issue/rotate/revoke logic.
  Refresh tokens are stored server-side (`RefreshToken` model, keyed by JWT `jti`) so
  they can be revoked; **refresh token rotation reuse detection** — reusing an
  already-rotated (revoked) refresh token revokes the user's *entire* token family,
  not just that token, on the assumption the token was stolen.
- `deps.py`: `CurrentUser` (Bearer-token dependency) and `AuthServiceDep` — the pattern
  to copy for a new module's own dependencies.
- `cookies.py`: refresh token travels as an `httponly` cookie scoped to `/auth`
  (`REFRESH_COOKIE_PATH`); the access token is returned in the JSON body for the client
  to send as a Bearer header.
- `router.py`: only exposes `/auth/{register,login,refresh,logout,me}`; no
  try/except — errors propagate as `AuthError` subclasses to the global handler.

**Logging (`app/core/logging/`):** `LogServiceInterface` (ABC) is the abstraction other
code depends on; `get_log_service()` returns the concrete `StructLogService`
(structlog-backed) implementation. Swappable in principle, but structlog is the only
provider implemented. Configured once at import time in
`providers/structlog/setup.py` (stdlib `logging.config.dictConfig` + structlog
processors); `LOG_LEVEL`/`LOG_HANDLERS` come from `AppConfig`.

## Testing conventions

- `tests/conftest.py` forces `ENVIRONMENT=testing` via `os.environ` *before* any app
  module is imported/collected — this is what makes secret validation and cookie
  `Secure`-flag checks behave correctly under test, and it works because
  `os.environ` takes precedence over `.env` in pydantic-settings.
- `tests/unit/` — no I/O, no Docker.
- `tests/integration/` — real Postgres via `testcontainers`, one container per test
  session (schema created once via `Base.metadata.create_all`, not via Alembic). Each
  test runs inside an outer transaction + a SAVEPOINT that's restarted after every
  `db.commit()` the service layer does, so tests stay isolated without recreating the
  schema per test. The FastAPI `get_session` dependency is overridden per-test so
  routes and the test share one session/transaction. See
  `tests/integration/conftest.py` for the full mechanism if adding new fixtures.
