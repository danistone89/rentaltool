#!/usr/bin/env python3
"""Gesetzliche Feiertage in Sachsen (Dresden) + Einstufung eines Tages.

Für die Zeiterfassung wird nur zwischen zwei Tagesarten unterschieden:

  WERKTAG    – Montag bis Freitag, sofern kein Feiertag
  WOCHENENDE – Samstag, Sonntag oder gesetzlicher Feiertag

Sachsen hat 11 gesetzliche Feiertage. Fronleichnam gilt nur in einzelnen
sorbischen Gemeinden des Landkreises Bautzen und ist deshalb hier bewusst
nicht enthalten (für Dresden nicht einschlägig).
"""
from datetime import date, timedelta

WERKTAG = "werktag"
WOCHENENDE = "wochenende_feiertag"

LABELS = {WERKTAG: "Werktag", WOCHENENDE: "Wochenende/Feiertag"}


def ostersonntag(year):
    """Gaußsche Osterformel (gregorianisch)."""
    a = year % 19; b = year // 100; c = year % 100
    d = b // 4; e = b % 4; f = (b + 8) // 25; g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30; i = c // 4; k = c % 4
    ll = (32 + 2 * e + 2 * i - h - k) % 7; mm = (a + 11 * h + 22 * ll) // 451
    month = (h + ll - 7 * mm + 114) // 31
    day = ((h + ll - 7 * mm + 114) % 31) + 1
    return date(year, month, day)


def buss_und_bettag(year):
    """Mittwoch vor dem 23. November."""
    d = date(year, 11, 23)
    while d.weekday() != 2:
        d -= timedelta(days=1)
    return d


def feiertage(year):
    """{date: Name} aller gesetzlichen Feiertage in Sachsen."""
    o = ostersonntag(year)
    return {
        date(year, 1, 1): "Neujahr",
        o - timedelta(days=2): "Karfreitag",
        o + timedelta(days=1): "Ostermontag",
        date(year, 5, 1): "Tag der Arbeit",
        o + timedelta(days=39): "Christi Himmelfahrt",
        o + timedelta(days=50): "Pfingstmontag",
        date(year, 10, 3): "Tag der Deutschen Einheit",
        date(year, 10, 31): "Reformationstag",
        buss_und_bettag(year): "Buß- und Bettag",
        date(year, 12, 25): "1. Weihnachtsfeiertag",
        date(year, 12, 26): "2. Weihnachtsfeiertag",
    }


def name_of(d):
    """Name des Feiertags oder None."""
    return feiertage(d.year).get(d)


def is_feiertag(d):
    return d in feiertage(d.year)


def kind_of(d):
    """WERKTAG oder WOCHENENDE für ein date."""
    return WOCHENENDE if (d.weekday() >= 5 or is_feiertag(d)) else WERKTAG


def label_of(d):
    """Sprechende Tagesart für die Anzeige: Feiertagsname, sonst Wochentag-Art."""
    return name_of(d) or ("Samstag" if d.weekday() == 5 else
                          "Sonntag" if d.weekday() == 6 else "Werktag")
