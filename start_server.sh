#!/usr/bin/env bash
# Start-script voor PM2.
#
# Belangrijk: dit script leest NOOIT je hele .env in via bash "source" —
# waarden zoals je Gmail app-wachtwoord bevatten spaties (bv. "mpwd cwpu
# mgmn gnwh"), en bash zou dat als los commando proberen uitvoeren. In
# plaats daarvan pikt het script enkel de BIND-regel eruit met grep, puur
# als tekst. De rest van .env (SMTP_ADDRESS, SMTP_PASSWORD, FLASK_SECRET,
# ...) wordt door de Python-app zelf ingelezen (via python-dotenv in
# wsgi.py) — daar speelt dit probleem niet.
#
# Gebruik:
#   chmod +x start_server.sh
#   pm2 start ./start_server.sh --name oryn-showup
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
    echo "FOUT: geen .env gevonden in $(pwd). Kopieer .env.example naar .env en vul in." >&2
    exit 1
fi

BIND=$(grep -E '^BIND=' .env | head -n1 | cut -d'=' -f2-)
BIND="${BIND:-0.0.0.0:5000}"

exec .venv/bin/gunicorn \
    --workers 2 \
    --threads 4 \
    --timeout 60 \
    --bind "$BIND" \
    wsgi:app
