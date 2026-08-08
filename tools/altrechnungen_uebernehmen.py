#!/usr/bin/env python3
"""Die Rechnungen aus dem alten Weg (Smoobu) ins Werkzeug holen – B10.

    .venv/bin/python tools/altrechnungen_uebernehmen.py <ordner>          # Probelauf
    .venv/bin/python tools/altrechnungen_uebernehmen.py <ordner> --bis 78 --schreiben

**Probelauf ist die Vorgabe.** Geschrieben wird nur mit `--schreiben`, und
vorher steht Zeile für Zeile da, was entstehen würde. Ein Lauf, der 78
Rechnungen stillschweigend anlegt, ist nicht nachvollziehbar.

`--bis` ist der Schnitt: bis einschließlich dieser Nummer gehört alles dem
alten Weg, alles darüber dem Werkzeug. Ohne Angabe wird alles gelesen.

Der Nummernkreis wird dabei **nicht** angefasst. Was danach zu tun ist, steht
am Ende der Ausgabe: `rechnung_startjahr` und `rechnung_startnummer` in den
Einstellungen setzen, sonst vergibt das Werkzeug die 1 ein zweites Mal.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import altrechnungen as alt   # noqa: E402
from app import data                   # noqa: E402


def _eur(w):
    return f"{w:>9.2f}"


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("ordner", help="Ordner mit den alten Rechnungs-PDFs")
    p.add_argument("--bis", type=int, default=None,
                   help="letzte Nummer, die noch zum alten Weg gehört")
    p.add_argument("--schreiben", action="store_true",
                   help="tatsächlich anlegen (sonst nur Probelauf)")
    a = p.parse_args()

    if not os.path.isdir(a.ordner):
        print(f"Den Ordner „{a.ordner}“ gibt es nicht.")
        return 1

    saetze = alt.einlesen(a.ordner, a.bis)
    if not saetze:
        print("Keine Rechnungen gefunden.")
        return 1

    schon = alt.vorhandene()
    unvollstaendig = [s for s in saetze
                      if not s["datum"] or not s["summen"]["brutto"]]
    summe = round(sum(s["summen"]["brutto"] for s in saetze), 2)

    print(f"{len(saetze)} Rechnungen gelesen, Nr. {saetze[0]['nummer']}"
          f"–{saetze[-1]['nummer']}, zusammen {summe:.2f} € brutto\n")
    print(f"{'Nr':>4}  {'Datum':10}  {'Gast':24}  {'Wohnung':16}  "
          f"{'brutto':>9} {'USt':>8} {'durchl':>8}")
    for s in saetze:
        merk = "  (schon da)" if s["nummer"] in schon else ""
        print(f"{s['nummer']:>4}  {s['datum']:10}  {s['gast'][:24]:24}  "
              f"{s['wohnung_name'][:16]:16}  {_eur(s['summen']['brutto'])}"
              f"{_eur(s['summen']['ust'])}{_eur(s['summen']['durchlaufend'])}{merk}")

    if unvollstaendig:
        print(f"\n⚠ {len(unvollstaendig)} unvollständig gelesen – die bitte "
              "ansehen, bevor geschrieben wird:")
        for s in unvollstaendig:
            print(f"   Nr {s['nummer']}: {os.path.basename(s['datei'])}")

    if not a.schreiben:
        print("\nProbelauf – es wurde nichts geschrieben. Mit --schreiben anlegen.")
        return 0

    # Die Wohnungen kommen von Smoobu, nicht aus der Konfiguration – dort
    # standen sie nie, und die Zuordnung blieb deshalb im ersten Lauf leer.
    wohnungen = {}
    try:
        from app.ui.basis import _apts
        wohnungen = {k: v for k, v in _apts().items()}
    except Exception as fehler:
        print(f"(Wohnungen nicht erreichbar: {fehler} – Feld bleibt leer)")
    neu, uebersprungen = alt.uebernehmen(saetze, wohnungen)
    print(f"\n{neu} angelegt, {uebersprungen} übersprungen (schon vorhanden).")
    hoechste = max(int(s["nummer"]) for s in saetze)
    print(f"\nNoch zu tun: in den Einstellungen `rechnung_startjahr` auf das "
          f"laufende Jahr und `rechnung_startnummer` auf {hoechste + 1} setzen –"
          f"\nsonst vergibt das Werkzeug die {saetze[0]['nummer']} ein zweites Mal.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
