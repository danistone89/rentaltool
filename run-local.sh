#!/usr/bin/env bash
# Startet die Beherbergungssteuer-App lokal (nur Python-Standardbibliothek).
set -euo pipefail
cd "$(dirname "$0")"
exec python3 app/server.py
