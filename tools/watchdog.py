#!/usr/bin/env python3
"""Wächter: prüft alle paar Minuten, ob der Betrieb noch steht.

    python3 tools/watchdog.py            # prüfen, bei Bedarf melden
    python3 tools/watchdog.py --zeigen   # nur anzeigen, nie melden

Geprüft wird das, was im Betrieb tatsächlich ausfällt:

* **Oberfläche** – antwortet die App auf `/login`, und steht dort das
  Anmeldeformular? Ein Prozess, der läuft, aber beim Rendern abstürzt, wäre
  über `systemctl is-active` nicht zu unterscheiden.
* **Smoobu** – ohne die API sind Buchungslisten leer. Das sieht aus wie
  „nichts zu tun", ist aber ein Ausfall.
* **Daten** – lassen sich Konten, Zeiten und Zuweisungen lesen?
* **Sicherung** – ist die letzte nicht älter als 36 Stunden? Eine Sicherung,
  die still aufgehört hat, ist der gefährlichste Ausfall überhaupt.

Gemeldet wird **nur bei Wechseln**: wenn eine Prüfung kippt, einmal; danach
höchstens alle 6 Stunden erneut; und einmal, wenn sie sich wieder fängt. Sonst
gewöhnt man sich an die Mails und liest sie irgendwann nicht mehr.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import paths  # noqa: E402

STATUS = "watchdog-status.json"
WIEDERVORLAGE_S = 6 * 3600
SICHERUNG_MAX_H = 36
URL = "http://127.0.0.1:3001/login"


def _pruefe_oberflaeche(url=URL):
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            if r.status != 200:
                return False, f"HTTP {r.status}"
            text = r.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as ex:
        return False, f"nicht erreichbar: {ex}"
    # NiceGUI baut die Seite im Browser auf; im HTML steht der Startzustand.
    if "Anmelden" not in text and "Erst-Einrichtung" not in text:
        return False, "Seite antwortet, aber ohne Anmeldeformular"
    return True, "erreichbar"


def _pruefe_smoobu():
    from app import data, smoobu
    key = (data.CONFIG.get("smoobu_api_key") or "").strip()
    if not key:
        return False, "kein API-Key hinterlegt"
    try:
        apts = smoobu.get_apartments(key)
    except Exception as ex:
        return False, f"{ex}"[:200]
    if not apts:
        return False, "keine Wohnungen geliefert"
    return True, f"{len(apts)} Wohnung(en)"


def _pruefe_daten():
    from app import bookings, data, store, timetrack
    try:
        konten = ((data.CONFIG.get("auth") or {}).get("users") or {})
        if not konten:
            return False, "keine Benutzerkonten"
        n_zeit = len(timetrack.entries())
        n_zuw = len(bookings._read())
    except store.DatenFehler as ex:
        return False, f"{ex}"[:200]
    except Exception as ex:
        return False, f"{type(ex).__name__}: {ex}"[:200]
    return True, f"{len(konten)} Konten, {n_zeit} Zeiten, {n_zuw} Zuweisungen"


def _pruefe_sicherung():
    pfad = paths.p("backup-status.json")
    if not os.path.exists(pfad):
        return False, "noch nie gelaufen"
    try:
        with open(pfad, encoding="utf-8") as f:
            s = json.load(f)
    except Exception as ex:
        return False, f"Statusdatei unlesbar: {ex}"
    if not s.get("ok"):
        return False, "letzte Sicherung fehlgeschlagen: " + "; ".join(s.get("fehler") or [])
    try:
        alter_h = (datetime.now() - datetime.fromisoformat(s["zeit"])).total_seconds() / 3600
    except Exception:
        return False, "Zeitpunkt der letzten Sicherung unlesbar"
    if alter_h > SICHERUNG_MAX_H:
        return False, f"letzte Sicherung vor {alter_h:.0f} h"
    return True, f"vor {alter_h:.0f} h ({s.get('datei', '?')})"


PRUEFUNGEN = [
    ("Oberfläche", _pruefe_oberflaeche),
    ("Smoobu", _pruefe_smoobu),
    ("Daten", _pruefe_daten),
    ("Sicherung", _pruefe_sicherung),
]


def _status_lesen():
    pfad = paths.p(STATUS)
    if not os.path.exists(pfad):
        return {}
    try:
        with open(pfad, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _status_schreiben(obj):
    pfad = paths.p(STATUS)
    tmp = pfad + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, pfad)


def melden(betreff, text):
    try:
        from app import data, mailer
        empf = ((data.CONFIG.get("notify_email") or {}).get("absender")
                or (data.CONFIG.get("email") or {}).get("absender") or "")
        if not empf:
            return False
        mailer.send_notify(data.CONFIG, empf, betreff, text)
        return True
    except Exception as ex:
        print(f"   (Meldung nicht zustellbar: {ex})")
        return False


def faellig(alt, ok, jetzt):
    """Soll gemeldet werden? (bei Wechsel, sonst höchstens alle 6 Stunden)

    Reine Funktion – die Regel gegen Melde-Lawinen gehört getestet.
    """
    if alt is None:
        return not ok                       # erster Lauf: nur Probleme melden
    war_ok = alt.get("ok", True)
    if ok != war_ok:
        return True                         # kaputtgegangen oder wieder da
    if ok:
        return False
    return (jetzt - float(alt.get("gemeldet", 0))) >= WIEDERVORLAGE_S


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zeigen", action="store_true", help="nur anzeigen, nie melden")
    ap.add_argument("--url", default=URL)
    args = ap.parse_args(argv)

    alt = _status_lesen()
    jetzt = time.time()
    neu, kaputt, geheilt = {}, [], []

    for name, fn in PRUEFUNGEN:
        try:
            ok, info = fn(args.url) if fn is _pruefe_oberflaeche else fn()
        except Exception as ex:                     # Prüfung selbst kaputt
            ok, info = False, f"Prüfung fehlgeschlagen: {type(ex).__name__}: {ex}"[:200]
        print(f"{'OK  ' if ok else 'FEHL'} {name:12} {info}")
        vorher = alt.get(name)
        eintrag = {"ok": ok, "info": info,
                   "zeit": datetime.now().isoformat(timespec="seconds"),
                   "gemeldet": (vorher or {}).get("gemeldet", 0)}
        if not args.zeigen and faellig(vorher, ok, jetzt):
            (geheilt if ok else kaputt).append((name, info))
            eintrag["gemeldet"] = jetzt
        neu[name] = eintrag

    if kaputt:
        text = ("Der Wächter meldet ein Problem im Echtbetrieb:\n\n"
                + "\n".join(f"· {n}: {i}" for n, i in kaputt)
                + "\n\nStand aller Prüfungen:\n"
                + "\n".join(f"· {n}: {'ok' if e['ok'] else 'FEHLER'} – {e['info']}"
                            for n, e in neu.items()))
        melden(f"rentaltool: {', '.join(n for n, _ in kaputt)} gestört", text)
    if geheilt:
        melden("rentaltool: wieder in Ordnung",
               "Das hat sich wieder gefangen:\n\n"
               + "\n".join(f"· {n}: {i}" for n, i in geheilt))

    if not args.zeigen:
        _status_schreiben(neu)
    return 1 if any(not e["ok"] for e in neu.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
