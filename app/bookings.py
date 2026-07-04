#!/usr/bin/env python3
"""Buchungs-Workflow: Zuweisung von Mitarbeitern zu Smoobu-Buchungen + Tausch.

Smoobu ist die Quelle der Buchungsdaten (nur lesen). Hier speichern wir nur unsere
eigenen Metadaten je Buchung: welcher Mitarbeiter zuständig ist (assignee) und die
Tausch-/Zuweisungs-Historie. Datei assignments.json (gitignored, betrieblich).
"""
import json
import os
from datetime import datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSIGN = os.path.join(HERE, "assignments.json")


def _read():
    if os.path.exists(ASSIGN):
        with open(ASSIGN, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _write(obj):
    with open(ASSIGN, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def get_assignment(booking_id):
    return _read().get(str(booking_id))


def assignee_of(booking_id):
    a = get_assignment(booking_id)
    return a.get("assignee") if a else None


def set_assignment(booking_id, assignee, by, note=""):
    """Buchung einem Mitarbeiter zuweisen/umverteilen. Gibt (eintrag, vorheriger) zurück."""
    d = _read()
    key = str(booking_id)
    cur = d.get(key) or {"history": []}
    prev = cur.get("assignee")
    cur.update({"assignee": assignee, "assigned_by": by, "ts": now_iso()})
    cur.setdefault("history", []).append(
        {"from": prev, "to": assignee, "by": by, "ts": now_iso(), "note": note})
    d[key] = cur
    _write(d)
    return cur, prev


def clear_assignment(booking_id):
    d = _read()
    if str(booking_id) in d:
        d.pop(str(booking_id))
        _write(d)


# ----------------------------------------------------- Smoobu-Buchung normalisieren
def is_real(b):
    """True für echte, nicht stornierte Buchungen (keine Blockierungen)."""
    return b.get("type") != "cancellation" and not b.get("is-blocked-booking")


def normalize(b):
    ap = b.get("apartment") or {}
    guest = (b.get("guest-name") or
             f"{b.get('firstname', '')} {b.get('lastname', '')}".strip())
    return {
        "id": b.get("id"),
        "apartment_id": ap.get("id"),
        "apartment_name": ap.get("name", ""),
        "arrival": b.get("arrival", ""),
        "departure": b.get("departure", ""),
        "checkin_time": b.get("check-in", "") or "",
        "checkout_time": b.get("check-out", "") or "",
        "adults": b.get("adults") or 0,
        "children": b.get("children") or 0,
        "persons": (b.get("adults") or 0) + (b.get("children") or 0),
        "guest": guest,
        "email": b.get("email", "") or "",
        "phone": b.get("phone", "") or "",
        "channel": (b.get("channel") or {}).get("name", ""),
        "notice": b.get("notice", "") or "",
        "guest_app_url": b.get("guest-app-url", "") or "",
    }
