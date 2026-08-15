#!/usr/bin/env bash
# Start-script voor PM2. Leest .env in zodat de poort (BIND) maar op één
# plek moet worden aangepast, en start gunicorn.
#
# Gebruik:
#   pm2 start ./start_server.sh --name oryn-showup
set -euo pipefail
cd "$(dirname "$0")"

set -a
source .env
set +a

exec .venv/bin/gunicorn \
    --workers 2 \
    --threads 4 \
    --timeout 60 \
    --bind "${BIND:-0.0.0.0:5000}" \
    wsgi:app
