#!/usr/bin/env python3
"""Abendliche Erinnerung: was morgen ansteht.

    python3 tools/erinnerung.py            # senden
    python3 tools/erinnerung.py --zeigen   # nur anzeigen, nichts senden

Läuft täglich um 18:00 (`rentaltool-erinnerung.timer`). Zwei Nachrichten:

* An **jeden Mitarbeiter** mit Reinigungen am nächsten Tag: wie viele und wo.
* An die **Verwaltung**, wenn für morgen noch etwas **niemandem zugewiesen**
  ist – das ist der Fall, der sonst erst am Morgen auffällt, wenn es zu spät
  ist, jemanden zu organisieren.

Wer für morgen nichts hat, bekommt auch nichts. Eine Erinnerung, die jeden Abend
kommt und meistens „nichts zu tun" sagt, wird nach einer Woche weggewischt.
"""
import argparse
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import bookings, push  # noqa: E402


def jobs_am(tag):
    """Reinigungen (Abreisen) an einem Tag – dieselbe Quelle wie die Oberfläche."""
    from app.ui.buchungen import _cleaning_jobs
    return [j for j in _cleaning_jobs() if j["departure"] == tag.isoformat()]


def verteilen(jobs):
    """(je_mitarbeiter, offen) – reine Funktion, damit die Auswahl prüfbar ist."""
    je_mitarbeiter, offen = {}, []
    for j in jobs:
        wer = bookings.assignee_of(j["id"])
        if wer:
            je_mitarbeiter.setdefault(wer, []).append(j)
        else:
            offen.append(j)
    return je_mitarbeiter, offen


def text_fuer(jobs):
    """„Cottaer Straße, Wernerstraße" bzw. „3 Reinigungen: …“."""
    wohnungen = sorted({j["apartment_name"] for j in jobs})
    return ", ".join(wohnungen)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zeigen", action="store_true", help="nur anzeigen")
    ap.add_argument("--tag", default="", help="Tag statt morgen (JJJJ-MM-TT)")
    args = ap.parse_args(argv)

    tag = date.fromisoformat(args.tag) if args.tag else date.today() + timedelta(days=1)
    jobs = jobs_am(tag)
    je_mitarbeiter, offen = verteilen(jobs)
    datum = f"{tag.day:02d}.{tag.month:02d}."
    print(f"Morgen ({datum}): {len(jobs)} Reinigung(en), "
          f"{len(offen)} ohne Zuweisung")

    from app.ui.basis import USERS
    gesendet = 0
    for benutzer, eigene in sorted(je_mitarbeiter.items()):
        anzahl = len(eigene)
        titel = ("Morgen 1 Reinigung" if anzahl == 1 else f"Morgen {anzahl} Reinigungen")
        text = f"{datum} · {text_fuer(eigene)}"
        print(f"   → {benutzer}: {titel} – {text}")
        if not args.zeigen and push.will(USERS.get(benutzer), "erinnerung"):
            gesendet += push.senden(benutzer, titel, text, "/", "erinnerung")

    if offen:
        titel = ("Morgen 1 Reinigung ohne Zuweisung" if len(offen) == 1
                 else f"Morgen {len(offen)} Reinigungen ohne Zuweisung")
        text = f"{datum} · {text_fuer(offen)}"
        for benutzer, u in sorted(USERS.items()):
            if u.get("role") not in ("admin", "manager"):
                continue
            print(f"   → {benutzer} (Verwaltung): {titel}")
            if not args.zeigen and push.will(u, "erinnerung"):
                gesendet += push.senden(benutzer, titel, text, "/", "erinnerung")

    if not args.zeigen:
        print(f"An {gesendet} Gerät(e) zugestellt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
