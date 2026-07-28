#!/usr/bin/env bash
# Laedt OpenCV.js (~10 MB) nach static/, damit der Belegscanner es vom eigenen
# Server ausliefert statt vom CDN. Optional: fehlt die Datei, faellt der Scanner
# automatisch auf https://docs.opencv.org zurueck.
#
#   ./tools/fetch_opencv.sh          (im Projektverzeichnis oder auf dem Server)
set -euo pipefail
cd "$(dirname "$0")/.."
URL="https://docs.opencv.org/4.8.0/opencv.js"
DST="static/opencv.js"
mkdir -p static
echo "Lade $URL …"
curl -fsSL --max-time 300 "$URL" -o "$DST.tmp"
# Grobe Plausibilitaetspruefung: muss gross und JavaScript sein
SIZE=$(wc -c < "$DST.tmp")
if [ "$SIZE" -lt 1000000 ]; then
  echo "FEHLER: nur $SIZE Bytes – Download unvollstaendig." >&2
  rm -f "$DST.tmp"; exit 1
fi
mv "$DST.tmp" "$DST"
echo "OK: $DST ($SIZE Bytes)"
