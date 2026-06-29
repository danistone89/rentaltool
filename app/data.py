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

from app import smoobu, steuer

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(HERE, "config.json")

MONATE = ["", "Januar", "Februar", "März", "April", "Mai", "Juni",
          "Juli", "August", "September", "Oktober", "November", "Dezember"]

CONFIG = json.load(open(CONFIG_PATH, encoding="utf-8"))

# Felder der Einstellungs-Seite: config-key -> Label
BETREIBER_FIELDS = [
    ("name", "Name/Firma"), ("zusatz", "Vorname/Firmenzusatz"),
    ("strasse", "Straße"), ("hausnummer", "Hausnummer"),
    ("plz", "PLZ"), ("ort", "Ort"),
    ("telefon", "Telefon"), ("kassenzeichen", "Kassenzeichen"),
]

_CACHE = {}
_CACHE_TTL = 300
LAST_FETCH = None  # Zeitpunkt des letzten echten API-Zugriffs (datetime)


def save_config():
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(CONFIG, fh, ensure_ascii=False, indent=2)


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
    return steuer.compute(
        bookings, year, month,
        steuersatz=CONFIG.get("steuersatz", 0.06),
        airbnb_channel=CONFIG.get("airbnb_channel_name", "Airbnb"),
        steuerbefreite_umsaetze=befreit or 0.0,
        airbnb_overnights_override=airbnb_override)


def euro(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
