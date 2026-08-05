#!/usr/bin/env python3
"""Betriebsdaten aus dem Projektordner in einen eigenen Datenordner umziehen.

Einmalig je Installation. Danach zeigt die App über RENTALTOOL_DATA dorthin
(siehe app/paths.py) und `git pull` fasst die Daten nicht mehr an.

    python3 tools/migrate_data.py /var/lib/rentaltool          # nur zeigen
    python3 tools/migrate_data.py /var/lib/rentaltool --jetzt  # wirklich umziehen

Verschoben wird, nicht kopiert: eine zweite Kopie im Projektordner wäre die
gefährlichere Variante – man weiß hinterher nicht, welche die echte ist.
Vorhandene Dateien im Ziel werden NIE überschrieben; sie werden übersprungen
und am Ende gemeldet.
"""
import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import paths  # noqa: E402


def plan(quelle, ziel):
    """[(art, name, quelle_pfad, ziel_pfad, status)] – was zu tun wäre."""
    out = []
    for art, namen in (("Datei", paths.DATEIEN), ("Ordner", paths.ORDNER)):
        for name in namen:
            q = os.path.join(quelle, name)
            z = os.path.join(ziel, name)
            if not os.path.exists(q):
                status = "fehlt"
            elif os.path.exists(z):
                status = "Ziel belegt"
            else:
                status = "umziehen"
            out.append((art, name, q, z, status))
    return out


def groesse(pfad):
    if os.path.isfile(pfad):
        return os.path.getsize(pfad)
    total = 0
    for wurzel, _, dateien in os.walk(pfad):
        for d in dateien:
            try:
                total += os.path.getsize(os.path.join(wurzel, d))
            except OSError:
                pass
    return total


def _mb(b):
    return f"{b / 1024 / 1024:.1f} MB" if b >= 1024 * 1024 else f"{b / 1024:.1f} KB"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ziel", help="Zielordner, z. B. /var/lib/rentaltool")
    ap.add_argument("--quelle", default=paths.ROOT, help="Quelle (Vorgabe: Projektordner)")
    ap.add_argument("--jetzt", action="store_true", help="wirklich verschieben")
    args = ap.parse_args(argv)

    quelle = os.path.abspath(args.quelle)
    ziel = os.path.abspath(args.ziel)
    if quelle == ziel:
        print("Quelle und Ziel sind derselbe Ordner – nichts zu tun.")
        return 1

    eintraege = plan(quelle, ziel)
    zu_tun = [e for e in eintraege if e[4] == "umziehen"]
    belegt = [e for e in eintraege if e[4] == "Ziel belegt"]

    print(f"Quelle: {quelle}")
    print(f"Ziel:   {ziel}\n")
    for art, name, q, _z, status in eintraege:
        marke = {"umziehen": "→", "Ziel belegt": "!", "fehlt": "·"}[status]
        extra = f"  ({_mb(groesse(q))})" if status == "umziehen" else ""
        print(f" {marke} {art:6} {name:22} {status}{extra}")

    if belegt:
        print(f"\n{len(belegt)} Eintrag/Einträge liegen im Ziel bereits vor und "
              "bleiben unangetastet.")
    if not zu_tun:
        print("\nNichts zu verschieben.")
        return 0
    if not args.jetzt:
        print(f"\nProbelauf – nichts verändert. Mit --jetzt wirklich verschieben "
              f"({len(zu_tun)} Eintrag/Einträge).")
        return 0

    os.makedirs(ziel, exist_ok=True)
    for art, name, q, z, _status in zu_tun:
        shutil.move(q, z)
        print(f"   verschoben: {name}")
    print(f"\nFertig. Jetzt RENTALTOOL_DATA={ziel} setzen "
          f"(systemd: Environment= in der Unit) und den Dienst neu starten.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
