#!/usr/bin/env python3
"""Datenschicht: Konfiguration, Smoobu-Cache und Steuerberechnung.

Kapselt Config-Laden/Speichern, das Ziehen + Cachen der Reservierungen und die
Berechnung. Wird von der NiceGUI-Oberfläche (app/web.py) genutzt – das fachliche
Backend (smoobu, steuer, pdf_form) bleibt unverändert.
"""
import json
import os
import time
from datetime import date, timedelta

from app import paths, smoobu, steuer, store

HERE = paths.ROOT
CONFIG_PATH = paths.p("config.json")

# Getrennter Datenordner eingerichtet, Konfiguration aber noch im Projektordner?
# Dann sind die Daten nicht umgezogen. Ohne diese Prüfung startete die App mit
# leerer Konfiguration – und böte auf der Login-Seite an, einen NEUEN
# Administrator anzulegen, während die echten Konten unbemerkt daneben liegen.
if paths.getrennt() and not os.path.exists(CONFIG_PATH) \
        and os.path.exists(os.path.join(paths.ROOT, "config.json")):
    raise SystemExit(
        f"config.json fehlt im Datenordner {paths.DATA_DIR}, liegt aber noch im "
        f"Projektordner {paths.ROOT}.\n"
        f"Erst die Daten umziehen, dann starten:\n"
        f"  python3 tools/migrate_data.py {paths.DATA_DIR} --jetzt")

MONATE = ["", "Januar", "Februar", "März", "April", "Mai", "Juni",
          "Juli", "August", "September", "Oktober", "November", "Dezember"]

CONFIG = json.load(open(CONFIG_PATH, encoding="utf-8"))

# Felder der Einstellungs-Seite: config-key -> Label
BETREIBER_FIELDS = [
    ("name", "Name/Firma"), ("zusatz", "Vorname/Firmenzusatz"),
    ("strasse", "Straße"), ("hausnummer", "Hausnummer"),
    ("plz", "PLZ"), ("ort", "Ort"),
    ("telefon", "Telefon"), ("kassenzeichen", "Kassenzeichen"),
    # Pflichtangaben einer Rechnung (§ 14 Abs. 4 UStG) – ohne sie ist der Beleg
    # unvollstaendig, und der Gast kann keine Vorsteuer ziehen.
    ("email", "E-Mail"), ("steuernummer", "Steuernummer"),
    ("ust_id", "USt-IdNr. (falls vorhanden)"),
    ("bank", "Bank"), ("iban", "IBAN"), ("bic", "BIC"),
]

_CACHE = {}
_CACHE_TTL = 300
LAST_FETCH = None  # Zeitpunkt des letzten echten API-Zugriffs (datetime)
# Die Rohbuchungen der letzten Rechnung. Die Vollstaendigkeitspruefung (AP11)
# braucht auch das, was `steuer.classify` wegwirft – eine Buchung ohne
# Abreisedatum faellt sonst still aus der Summe.
LAST_BOOKINGS = []


def save_config():
    """Konfiguration atomar sichern.

    Die heikelste Datei überhaupt: hier stehen die Benutzerkonten. Ein Abbruch
    beim Schreiben hätte die App ohne Konten zurückgelassen (siehe app/store.py).
    """
    store.write(CONFIG_PATH, CONFIG, indent=2)


def clear_cache():
    _CACHE.clear()


def get_apartments():
    return smoobu.get_apartments(CONFIG["smoobu_api_key"])


def _reservations(date_from, date_to):
    global LAST_FETCH
    key = (date_from, date_to)
    hit = _CACHE.get(key)
    if hit and (time.time() - hit[0]) < _CACHE_TTL:
        return hit[1]
    from datetime import datetime
    data = smoobu.get_reservations(CONFIG["smoobu_api_key"], date_from, date_to)
    _CACHE[key] = (time.time(), data)
    LAST_FETCH = datetime.now()
    return data


def compute(year, month, *, apt_ids=None, airbnb_override=None, befreit=0.0):
    """Reservierungen ziehen und Steuer für (year, month) berechnen."""
    first = date(year, month, 1)
    d_from = (first - timedelta(days=92)).isoformat()
    nxt = date(year + (month == 12), (month % 12) + 1, 1)
    d_to = (nxt - timedelta(days=1)).isoformat()
    bookings = _reservations(d_from, d_to)
    if apt_ids:
        ids = set(apt_ids)
        bookings = [b for b in bookings if (b.get("apartment") or {}).get("id") in ids]
    global LAST_BOOKINGS
    LAST_BOOKINGS = bookings
    return steuer.compute(
        bookings, year, month,
        steuersatz=CONFIG.get("steuersatz", 0.06),
        airbnb_channel=CONFIG.get("airbnb_channel_name", "Airbnb"),
        steuerbefreite_umsaetze=befreit or 0.0,
        airbnb_overnights_override=airbnb_override)


def euro(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def detect_cloud_folders():
    """Synchronisierte Cloud-Ordner (Nextcloud/iCloud/Dropbox …) als Vorschläge.

    macOS legt sie unter ~/Library/CloudStorage ab.
    """
    out = []
    base = os.path.expanduser("~/Library/CloudStorage")
    if os.path.isdir(base):
        for name in sorted(os.listdir(base)):
            p = os.path.join(base, name)
            if os.path.isdir(p):
                out.append(p)
    return out


# ---------------------------------------------------------- Gastdaten (AP14)
# Die Anschrift steht am Gast, nicht an der Buchung. Ein Abruf je Buchung waere
# achtzigmal so teuer wie einer ueber alle Gaeste – deshalb einmal alles holen
# und nach Buchungsnummer ablegen.
_GAESTE = {"stand": None, "je_buchung": {}}
_GAESTE_TTL = 900


def gastdaten(force=False):
    """{buchungs_id: gast} fuer alle Gaeste. Zwischengespeichert (15 Minuten)."""
    import time
    jetzt = time.time()
    if not force and _GAESTE["stand"] and jetzt - _GAESTE["stand"] < _GAESTE_TTL:
        return _GAESTE["je_buchung"]
    key = (CONFIG.get("smoobu_api_key") or "").strip()
    if not key:
        return {}
    je_buchung = {}
    for g in smoobu.get_guests(key):
        for b in (g.get("bookings") or []):
            if isinstance(b, dict) and b.get("id"):
                je_buchung[b["id"]] = g
    _GAESTE.update(stand=jetzt, je_buchung=je_buchung)
    return je_buchung


def gast_zu_buchung(buchung_id):
    """Der Gast dieser Buchung – None, wenn unbekannt."""
    return gastdaten().get(buchung_id)
