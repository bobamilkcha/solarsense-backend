#!/usr/bin/env bash
# Nightly Postgres dump, keeping the last 7. Run from the repo folder on the server.
# Cron (as the deploy user):  0 3 * * * cd /home/<user>/solarsense-backend && ./deploy/backup.sh
set -euo pipefail
mkdir -p backups
ENV_FILE="${ENV_FILE:-.env}"
set -a; . "./$ENV_FILE"; set +a
# COMPOSE_FILES lets the local (ngrok) setup pass its extra compose file.
# shellcheck disable=SC2086
docker compose --env-file "$ENV_FILE" ${COMPOSE_FILES:--f docker-compose.prod.yml} exec -T db \
  pg_dump -U "$DATABASE_USER" "$DATABASE_NAME" | gzip > "backups/solarsense-$(date +%F).sql.gz"
ls -1t backups/solarsense-*.sql.gz | tail -n +8 | xargs -r rm --
