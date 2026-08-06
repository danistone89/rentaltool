#!/usr/bin/env python3
"""Bestände aus den JSON-Dateien in die SQLite-Datenbank übernehmen.

    python3 tools/migrate_db.py            # Probelauf: was würde übernommen
    python3 tools/migrate_db.py --jetzt    # übernehmen und danach prüfen

Einmalig je Installation (AP5). Der Ablauf ist absichtlich vorsichtig:

1. Die Datenbank muss **leer** sein – sonst bricht das Werkzeug ab. Zweimal
   laufen lassen würde sonst alles doppelt anlegen.
2. Übernommen wird in der **Reihenfolge der Datei**, damit „neueste zuerst" in
   den Listen weiterhin dasselbe bedeutet.
3. Danach wird **gegengelesen**: jeder Satz muss sich aus der Datenbank wieder
   genau so herausholen lassen, wie er in der Datei stand. Erst wenn das für
   alle Bestände stimmt, werden die alten Dateien in `<name>.vor-sqlite`
   umbenannt – gelöscht wird nichts.

Der Rückweg besteht damit aus zwei Handgriffen: den vorherigen Stand ausrollen
und die `.vor-sqlite`-Dateien zurückbenennen.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, paths  # noqa: E402

# Datei -> (Tabelle, Bauart). "liste" = Liste von Sätzen mit eigener id,
# "zuordnung" = {schluessel: inhalt}, "zuordnung_liste" = {schluessel: [...]}.
BESTAENDE = [
    ("worklog.json", "zeiten", "liste"),
    ("assignments.json", "zuweisungen", "zuordnung"),
    ("receipts.json", "belege", "liste"),
    ("checklists.json", "checklisten", "zuordnung"),
    ("inventory.json", "bestand", "zuordnung_liste"),
    ("cleanings.json", "durchgaenge", "liste"),
    ("damages.json", "schaeden", "liste"),
    ("restock.json", "nachkauf", "liste"),
]


def _lesen(pfad):
    if not os.path.exists(pfad):
        return None
    with open(pfad, encoding="utf-8") as f:
        return json.load(f)


def saetze(inhalt, bauart):
    """[(id, satz)] in Dateireihenfolge."""
    if inhalt is None:
        return []
    if bauart == "liste":
        return [(str(s["id"]), s) for s in inhalt]
    if bauart == "zuordnung":
        return [(str(k), v) for k, v in inhalt.items()]
    if bauart == "zuordnung_liste":
        # Eine Zeile speichert immer ein Objekt – die Liste kommt unter "items".
        return [(str(k), {"items": v}) for k, v in inhalt.items()]
    raise ValueError(bauart)


def uebernehmen(ordner):
    """Alles übernehmen. Gibt {tabelle: anzahl} zurück."""
    stand = {}
    with db.transaktion():
        for datei, tabelle, bauart in BESTAENDE:
            paare = saetze(_lesen(os.path.join(ordner, datei)), bauart)
            for sid, satz in paare:
                db.anlegen(tabelle, satz, sid=sid)
            stand[tabelle] = len(paare)
    return stand


def gegenlesen(ordner):
    """Jeden Satz aus der Datenbank mit der Datei vergleichen. [] = alles gleich."""
    fehler = []
    for datei, tabelle, bauart in BESTAENDE:
        paare = saetze(_lesen(os.path.join(ordner, datei)), bauart)
        in_db = db.anzahl(tabelle)
        if in_db != len(paare):
            fehler.append(f"{tabelle}: {in_db} in der Datenbank, {len(paare)} in {datei}")
            continue
        for sid, satz in paare:
            zurueck = db.holen(tabelle, sid)
            if zurueck != satz:
                fehler.append(f"{tabelle}/{sid}: Inhalt weicht ab")
        # Reihenfolge zählt: „neueste zuerst" hängt daran.
        if bauart == "liste":
            ids_datei = [sid for sid, _ in paare]
            ids_db = [str(s["id"]) for s in db.alle(tabelle)]
            if ids_datei != ids_db:
                fehler.append(f"{tabelle}: Reihenfolge weicht ab")
    return fehler


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ordner", default=paths.DATA_DIR)
    ap.add_argument("--jetzt", action="store_true", help="wirklich übernehmen")
    args = ap.parse_args(argv)
    ordner = os.path.abspath(args.ordner)

    print(f"Datenordner: {ordner}")
    print(f"Datenbank:   {db.DATEI}\n")
    gesamt = 0
    for datei, tabelle, bauart in BESTAENDE:
        paare = saetze(_lesen(os.path.join(ordner, datei)), bauart)
        gesamt += len(paare)
        zustand = "fehlt" if not os.path.exists(os.path.join(ordner, datei)) else \
                  f"{len(paare)} Satz/Sätze"
        print(f"   {datei:20} → {tabelle:13} {zustand}")

    belegt = {t: db.anzahl(t) for t in db.TABELLEN}
    if any(belegt.values()):
        print("\nDie Datenbank ist nicht leer: "
              + ", ".join(f"{t}={n}" for t, n in belegt.items() if n))
        print("Übernahme abgebrochen – sonst stünde alles doppelt darin.")
        return 1
    if not args.jetzt:
        print(f"\nProbelauf – nichts verändert. Mit --jetzt übernehmen ({gesamt} Sätze).")
        return 0

    stand = uebernehmen(ordner)
    print("\nübernommen: " + ", ".join(f"{t}={n}" for t, n in stand.items() if n))

    fehler = gegenlesen(ordner)
    if fehler:
        print("\nGegenlesen FEHLGESCHLAGEN:")
        for f in fehler:
            print(f"   · {f}")
        print("Die alten Dateien bleiben unangetastet. Datenbank prüfen "
              "(oder rentaltool.db löschen und erneut versuchen).")
        return 1
    print("gegengelesen: jeder Satz kommt unverändert zurück ✓")

    for datei, _t, _b in BESTAENDE:
        alt = os.path.join(ordner, datei)
        if os.path.exists(alt):
            os.replace(alt, alt + ".vor-sqlite")
    print("alte Dateien umbenannt auf *.vor-sqlite (nichts gelöscht)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
