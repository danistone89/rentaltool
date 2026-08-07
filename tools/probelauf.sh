#!/usr/bin/env bash
# Probelauf am eigenen Rechner – echte Buchungen, aber nichts geht hinaus.
#
#     ./tools/probelauf.sh          # startet auf http://127.0.0.1:3002
#     ./tools/probelauf.sh 3005     # anderer Port
#
# Wozu das statt ./run-local.sh? Weil `run-local.sh` mit dem echten Datenordner
# arbeitet – und dort haengt die echte E-Mail-Konfiguration. Ein Klick auf
# "Senden" in den Rechnungen ginge an einen echten Gast.
#
# Dieser Lauf setzt deshalb zweierlei:
#
#   * RENTALTOOL_STAGING=1 sperrt Mailversand, Gast-Nachrichten und den
#     Nextcloud-Spiegel IM CODE (app/mode.py) – nicht ueber die Konfiguration,
#     die liesse sich versehentlich wieder fuellen.
#   * einen eigenen Datenordner. Was hier entsteht – Rechnungsentwuerfe,
#     Nummern, Belege – bleibt hier und beruehrt weder den Echtbetrieb noch die
#     lokalen Daten.
#
# Die config.json wird aus dem echten Datenordner kopiert, damit der
# Smoobu-Zugang funktioniert und echte Buchungen erscheinen. Smoobu wird dabei
# nur GELESEN; schreibende Aufrufe blockt app/mode.py ebenfalls.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${1:-3002}"
QUELLE="${RENTALTOOL_DATA:-$PWD}"
ZIEL="${PROBE_DATA:-/tmp/livaro-probe}"

if [ ! -f "$QUELLE/config.json" ]; then
  echo "Keine config.json in $QUELLE gefunden." >&2
  exit 1
fi

mkdir -p "$ZIEL"
# Konfiguration bei jedem Start frisch – damit geaenderte Einstellungen
# (Betreiberdaten, Nummernkreis) mitkommen. Die Datenbank bleibt stehen.
cp "$QUELLE/config.json" "$ZIEL/config.json"
for ORDNER in templates assets; do
  [ -d "$ORDNER" ] && cp -R "$ORDNER" "$ZIEL/" 2>/dev/null || true
done

# Port in die Kopie schreiben, damit ein paralleler Echtlauf auf 3001 bleibt.
python3 - "$ZIEL/config.json" "$PORT" <<'PY'
import json, sys
pfad, port = sys.argv[1], int(sys.argv[2])
cfg = json.load(open(pfad, encoding="utf-8"))
cfg["port"] = port
json.dump(cfg, open(pfad, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
PY

PYTHON="$PWD/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="python3"

echo "Probelauf"
echo "  Datenordner : $ZIEL   (Echtbetrieb bleibt unberuehrt)"
echo "  Adresse     : http://127.0.0.1:$PORT"
echo "  Mailversand : gesperrt (PROBE-INSTANZ)"
echo "  Anmeldung   : deine ueblichen Zugangsdaten"
echo
exec env RENTALTOOL_DATA="$ZIEL" RENTALTOOL_STAGING=1 "$PYTHON" app/web.py
