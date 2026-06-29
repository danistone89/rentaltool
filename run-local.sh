#!/usr/bin/env bash
# Startet die Beherbergungssteuer-App lokal (NiceGUI-Oberfläche).
# Vorab: pip install -r requirements.txt
set -euo pipefail
cd "$(dirname "$0")"
exec python3 app/web.py
