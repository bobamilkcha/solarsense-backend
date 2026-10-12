# SolarSense Backend — Feature Status

_Last updated: 2026-10-01_

## Working today

### Auth + RBAC (`app/modules/auth/`)
- `POST /auth/register` — creates a new `Company` **and** its first user
  together, as `company_admin`. There's no public "join an existing company"
  endpoint yet (see gaps below).
- `POST /auth/login`, `/auth/refresh`, `/auth/logout`, `GET /auth/me`
- Argon2 password hashing with automatic rehash on login when params go stale
- JWT access tokens (Bearer, returned in JSON body) + refresh tokens (httponly
  cookie scoped to `/auth`)
- Refresh tokens are stored server-side, keyed by JWT `jti`, enabling revocation
- Rotation reuse detection: replaying an already-rotated refresh token revokes the
  user's entire token family
- Login always does a real or dummy password-verify to avoid a timing oracle on
  email existence
- **Roles**: `installer`, `company_admin`, `super_admin` (`UserRole` enum on
  `User.role`). `require_roles(...)` is a FastAPI dependency factory that 403s
  unless the caller has one of the listed roles (`super_admin` always passes)
- Fully tested (unit + integration, including reuse-detection, rotation, and
  role-based access edge cases)

### Company-scoped projects & sites (`app/modules/projects/`)
- `Company` → `Project` → `Site` → `SensorReading` hierarchy — a site now
  belongs to a project, which belongs to a company
- `POST /projects` (company_admin+) — create a project under the caller's company
- `GET /projects` — list projects (company-scoped; `super_admin` sees all)
- `POST /projects/{project_id}/sites` (company_admin+) — register a new device/site
  under a project; rejects duplicate `device_id` (409) and sites under another
  company's project (404, not 403 — avoids leaking project existence)
- Fully tested (RBAC allow/deny per role, 404/409 cases)

### Readings module (`app/modules/readings/`)
- **MQTT ingestion**: `MQTTSubscriber` connects to EMQX Cloud (TLS) on app
  startup, subscribes to `solarsense/+/readings`, and on each message:
  - Parses `device_id` from the topic path
  - Validates the payload against `ReadingPayload` (malformed JSON/payload is
    logged and dropped, not raised)
  - Looks up the `Site` by `device_id`; unknown devices are logged
    (`mqtt_unknown_device`) and dropped, not inserted
  - Derives `cell_current = cell_voltage / 10.0` (shunt resistor) in the backend —
    firmware stays "dumb" per the hardware convention
  - Inserts a `SensorReading` row
- **REST read API** (requires auth, company-scoped — `super_admin` sees every
  company's data, everyone else only their own):
  - `GET /sites` — list sites visible to the caller
  - `GET /sites/{site_id}/readings?limit=&offset=` — paginated readings for a
    site, newest first; 404s if the site doesn't exist *or* belongs to another
    company (same reasoning as the projects 404s above)
- Domain errors go through a `ReadingsError`/`ProjectsError` hierarchy +
  global exception handlers, same pattern as `AuthError`
- Fully tested, and **verified live end-to-end** against the real EMQX Cloud
  broker and local Postgres: register company → create project → create site →
  publish MQTT reading → ingest → insert → authenticated read back out, plus
  the unknown-device-drop and cross-company-isolation paths

### Infrastructure
- `docker-compose.yml`: Postgres (named volume `pgdata`) + MinIO, both reading
  config from `.env`
- Alembic migrations for `users`, `refresh_tokens`, `sites`, `sensor_readings`,
  `companies`, `projects`, plus the `user_role` Postgres enum
  (`migrations/versions/`), applied to the local DB
- Structured logging (`structlog`) with request/trace ID propagation via
  `LoggingMiddleware`
- Global exception-handler pattern: routers never do manual
  try/except-to-HTTPException mapping
- `mise` tasks for dev/test/migrate/db lifecycle; pre-commit (ruff + `ty check`)
  and pre-push (full pytest) git hooks
- Test suite: 71 tests passing, unit (no Docker) + integration (real Postgres via
  testcontainers, transaction-per-test isolation)
- Standalone scripts for manual testing: `scripts/seed_test_site.py` (creates a
  throwaway Company+Project+Site chain), `scripts/mock_publish_reading.py`
  (publish a mock reading to a device's MQTT topic)

## Still being worked on / needs fixing

- **No "join an existing company" flow** — registration always creates a brand
  new company + a `company_admin`. Adding a second user (e.g. an `installer`)
  to an existing company has no API yet — only possible by inserting a `User`
  row directly (as the tests do).
- **No user management endpoints** — no way to list/invite/deactivate users
  within a company, or for a `company_admin` to change another user's role.
- **MinIO is provisioned but unused** — the service runs in `docker-compose.yml`
  and has config values, but no code reads/writes to it (likely intended for
  storing site photos or exports later).
- **No CI pipeline** — tests, lint, and type-checking only run locally via
  pre-commit/pre-push hooks; no `.github/workflows` or equivalent.
- **No pagination metadata** — `GET /sites/{site_id}/readings` takes
  `limit`/`offset` but doesn't return a total count or next-page cursor.
- **MQTT reconnect/resilience untested** — `MQTTSubscriber.connect()` catches a
  failed initial connection, but reconnect behavior after a broker drop (paho's
  automatic reconnect) hasn't been exercised.
- **No rate limiting** — `RATE_LIMITER_ENABLED` exists in config but there's no
  rate-limiting middleware wired up yet.
- **NFR3 (5s MQTT latency) untested** — no timing test; should be fine against
  real hardware but hasn't been measured.
- **NFR6 (satellite benchmark comparison)** — no PVGIS/Solcast/Solargis
  integration; nothing fetches or compares external irradiance data yet.
- **NFR7 (uptime)** — no health-check endpoint, no deployment/hosting setup
  (`gunicorn` is a dependency but unused so far).
- **FR4 (TNB bill parsing)** — no PDF upload or kWh/tariff extraction.
- **FR5 (feasibility report generation)** — no report generation/export
  (PDF/Excel) combining readings + satellite benchmark data.
- **FR6 (site visit checklist)** — no CRUD for this yet.
- **FR8 (raw data export)** — no CSV/JSON export endpoint for readings.
