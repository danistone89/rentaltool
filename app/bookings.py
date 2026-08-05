#!/usr/bin/env python3
"""Buchungs-Workflow: Zuweisung von Mitarbeitern zu Smoobu-Buchungen + Tausch.

Smoobu ist die Quelle der Buchungsdaten (nur lesen). Hier speichern wir nur unsere
eigenen Metadaten je Buchung: welcher Mitarbeiter zuständig ist (assignee) und die
Tausch-/Zuweisungs-Historie. Datei assignments.json (gitignored, betrieblich).
"""
import json
import os
from datetime import datetime

from app import paths, store

HERE = paths.ROOT
ASSIGN = paths.p("assignments.json")


def _read():
    return store.read(ASSIGN, {})


def _write(obj):
    store.write(ASSIGN, obj)


def _aendern():
    """Zuweisungen unter Sperre ändern (siehe app/store.py)."""
    return store.edit(ASSIGN, {})


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def get_assignment(booking_id):
    return _read().get(str(booking_id))


def assignee_of(booking_id):
    a = get_assignment(booking_id)
    return a.get("assignee") if a else None


def set_assignment(booking_id, assignee, by, note=""):
    """Buchung einem Mitarbeiter zuweisen/umverteilen. Gibt (eintrag, vorheriger) zurück."""
    key = str(booking_id)
    with _aendern() as a:
        cur = a.wert.get(key) or {"history": []}
        prev = cur.get("assignee")
        cur.update({"assignee": assignee, "assigned_by": by, "ts": now_iso()})
        cur.setdefault("history", []).append(
            {"from": prev, "to": assignee, "by": by, "ts": now_iso(), "note": note})
        a.wert[key] = cur
    return cur, prev


def clear_assignment(booking_id):
    with _aendern() as a:
        if str(booking_id) in a.wert:
            a.wert.pop(str(booking_id))
        else:
            a.verwerfen()


def get_record(booking_id):
    return _read().get(str(booking_id)) or {}


def set_field(booking_id, **fields):
    """Zusatzfelder am Buchungs-Datensatz setzen (legt ihn bei Bedarf an)."""
    key = str(booking_id)
    with _aendern() as a:
        rec = a.wert.get(key) or {"history": []}
        rec.update(fields)
        a.wert[key] = rec
    return rec


def mark_checklist_done(booking_id, user=None):
    set_field(booking_id, checklist_done=now_iso(), checklist_by=user or "")


def is_checklist_done(booking_id):
    return bool(get_record(booking_id).get("checklist_done"))


def reset(booking_id):
    """Workflow-Status zurücksetzen: Zuweisung, Checklisten-Abschluss und Flags löschen
    (Notiz bleibt erhalten). Status wird damit wieder 'nicht zugewiesen'."""
    key = str(booking_id)
    with _aendern() as a:
        rec = a.wert.get(key)
        if not rec:
            a.verwerfen()
            return
        for f in ("assignee", "assigned_by", "ts", "checklist_done", "checklist_by",
                  "nachtragen_notified"):
            rec.pop(f, None)
        rec.setdefault("history", []).append({"reset": now_iso()})
        a.wert[key] = rec


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
