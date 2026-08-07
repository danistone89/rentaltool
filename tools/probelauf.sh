#!/usr/bin/env bash
# Probelauf am eigenen Rechner – echte Buchungen, aber nichts geht hinaus.
#
#     ./tools/probelauf.sh --von-live   # Konten+Daten vom Echtbetrieb holen
#     ./tools/probelauf.sh              # weiter mit dem, was schon da ist
#     ./tools/probelauf.sh 3005         # anderer Port
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

# --von-live holt Konten und Daten frisch vom Echtbetrieb (siehe unten).
VON_LIVE=0
ARGS=()
for a in "$@"; do
  case "$a" in
    --von-live) VON_LIVE=1 ;;
    *) ARGS+=("$a") ;;
  esac
done
set -- "${ARGS[@]:-}"

PORT="${1:-3002}"
QUELLE="${RENTALTOOL_DATA:-$PWD}"
ZIEL="${PROBE_DATA:-/tmp/livaro-probe}"

mkdir -p "$ZIEL"

if [ "$VON_LIVE" = "1" ]; then
  # Konten und Daten vom Echtbetrieb holen. Ohne das meldet man sich hier mit
  # Konten an, die es nur lokal gibt – und sieht Daten, die niemand kennt.
  #
  # Die Konfiguration wird dabei durch tools/staging_refresh.entschaerfen()
  # geschickt: Mail-Passwort, Nextcloud-Spiegel und Sicherungsziel fallen
  # heraus, die BENUTZERKONTEN bleiben (man will sich mit dem eigenen Passwort
  # anmelden). Der Smoobu-Zugang bleibt ebenfalls – ohne ihn gaebe es keine
  # Buchungen, und schreibende Aufrufe blockt app/mode.py.
  echo "Hole Konten und Daten vom Echtbetrieb ..."
  ssh rentaltool 'cd /opt/rentaltool && RENTALTOOL_DATA=/var/lib/rentaltool \
      .venv/bin/python -c "from app import db; db.sichern_nach(\"/tmp/abzug.db\")"' \
    || { echo "Datenbank-Abzug fehlgeschlagen." >&2; exit 1; }
  scp -q rentaltool:/var/lib/rentaltool/config.json "$ZIEL/config.live.json"
  scp -q rentaltool:/tmp/abzug.db "$ZIEL/rentaltool.db"
  ssh rentaltool 'rm -f /tmp/abzug.db'
  rsync -a --quiet rentaltool:/var/lib/rentaltool/media/ "$ZIEL/media/" 2>/dev/null || true
  rsync -a --quiet rentaltool:/var/lib/rentaltool/archive/ "$ZIEL/archive/" 2>/dev/null || true

  PYTHON_ENTSCHAERF="$PWD/.venv/bin/python"
  [ -x "$PYTHON_ENTSCHAERF" ] || PYTHON_ENTSCHAERF="python3"
  "$PYTHON_ENTSCHAERF" - "$ZIEL" "$PORT" <<'PY'
import json, sys, os
sys.path.insert(0, os.getcwd())
from tools.staging_refresh import entschaerfen
ziel, port = sys.argv[1], int(sys.argv[2])
roh = json.load(open(os.path.join(ziel, "config.live.json"), encoding="utf-8"))
cfg = entschaerfen(roh, url=f"http://127.0.0.1:{port}", konten=True)
cfg["port"] = port
json.dump(cfg, open(os.path.join(ziel, "config.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
os.remove(os.path.join(ziel, "config.live.json"))
konten = list((cfg.get("auth") or {}).get("users") or {})
print(f"  Konten uebernommen: {', '.join(konten) or '(keine)'}")
print("  Entfernt: Mail-Passwort, Nextcloud-Spiegel, Sicherungsziel")
PY
  QUELLE="$ZIEL"        # ab hier ist die entschaerfte Kopie die Quelle
fi

if [ ! -f "$QUELLE/config.json" ]; then
  echo "Keine config.json in $QUELLE gefunden." >&2
  echo "Beim ersten Mal mit --von-live starten." >&2
  exit 1
fi
# Konfiguration bei jedem Start frisch – damit geaenderte Einstellungen
# (Betreiberdaten, Nummernkreis) mitkommen. Die Datenbank bleibt stehen.
# Nach --von-live ist die Quelle schon das Ziel; dann waere es dieselbe Datei.
if [ "$QUELLE" != "$ZIEL" ]; then
  cp "$QUELLE/config.json" "$ZIEL/config.json"
fi
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
