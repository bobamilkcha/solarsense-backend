#!/usr/bin/env bash
# Build the frontend for same-origin hosting (API under /api) into ./web, which Caddy serves.
# Usage: ./deploy/build_frontend.sh [path-to-frontend-repo]   (default: ../solarsense-frontend)
set -euo pipefail
FRONTEND="${1:-../solarsense-frontend}"
HERE="$(pwd)"
(cd "$FRONTEND" && VITE_API_URL=/api npm run build)
mkdir -p "$HERE/web"
rsync -a --delete "$FRONTEND/dist/" "$HERE/web/"
echo "Frontend copied to $HERE/web"
