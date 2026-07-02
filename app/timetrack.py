#!/usr/bin/env python3
"""Arbeitszeit-Erfassung: Check-in/Check-out je Benutzer (ohne Standort, DSGVO).

Speichert Einträge in worklog.json (Liste): {id, user, checkin(ISO),
checkout(ISO|None)}.
"""
import json
import os
from datetime import datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(HERE, "worklog.json")


def _read():
    if os.path.exists(LOG):
        with open(LOG, encoding="utf-8") as f:
            return json.load(f)
    return []


def _write(items):
    with open(LOG, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)


def get_open(user):
    for e in _read():
        if e["user"] == user and not e.get("checkout"):
            return e
    return None


def check_in(user, now=None):
    """Check-in. Gibt None zurück, wenn bereits ein offener Eintrag existiert."""
    items = _read()
    if any(e["user"] == user and not e.get("checkout") for e in items):
        return None
    now = now or datetime.now()
    e = {"id": now.strftime("%Y%m%d%H%M%S") + "-" + user, "user": user,
         "checkin": now.isoformat(timespec="seconds"), "checkout": None}
    items.append(e)
    _write(items)
    return e


def check_out(user, now=None):
    """Offenen Eintrag des Benutzers schließen. None, wenn keiner offen ist."""
    items = _read()
    now = now or datetime.now()
    for e in reversed(items):
        if e["user"] == user and not e.get("checkout"):
            e["checkout"] = now.isoformat(timespec="seconds")
            _write(items)
            return e
    return None


def entries(user=None):
    items = _read()
    if user:
        items = [e for e in items if e["user"] == user]
    return list(reversed(items))   # neueste zuerst


def duration_minutes(e):
    if not e.get("checkout"):
        return None
    a = datetime.fromisoformat(e["checkin"])
    b = datetime.fromisoformat(e["checkout"])
    return int((b - a).total_seconds() // 60)


def fmt_dur(mins):
    if mins is None:
        return "läuft…"
    return f"{mins // 60}:{mins % 60:02d} h"
