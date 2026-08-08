#!/usr/bin/env bash
# Ausrollen mit Netz: Tests vorher, Rauchprobe nachher, Rückweg bei Fehlschlag.
#
#   tools/deploy.sh probe      # aktuellen Stand auf die Probe-Instanz (Port 3002)
#   tools/deploy.sh echt       # nach app.ds-apartments.de (Port 3001)
#   tools/deploy.sh echt --ohne-tests
#
# Vorher lief das von Hand: git pull, systemctl restart, hoffen. Ein Fehler, der
# erst beim Rendern auffällt, stand damit live – und der Weg zurück musste im
# Kopf zusammengesucht werden, während die App aus war.
set -euo pipefail

HOST="${RENTALTOOL_HOST:-rentaltool}"
ZIEL="${1:-}"
shift || true
OHNE_TESTS=0
for arg in "$@"; do [ "$arg" = "--ohne-tests" ] && OHNE_TESTS=1; done

case "$ZIEL" in
  echt)  PFAD=/opt/rentaltool;         DIENST=rentaltool;         PORT=3001 ;;
  probe) PFAD=/opt/rentaltool-staging; DIENST=rentaltool-staging; PORT=3002 ;;
  *) echo "Ziel fehlt: tools/deploy.sh {echt|probe} [--ohne-tests]"; exit 2 ;;
esac

HIER="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HIER"
say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

# ---------------------------------------------------------------- vorher
if [ -n "$(git status --porcelain)" ]; then
  echo "Arbeitsverzeichnis ist nicht sauber – erst committen."; exit 1
fi
ZWEIG="$(git rev-parse --abbrev-ref HEAD)"
if [ "$ZIEL" = "echt" ] && [ "$ZWEIG" != "main" ]; then
  echo "Echtbetrieb nur aus main (hier: $ZWEIG)."; exit 1
fi

if [ "$OHNE_TESTS" = "0" ]; then
  say "Tests"
  PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
  "$PY" -m pytest -q | tail -3
fi

say "Hochladen ($ZWEIG)"
git push origin "$ZWEIG"

# ---------------------------------------------------------------- ausrollen
VORHER="$(ssh "$HOST" "cd $PFAD && git rev-parse HEAD")"
say "Ausrollen nach $PFAD (Stand vorher: ${VORHER:0:8})"
ssh "$HOST" "cd $PFAD && git fetch --quiet origin && git checkout --quiet $ZWEIG && git reset --hard --quiet origin/$ZWEIG && git log --oneline -1"
# Zeitpunkt des Neustarts merken: die Rauchprobe darf nur Fehler ZAEHLEN, die
# danach entstehen. Beim Herunterfahren meldet NiceGUI fuer jeden offenen
# Browser-Tab einen Traceback ("JavaScript did not respond") – das ist kein
# Fehler des neuen Stands, hat aber am 8.8.2026 ein gutes Ausrollen
# zurueckgerollt, nur weil ein Tab offen war.
# Abhaengigkeiten nachziehen. Sie standen bisher nur in requirements.txt und
# wurden von Hand installiert – eine neue Abhaengigkeit rollte damit als
# funktionierender Code aus, dessen Funktion beim ersten Klick abbrach.
ssh "$HOST" "cd $PFAD && .venv/bin/pip install --quiet --upgrade-strategy only-if-needed -r requirements.txt"

SEIT="$(ssh "$HOST" "date '+%Y-%m-%d %H:%M:%S'")"
ssh "$HOST" "systemctl restart $DIENST"

# ---------------------------------------------------------------- Rauchprobe
say "Rauchprobe"
ok=0
for i in $(seq 1 10); do
  sleep 2
  if ssh "$HOST" "curl -fsS --max-time 10 http://127.0.0.1:$PORT/login" 2>/dev/null \
       | grep -qE 'Anmelden|Erst-Einrichtung'; then ok=1; break; fi
  echo "   Versuch $i …"
done

FEHLER="$(ssh "$HOST" "journalctl -u $DIENST --since '$SEIT' --no-pager \
  | grep -viE 'JavaScript did not respond|CancelledError|Stopping|Deactivated|Stopped' \
  | grep -ciE 'traceback|error' || true")"
if [ "$ok" = "1" ] && [ "${FEHLER:-0}" -eq 0 ]; then
  say "Fertig ✓  ($DIENST läuft, Anmeldeseite antwortet, kein Fehler im Log)"
  ssh "$HOST" "cd $PFAD && git log --oneline -1"
  exit 0
fi

# ---------------------------------------------------------------- Rückweg
say "Rauchprobe fehlgeschlagen (Seite ok=$ok, Fehlerzeilen im Log=$FEHLER) – zurück auf ${VORHER:0:8}"
ssh "$HOST" "cd $PFAD && git reset --hard --quiet $VORHER && systemctl restart $DIENST"
sleep 4
if ssh "$HOST" "curl -fsS --max-time 10 http://127.0.0.1:$PORT/login" 2>/dev/null \
     | grep -qE 'Anmelden|Erst-Einrichtung'; then
  echo "Zurückgerollt – der alte Stand läuft wieder."
else
  echo "ACHTUNG: auch der alte Stand antwortet nicht. journalctl -u $DIENST prüfen."
fi
ssh "$HOST" "journalctl -u $DIENST --since '$SEIT' --no-pager | tail -25"
exit 1
