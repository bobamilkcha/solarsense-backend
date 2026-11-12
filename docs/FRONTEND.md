# SolarSense backend: frontend integration guide

Read this together with **`openapi.json`** (same folder). That file is the exact
contract: every endpoint, parameter, request body and response shape. This
guide covers what the spec can't express: auth mechanics, error conventions,
units, flows and known gaps. Prefer generating TypeScript types from the spec
(e.g. `npx openapi-typescript docs/openapi.json -o src/api/schema.d.ts`) over
hand-writing them.

The backend regenerates the spec with `mise run export-openapi`. If something
here disagrees with `openapi.json`, the spec wins.

## What the product is

SolarSense helps Malaysian solar installers (B2B) assess a customer's site
before installing panels. An ESP32 device with a reference solar cell is left
on the roof and sends readings over MQTT. The backend combines those readings
with satellite sunlight data (PVGIS) and the customer's uploaded TNB electricity
bills to produce a feasibility report: system size, cost, savings, payback.

Data hierarchy: **Company → Project → Site → (Readings, Bills, Visits)**. A
Site is one physical location with one device (`device_id`).

## Local setup

- API base URL: `http://localhost:8000` (backend runs with `mise run dev`)
- Interactive docs: `http://localhost:8000/docs` (disabled in production)
- CORS: the backend allows the origins in its `BACKEND_CORS_ORIGINS` env var,
  with credentials enabled. Ask for the frontend dev origin to be added
  explicitly (e.g. `["http://localhost:5173"]`).

## Authentication

Two tokens:

| Token | Where it lives | Lifetime | How to send it |
|---|---|---|---|
| Access token (JWT) | JSON body of login/register/refresh/accept-invite responses | 15 min | `Authorization: Bearer <token>` header on every API call |
| Refresh token | `httponly` cookie `refresh_token`, path `/auth`, `SameSite=Lax` | 30 days | Sent automatically by the browser to `/auth/*` |

Rules:

- **Keep the access token in memory** (e.g. app state), not localStorage. On
  page load, call `POST /auth/refresh` to get a new one from the cookie. A 401
  there means the user is logged out.
- **Every request to `/auth/*` must use `credentials: "include"`** (fetch) or
  `withCredentials: true` (axios), or the cookie won't be sent or stored.
- On a **401 from any other endpoint**, call `POST /auth/refresh` once, then
  retry the original request with the new access token.
- **Never run two refreshes at the same time.** Refresh tokens rotate: each
  refresh invalidates the old one. If the same old token is used twice, the
  backend assumes it was stolen and **revokes every session for that user**,
  which logs them out. Use a single shared in-flight refresh promise that all
  callers await.
- `POST /auth/logout` revokes the refresh token and clears the cookie. Then
  drop the access token from memory.
- `GET /auth/me` returns the current user, including `role` and `company_id`.

Production note: if the frontend and API end up on different sites (different
registrable domains), the cookie will need `SameSite=None` and `Secure`. That's
a backend config change; flag it when deploying.

### Roles

`installer`, `company_admin` and `super_admin` (platform-wide; can see every
company's data). These endpoints need `company_admin` or higher (others get
403):

- `POST /projects`, `POST /projects/{id}/sites`
- `PATCH`/`DELETE /projects/{id}`, `PATCH`/`DELETE /sites/{id}`
- `POST /users/invitations`, `GET /users/invitations`, `DELETE /users/invitations/{id}`
- `PATCH /users/{id}`

Everything else is open to any logged-in member of the company. Use
`/auth/me`'s `role` to hide admin-only UI, but still handle 403.

## Errors

All domain errors are `{"detail": "human-readable message"}`. Request
validation errors (bad body or params) are FastAPI's 422 shape, where `detail`
is a **list**: `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}`.
Handle both shapes.

| Status | Meaning |
|---|---|
| 401 | Missing, invalid or expired access token → refresh and retry. On `/auth/login`: wrong email or password. On `/auth/refresh`: logged out. |
| 403 | Role not allowed. On `/auth/login`: the account is deactivated (password was correct). |
| 404 | Not found **or belongs to another company**. The API never reveals that another company's resource exists, so treat both the same. |
| 409 | Conflict: duplicate email or `device_id` (device already paired to another site), completing a visit with pending items, editing a completed visit, admin editing themselves. |
| 422 | Validation error, or a domain precondition (e.g. a feasibility report with no bills uploaded). Show `detail`. |
| 502 | Satellite data (PVGIS) is unavailable. Benchmark and feasibility only; offer a retry. |

## Times and units

- All timestamps are ISO 8601 with a timezone, stored in UTC. **Display in
  `Asia/Kuala_Lumpur`** (UTC+8). Send timestamps with an offset.
- Money is RM (Malaysian ringgit). Energy is kWh.

Reading fields (`GET /sites/{id}/readings`):

| Field | Unit / meaning |
|---|---|
| `cell_voltage` | V, measured across the 10 Ω shunt |
| `cell_current` | A, = voltage / 10 (computed by the backend) |
| `irradiance_wm2` | W/m², sunlight strength. 1000 is full sun; 0 is night. **The main number to chart.** |
| `ambient_temp` | °C. `null` if the device's temperature sensor failed |
| `humidity` | %. `null` if the sensor failed |
| `roll`, `pitch` | degrees, device orientation from the accelerometer. `null` if the sensor failed |
| `tilt_deg` | degrees from horizontal, combining roll and pitch (computed by the backend). 0 is flat. **Use this as the panel tilt angle.** `null` when roll or pitch is `null` |
| `heading` | degrees, magnetometer compass heading. `null` if the sensor failed |
| `rssi` | dBm, device Wi-Fi signal (e.g. -59). Closer to 0 is stronger; below about -80 is weak. May be `null` on older readings |
| `device_timestamp` | when the device took the reading (server receive time if the device's clock wasn't synced yet) |

Irradiance calibration is still a placeholder constant, so treat absolute
values as approximate.

## Feature guide

### Projects and sites

- `GET /projects`, `POST /projects` (admin)
- `POST /projects/{project_id}/sites` (admin): needs `name`, `location_lat`,
  `location_lng`. `device_id` is optional (409 if another site has it); prefer
  creating the site without one and pairing it as below.
- `GET /sites`: all sites the user can see. Each has `project_id`; group by it
  client-side. `device_id` is `null` when no device is paired.
- `PATCH /projects/{id}` (admin): send only the fields to change, from `name`
  and `description`. `"description": null` clears it; `name` can't be null or
  empty (422). Returns the updated project.
- `PATCH /sites/{id}` (admin): send only the fields to change, from `name`,
  `location_lat` and `location_lng` (none may be null). Returns the updated
  site. The benchmark and feasibility report always use the current location,
  so fixing a wrong location also changes results for past readings. To
  change the device, use the pairing endpoints below, not this.
- `DELETE /projects/{id}` and `DELETE /sites/{id}` (admin): 204. **Permanent,
  no undo**: deleting a site also deletes its readings, bills (with the
  PDFs) and visits; deleting a project does that for every site in it. The
  site's device becomes unpaired and can be paired elsewhere. Ask the user to
  confirm (e.g. type the name) before calling.
- Another company's project or site gives 404 on all of these.

### Pairing a device (admin)

Each device has a sticker with a 4-character code (the end of its ID, e.g.
`FE68`). Users never type the full ID.

1. Ask the user to switch the device on and wait for Wi-Fi (about 30 s).
2. Poll `GET /devices/unpaired` every few seconds. It lists devices that have
   published in the last 10 minutes (`?within_minutes=` to change) and aren't
   on any site, newest first. Show each as `short_code`, "seen N s ago" (from
   `last_seen_at`) and `signal` (`good` / `fair` / `weak` / `unknown`).
   Ask the user to match the code against the sticker.
3. `PUT /sites/{id}/device` with `{"device_id": "<device_id from the list>"}`.
   Replaces the site's current device, if any. 409 if the device is on another
   site.
4. `DELETE /sites/{id}/device` unpairs (e.g. when the survey ends) so the
   device can be moved. The site keeps its past readings.

An empty list means no unpaired device is online: check power and Wi-Fi.
Readings sent before pairing are not stored.

### Device settings: remote config (admin)

A paired device reports its status over MQTT and accepts a new publish
interval remotely. Both endpoints are admin-only and keyed by the **device ID**
(the site's `device_id`). They return 404 if the device isn't paired to one of
your company's sites (or hasn't been heard from yet).

- `GET /devices/{device_id}/config` returns
  `{device_id, desired: {publish_interval_s, requested_at}, reported: {online, fw, publish_interval_s, last_seen_at}, synced}`.
  - `reported` is what the device says it is **actually using**: show
    `online`, `fw` and `last_seen_at` as the status line. When it goes offline
    `fw` and `publish_interval_s` keep their last known values.
  - `desired` is what an admin last asked for; `publish_interval_s` is `null`
    if nobody ever has.
  - `synced` is `true` when nothing is pending (no request, or the device has
    reported the requested interval). Show **Pending…** while it's `false` and
    **Applied** once it's `true`.
- `PUT /devices/{device_id}/config` with `{"publish_interval_s": 30}`. It must
  be an integer from 5 to 3600 (422 otherwise). Returns the same shape as GET,
  so `synced` is `false` right after saving. The change is retained on the
  broker: an offline device picks it up when it reconnects, so Pending can last
  a while. 503 means the backend couldn't reach the MQTT broker and nothing was
  saved.
- While pending, poll `GET` every few seconds and stop when `synced` is `true`.
- `last_seen_at` is the last time the device published anything (a reading or
  an online status), not a heartbeat; a device that is `online` but hasn't been
  seen for several publish intervals is likely stuck.

### Changing a device (admin)

Devices pair to **sites**, not projects. To change the device "on a project",
change it on one of the project's sites. There's no separate endpoint: use the
same `PUT /sites/{id}/device` as pairing.

1. Find the site: `GET /sites`, filtered by `project_id`. If the project has
   only one site, a "Change device" button on the project page can skip
   straight to it.
2. Open the pairing dialog (`GET /devices/unpaired`) and let the user pick
   the new device.
3. `PUT /sites/{id}/device` with the new `device_id`.

What happens:

- The old device is released at once and appears in `GET /devices/unpaired`,
  ready for another site.
- Readings belong to the site, not the device: past readings stay, and the
  new device's readings join the same history.
- 409 means the new device is paired to another site. Show "Unpair it from
  that site first" (`DELETE /sites/{other_id}/device`).
- Admin only; installers get 403, so hide the action for them.

### Live readings

- `GET /sites/{id}/readings?limit=&offset=`: newest first, `limit` ≤ 1000. No
  total count is returned.
- There's no websocket or push. **Poll** for a live view (e.g. every 30–60 s;
  match it to the firmware's send interval).
- `GET /sites/{id}/readings/export?format=csv|xlsx&start=&end=` downloads a
  file (start inclusive, end exclusive). Send it with the Bearer header and
  save the blob; a plain `<a href>` won't carry the token.

### Satellite benchmark

`GET /sites/{id}/benchmark?month=1-12` (defaults to the current month)
compares the device's measurements with satellite expectations for that month:

- `device_avg_daily_irradiation_kwh_m2` vs `satellite_avg_daily_irradiation_kwh_m2`
- `device_to_satellite_ratio`: **~1.0 means the site gets the expected
  sunlight; well below 1.0 suggests shading.** This is the headline number.
- `device_complete_days`: only full days of data count (≥ 90% of 07:00–19:00
  covered). If it's 0, the device hasn't run a full day yet and the
  device-side fields are `null`. Show "collecting data" instead of a ratio.

### TNB bills

- `POST /sites/{id}/bills`: multipart upload, field name **`file`** (PDF). The
  backend reads the fields from the PDF. **Every parsed field can be `null`**
  if the layout isn't recognised; the upload still succeeds. Show what was
  found, and treat missing values as "couldn't read".
- `GET /sites/{id}/bills` lists them; `GET /bills/{id}/file` downloads the
  original PDF (Bearer header, blob).
- `amount_due` is the total payable (includes any previous unpaid balance).
  `current_charges` is this month's charges only.

### Feasibility report

`GET /sites/{id}/feasibility` is the main output of the product. Requires at
least one bill with kWh (otherwise 422). Optional query params let the user
tweak assumptions:

| Param | Default | Meaning |
|---|---|---|
| `system_kwp` | auto-sized to cover yearly usage | system size |
| `cost_per_kwp_rm` | 4000 | installed cost |
| `self_consumption_ratio` | 0.6 | share of solar output used on-site |
| `export_rate_rm_per_kwh` | 0 | credit for power exported to the grid |
| `performance_ratio` | 0.8 | system losses |
| `panel_wp` | 550 | panel size in watts |
| `afa_rate_rm_per_kwh` | 0 | TNB monthly fuel adjustment |

Response highlights:

- Headline: `system_kwp`, `panel_count`, `system_cost_rm`, `annual_savings_rm`,
  `payback_years` (`null` if there are no savings), `lifetime_net_savings_rm`
- `avg_monthly_bill_before_rm` / `avg_monthly_bill_after_rm`
- `months[]`: 12 rows of production, bill before/after and savings. Good for a
  bar chart of the bill with and without solar.
- `shading.source`: `"device"` (measured) or `"satellite_only"` (no full
  device days yet, so no shading adjustment). Say which one in the UI.
- `assumptions`: the values actually used (echoes the auto-sized `system_kwp`)
- `site_name`, `location_lat/lng`: for report headers

**PDF export is the frontend's job** (e.g. `@react-pdf/renderer`), built from
this JSON. Include a line saying the figures are estimates, not a quotation.
`GET /sites/{id}/feasibility/xlsx` (same params) downloads an Excel version
from the backend.

### Site visit checklist

- `POST /sites/{id}/visits` starts a visit with a 20-item default checklist
  (`{"use_default_checklist": false}` for an empty one). Optional
  `visited_at` and `notes`.
- `GET /sites/{id}/visits` lists visits with `progress` counts (no items).
  `GET /visits/{id}` returns a visit with `items`, ordered by `position`;
  group them by `category`.
- Item status: `pending` / `ok` / `issue` / `not_applicable`, plus an optional
  free-text `value` (e.g. "45 m²") and `notes`. Update with
  `PATCH /visits/{id}/items/{item_id}`; add or remove with `POST` / `DELETE`.
- `PATCH /visits/{id}` with `{"status": "completed"}` returns 409 while any
  item is `pending`. A completed visit returns 409 on every edit until it's
  reopened with `{"status": "in_progress"}`.
- Any company member can run visits. Installers are the main users, so design
  for mobile use on a rooftop.

### Team and invitations

1. An admin calls `POST /users/invitations` with `{"email", "role"}`
   (`installer` or `company_admin`). The response includes **`token`, shown
   only once**.
2. The frontend shows a link to copy: `<frontend>/accept-invite?token=<token>`.
   The backend doesn't send email; the admin shares the link.
3. The accept page calls `POST /auth/invitations/lookup` with `{"token"}` to
   show the company name, email and role, then
   `POST /auth/invitations/accept` with `{token, password (min 8),
   first_name?, last_name?}`. This logs the user in (same response as login,
   sets the cookie; use `credentials: "include"`).

Invites expire after 7 days and are single-use. Re-inviting an email
invalidates the old link. An invalid token returns 400.

- `GET /users`: team list (any role)
- `PATCH /users/{id}` (admin): change `role` or `is_active`. Deactivating
  logs the user out everywhere. Admins can't edit themselves (409), so hide
  those controls on their own row.
- `GET /users/invitations` / `DELETE /users/invitations/{id}`: pending invites

## Suggested screens

1. Login / register (register creates a new company plus its admin)
2. Accept invite (`/accept-invite?token=`)
3. Projects → sites list (admins can create, edit and delete)
4. Site dashboard: live irradiance chart (poll), latest temperature and
   humidity, benchmark ratio, bills list and upload, visits list
5. Visit checklist (mobile-first)
6. Feasibility report: adjustable assumptions, monthly bill chart, PDF and
   Excel download
7. Team management (admin): members, roles, invites

## Not available yet (don't build UI that depends on these)

- No `GET` for a single project or site. Use the list endpoints and filter.
- No editing or deleting bills.
- No readings aggregation (hourly or daily averages). Charts must use raw
  readings (max 1000 per request).
- No pagination totals on the readings list.
- No websocket or live push. Poll instead.
- No photo uploads on visits.
- No password reset or email verification flow.
