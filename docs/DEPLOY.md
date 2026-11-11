# Deploying SolarSense

# Free option: run on your own PC behind an ngrok tunnel

No server and no money. The same stack runs in Docker on your PC and a free
ngrok tunnel gives it a public HTTPS address (the tunnel provides the HTTPS,
so Caddy serves plain HTTP here). The rest of this file describes the paid
VPS route and is not needed for this mode.

1. **ngrok account** (free, no card): https://dashboard.ngrok.com. Copy your
   *authtoken*, and claim your free *static domain* (Domains page), e.g.
   `something.ngrok-free.dev`.
2. **Config.** `.env.prod` already exists (gitignored, with generated secrets and
   your EMQX settings). Fill in the three lines:
   `DOMAIN=` and `NGROK_DOMAIN=` (both the static domain, no `https://`) and
   `NGROK_AUTHTOKEN=`.
3. **Frontend build:** `./deploy/build_frontend.sh` (builds `../solarsense-frontend`
   with `VITE_API_URL=/api` into `web/`). Re-run it after any frontend change.
4. **Start:** `mise run local-up`. Stop with `mise run local-down` (keeps data).
   Open `http://localhost:8080` on the PC, or `https://<your-ngrok-domain>` from anywhere.
   `https://<your-ngrok-domain>/api/health` should say `"mqtt":true`.
5. **Stop the dev server** (`mise run dev`) for the week. It subscribes to the same
   device topics and would just compete for CPU and confuse the data. The
   production stack has its **own empty database**, so register your company
   and pair the device again in the UI.
6. **Keep the PC working for 7 days:**
   - Never sleep or hibernate while plugged in. In an admin PowerShell:
     `powercfg /change standby-timeout-ac 0` and `powercfg /change hibernate-timeout-ac 0`.
     Laptop: set the lid-close action to "Do nothing" and keep it plugged in.
   - Docker Desktop: Settings > General > "Start Docker Desktop when you sign in".
     The containers use `restart: unless-stopped`, so they return after a reboot
     once Docker is up (you must be signed in to Windows).
   - Pause Windows Update restarts for the week (Settings > Windows Update > Pause).
   - Stay on a stable network. Readings are lost whenever the PC is asleep, offline
     or restarting: the device sends at QoS 0 and the broker does not keep them.
7. **Monitor + backup:** an UptimeRobot keyword monitor on
   `https://<ngrok-domain>/api/health` for `"mqtt":true` (free), and
   `mise run local-backup` whenever you like (keeps 7 dumps in `backups/`).

ngrok free-tier notes: the first browser visit may show an ngrok "visit site"
interstitial (click through once), and free accounts have bandwidth and request
limits, which are plenty for this app. Check their current terms.

---

# Paid option: one VPS with a free DuckDNS domain

Everything runs on one small Linux VPS (about US$5/month, e.g. Hetzner or
DigitalOcean, Ubuntu 24.04, 1 GB RAM is enough) with Docker Compose:

- `caddy`: HTTPS certificate, serves the built frontend at `/`, proxies `/api/*` to the API
- `api`: FastAPI plus the MQTT subscriber (exactly **one** worker, see below)
- `db`: Postgres, not reachable from the internet

The ESP32 talks only to EMQX Cloud, so the server needs just ports 80 and 443.
Frontend and API share one origin (`https://<name>.duckdns.org`), so there is
no CORS and the refresh cookie works (it is scoped to `/api/auth`).

## 1. One-time setup

1. **Domain.** Sign in at https://www.duckdns.org, create a subdomain
   (e.g. `solarsense-fyp`), and set its IP to your VPS's public IP.
2. **VPS.** Create the server, open ports **22, 80, 443** in its firewall.
   Install Docker: `curl -fsSL https://get.docker.com | sh`, then
   `sudo usermod -aG docker $USER` and log in again.
3. **Code.** Put this repo on the server (`git clone ...`, or `rsync`).
4. **Config.** In the repo folder: `cp deploy/.env.prod.example .env`, then edit it:
   - `DOMAIN=solarsense-fyp.duckdns.org`
   - `SECRET_KEY`: `python3 -c "import secrets; print(secrets.token_hex(32))"`
   - `DATABASE_PASSWORD`: a long random password
   - `MQTT_*`: your EMQX Cloud host, username and password
   - The app refuses to start in production while a secret is still `changethis`.
5. **Frontend build** (on your own machine, in the frontend repo):
   ```bash
   VITE_API_URL=/api npm run build
   rsync -av --delete dist/ <user>@<server-ip>:~/solarsense-backend/web/
   ```
6. **Start:** `docker compose -f docker-compose.prod.yml up -d --build`
   The first start takes a couple of minutes (image build, certificate).
   Migrations run automatically every time the API container starts.

## 2. Check it works

- `https://<domain>/` shows the login page.
- `https://<domain>/api/health` returns `{"status":"ok","database":true,"mqtt":true}`.
  `mqtt:false` means the API cannot reach EMQX: check the `MQTT_*` values and
  `docker compose -f docker-compose.prod.yml logs api`. It retries by itself.
- Register your company in the UI, create a project, pair your device. Readings
  should appear within one publish interval.

## 3. Keeping it running for the week

- All containers use `restart: unless-stopped`, so they come back after a crash
  or a server reboot. The API container also has a health check.
- **Uptime monitor** (free): UptimeRobot, a keyword monitor on
  `https://<domain>/api/health` for the text `"mqtt":true`. You get an alert if
  the database or the broker connection drops.
- **Backups:** `crontab -e`, add
  `0 3 * * * cd ~/solarsense-backend && ./deploy/backup.sh`
  (keeps the last 7 nightly dumps in `backups/`; copy them off the server too).
- **Logs:** `docker compose -f docker-compose.prod.yml logs -f api`
- **Update after a code change:** pull or rsync, then
  `docker compose -f docker-compose.prod.yml up -d --build`. Re-run the
  `rsync` in step 5 if the frontend changed.
- **Restore a dump:**
  `gunzip -c backups/<file>.sql.gz | docker compose -f docker-compose.prod.yml exec -T db psql -U postgres solarsense`
  (use your `DATABASE_USER` / `DATABASE_NAME`).

## 4. Network-drop check (do once before leaving it unattended)

This confirms ingestion recovers by itself after a network drop, without
restarting the backend. The automated version is
`uv run pytest tests/integration/test_mqtt_reconnect.py` (needs Docker).

1. With the device publishing, follow the API logs:
   `docker compose -f docker-compose.prod.yml logs -f api | grep mqtt_`
   Startup should show `mqtt_connected` and then `mqtt_subscribed`.
2. Note the "last reading" time on the dashboard and confirm it keeps updating.
3. Cut the server's network for about 2 minutes (on a laptop, including one
   running WSL, turn Wi-Fi off or unplug the cable). Leave the device online.
4. Within about 45 s you should see `mqtt_connection_lost` (with a reason). While
   the network is down, `/api/health` shows `"mqtt":false` (if you can reach it
   at all) and there may be repeated `mqtt_connect_failed` lines.
5. Restore the network. Within about 60 s you should see `mqtt_reconnected`,
   then `mqtt_subscribed`.
6. **Pass:** the dashboard's "last reading" updates again within one publish
   interval after `mqtt_subscribed`, and you didn't restart anything.
   Readings published while the network was down are lost (QoS 0, see below).

If you see `mqtt_ingest_failed` or `mqtt_message_handler_failed`, messages are
arriving but failing to save: the `error` field says why.

## Gotchas

- **One worker only.** Every worker runs its own MQTT subscriber, so several
  workers would store each reading several times. Don't add `--workers`.
- **Readings sent while the API is down are lost.** The device publishes at
  QoS 0 and the backend uses a clean session, so a restart loses a few seconds
  to minutes of data. Avoid redeploying mid-measurement.
- **Uploaded bill PDFs** live in the `objects` Docker volume, and the database
  in `pgdata`. `docker compose down -v` deletes both: never use `-v` here.
- **Certificate errors on first start** usually mean DNS has not propagated or
  port 80/443 is blocked. Check `logs caddy`.
- Confirm your **EMQX Cloud deployment stays active** for the whole period
  (some plans expire or pause); the dashboard shows nothing if it is gone.
- The dev `docker-compose.yml` (database only) is unchanged and unrelated to this stack.
