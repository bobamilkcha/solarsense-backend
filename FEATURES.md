# SolarSense Backend — Feature Status

_Last updated: 2026-10-22_

## Working today

### Auth + RBAC (`app/modules/auth/`)
- `POST /auth/register` — creates a new `Company` **and** its first user
  together, as `company_admin`. Joining an *existing* company is by
  invitation (below).
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

### Invitations & user management (`app/modules/users/`)
- `POST /users/invitations` (company_admin+) — invite an email as `installer`
  or `company_admin` (never `super_admin`). Returns a one-time token, shown
  only once; the frontend builds the invite link from it. No email is sent —
  the admin shares the link. Only a SHA-256 hash of the token is stored.
  Expires after `INVITATION_EXPIRE_DAYS` (default 7); re-inviting the same
  email invalidates the previous link. 409 if the email already has an account
- `GET /users/invitations` / `DELETE /users/invitations/{id}` (company_admin+)
  — list pending invites / revoke one
- `POST /auth/invitations/lookup` — preview an invite (company name, email,
  role) for the accept page; `POST /auth/invitations/accept` — set a password,
  creates the user in the inviting company and logs them in. Token goes in
  the body, not the URL, to keep it out of logs
- `GET /users` — list the caller's company (any role)
- `PATCH /users/{id}` (company_admin+) — change role and/or `is_active`.
  Can't modify yourself (so a company can't lose its last admin by accident);
  only a super_admin can modify a super_admin; another company's user → 404
- **Deactivation** (`users.is_active`): blocked at login (403, only after a
  correct password), refresh, and on every request via `get_current_user`;
  deactivating also revokes all the user's refresh tokens
- Fully tested (full invite flow, single-use/expired/revoked/replaced tokens,
  RBAC, cross-company isolation, deactivation lockout + reactivation)

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
- **Raw data export (FR8)**: `GET /sites/{site_id}/readings/export?format=csv|xlsx&start=&end=`
  (auth + company-scoped) — every reading in the range (start inclusive, end
  exclusive), oldest first, with derived `irradiance_wm2` and timestamps in
  both UTC and Malaysian time. CSV has a UTF-8 BOM so Excel opens it
  cleanly; Excel uses write-only mode for large exports and 422s past
  Excel's ~1M-row sheet limit. Built in memory, not streamed — fine for
  months of 1-minute data, revisit if exports get much bigger
- Domain errors go through a `ReadingsError`/`ProjectsError` hierarchy +
  global exception handlers, same pattern as `AuthError`
- Fully tested, and **verified live end-to-end** against the real EMQX Cloud
  broker and local Postgres: register company → create project → create site →
  publish MQTT reading → ingest → insert → authenticated read back out, plus
  the unknown-device-drop and cross-company-isolation paths

### Satellite benchmark comparison (`app/modules/benchmark/`)
- `GET /sites/{site_id}/benchmark?month=1-12` (auth required, company-scoped
  same as readings) — pairs the site's own average `cell_voltage`/`cell_current`
  for a calendar month against PVGIS's long-term average horizontal irradiation
  for that month at the site's lat/lng
- PVGIS (EU JRC) is free and requires no API key; `app/modules/benchmark/client.py`
  calls its `MRcalc` tool and averages across its historical years (2005-2020 for
  PVGIS-ERA5) per calendar month
- **Irradiance conversion** (`app/modules/readings/irradiance.py`): each
  reading's `cell_current` → W/m^2 via `current / Isc_STC * 1000` (the 10 ohm
  shunt keeps the cell near short-circuit, where current is proportional to
  sunlight). `Isc_STC` is the `REFERENCE_CELL_ISC_A` setting — **currently a
  0.22 A placeholder** for a generic 5V/1W cell, not a measured value.
  Computed on the fly (not stored), so changing the setting re-calibrates
  all past readings. Exposed as `irradiance_wm2` on `GET /sites/{id}/readings`
- Benchmark integrates each Malaysian-time day's readings (trapezoid rule,
  gaps >30 min not bridged) into kWh/m^2/day. Only days with >=90% of
  07:00-19:00 covered count, so a short session doesn't look like a shaded
  site. Returns device vs satellite daily irradiation and their ratio
  (`device_to_satellite_ratio`: ~1.0 = as expected, well below = shading)
- PVGIS failures surface as `502` (`BenchmarkUnavailableError`) rather than
  taking the request down
- Fully tested (PVGIS client unit-tested via `httpx.MockTransport`, no real
  network in tests; service/route tests mock the PVGIS call) and **verified
  live** against the real PVGIS API for a Kuala Lumpur coordinate

### TNB bill parsing & upload (`app/modules/bills/`)
- `POST /sites/{site_id}/bills` (multipart upload, auth + company-scoped) —
  stores the PDF and best-effort-extracts `billing_period_start/end`,
  `kwh_used`, `tariff_category`, `amount_due`, `current_charges` via regex over `pdfplumber`-
  extracted text (`app/modules/bills/parser.py`)
- Parser patterns are **verified against one real TNB bill** (2026 domestic,
  Malay two-page layout): all six fields extract correctly. Only one bill
  layout has been seen — commercial/industrial tariffs or older layouts may
  differ. Every extracted field is nullable by design: an unrecognized layout
  still stores the file with whatever could be extracted, rather than
  rejecting the upload.
- `amount_due` is the bill's total payable (`Jumlah Bil Anda`, includes any
  previous balance); `current_charges` is this period's charges only
  (`Caj Semasa`) — use the latter for cost/savings calculations
- `GET /sites/{site_id}/bills` — list a site's uploaded bills
- `GET /bills/{bill_id}/file` — download the original PDF
- A non-PDF/unreadable upload still gets an `InvalidPDFError` (422); an
  unreadable *layout* on a valid PDF does not — see above
- Fully tested (parser tests against real-bill extracted text;
  service/route tests with storage faked out) and **verified live
  end-to-end** against real local-filesystem storage: upload → stored on
  disk → listed → downloaded byte-identical to the original

### Feasibility report (`app/modules/reports/`)
- `GET /sites/{site_id}/feasibility` (auth + company-scoped) — combines the
  site's bills, PVGIS monthly irradiation, and the device's measured
  shading into: recommended system size (kWp, panel count), cost, annual
  production, bill before/after per month, annual savings, simple payback,
  and net savings over 25 years (0.5%/yr degradation, flat tariffs)
- **TNB domestic tariff calculator** (`tariff.py`) for the July 2025 tariff,
  checked line by line against a real bill: energy (incl. >1,500 kWh tier),
  capacity, network, retail charge, AFA, 8% service tax above 600 kWh, KWTBB.
  Non-domestic bills fall back to a flat RM/kWh rate derived from the bills'
  `current_charges`
- Shading factor = average of device/satellite ratio over complete days
  (capped at 1.0); with no complete days, satellite-only (factor 1.0)
- Overridable query params with defaults: `system_kwp` (omit = sized to cover
  annual usage), `performance_ratio` 0.8, `self_consumption_ratio` 0.6,
  `export_rate_rm_per_kwh` 0 (conservative), `cost_per_kwp_rm` 4000,
  `panel_wp` 550, `afa_rate_rm_per_kwh` 0
- 422 if the site has no bill with kWh; 502 if PVGIS is down
- `GET /sites/{site_id}/feasibility/xlsx` (same query params) — Excel
  workbook (`excel.py`, openpyxl): Summary, Monthly (with live `SUM` totals),
  and Assumptions sheets; values stored as numbers with number formats
- **PDF export is left to the frontend** (e.g. `@react-pdf/renderer`), built
  from the JSON endpoint — the response includes site name/coordinates for it
- Fully tested (tariff + maths unit tests, service/route integration tests
  with PVGIS mocked)

### Infrastructure
- `docker-compose.yml`: Postgres (named volume `pgdata`). MinIO was removed —
  see gaps below
- Object storage (`app/core/storage/object_storage.py`) is local-filesystem
  based (under `OBJECT_STORAGE_DIR`, default `./data/object_storage`), behind
  an S3-shaped `ensure_bucket`/`upload_bytes`/`get_bytes` interface so
  swapping in a real object store later doesn't require touching callers
- Alembic migrations for `users`, `refresh_tokens`, `sites`, `sensor_readings`,
  `companies`, `projects`, `tnb_bills` (+ `current_charges` column),
  `invitations` (+ `users.is_active`), plus the `user_role` Postgres enum
  (`migrations/versions/`), applied to the local DB
- Structured logging (`structlog`) with request/trace ID propagation via
  `LoggingMiddleware`
- Global exception-handler pattern: routers never do manual
  try/except-to-HTTPException mapping
- `mise` tasks for dev/test/migrate/db lifecycle; pre-commit (ruff + `ty check`)
  and pre-push (full pytest) git hooks
- Test suite: 165 tests passing, unit (no Docker) + integration (real Postgres via
  testcontainers, transaction-per-test isolation)
- Standalone scripts for manual testing: `scripts/seed_test_site.py` (creates a
  throwaway Company+Project+Site chain), `scripts/mock_publish_reading.py`
  (publish a mock reading to a device's MQTT topic)

## Still being worked on / needs fixing

- **Invited users' emails aren't verified** — invites are shared by the
  admin, not emailed, so accepting one doesn't prove email ownership
  (`email_verified` stays false; login doesn't check it yet either).
- **MinIO is gone, not just unused** — its container image is no longer
  freely pullable from Docker Hub or Quay.io as of 2026-10-21 (every tag
  tried, including `latest`, is denied — this looks like a 2025 licensing
  change, not a transient issue). Object storage is local-filesystem for now
  (see above); revisit if you get access to a real object store (a MinIO
  subscription, AWS S3, or a free alternative like Garage/SeaweedFS) before
  deploying anywhere that isn't this one machine's disk.
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
- **Reference cell calibration is a placeholder** — `REFERENCE_CELL_ISC_A`
  defaults to an estimated 0.22 A. Replace with the cell's datasheet Isc, or
  better, calibrate against a pyranometer/known-good reference. Temperature
  effect on Isc (~+0.05%/C) is ignored.
- **Benchmark assumes the cell lies flat** — PVGIS figures are for a
  horizontal surface; readings taken with the cell tilted aren't corrected
  (tilt is recorded but not used yet).
- **No caching on the benchmark endpoint** — every call hits PVGIS live; fine
  for an FYP demo, but would need caching (PVGIS data is static per
  coordinate+month) before any real traffic.
- **NFR7 (uptime)** — no health-check endpoint, no deployment/hosting setup
  (`gunicorn` is a dependency but unused so far).
- **FR4 (TNB bill parsing)** — validated on a single domestic bill only;
  needs more sample bills (other tariffs, older layouts) to harden.
- **FR5 (feasibility report) assumptions need review** — JSON + Excel export
  done (PDF is the frontend's job). Assumption defaults (cost/kWp,
  self-consumption 60%, zero export credit) are estimates; the Solar ATAP
  export rate and the Energy Efficiency Incentive rebate (usage <=1,000 kWh)
  aren't modelled, so savings are on the conservative side. Consumption is
  assumed flat across the year (average of uploaded bills).
- **FR6 (site visit checklist)** — no CRUD for this yet.
