#!/bin/sh
# Garante que /app/data (volume montado do host) seja gravável e roda a app sem root.
set -e
mkdir -p /app/data/previews
if [ "$(id -u)" = "0" ]; then
  chown -R appuser:appuser /app/data 2>/dev/null || true
  exec setpriv --reuid=appuser --regid=appuser --init-groups "$@"
fi
exec "$@"
