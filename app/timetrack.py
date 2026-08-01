#!/usr/bin/env python3
"""Arbeitszeit-Erfassung: Check-in/Check-out je Benutzer mit Standort.

Speichert Einträge in worklog.json (Liste). Jeder Eintrag:
  {id, user, checkin(ISO), checkin_loc, checkout(ISO|None), checkout_loc}
checkin_loc/checkout_loc: {lat, lon, acc} oder {error: "..."} (Standort-Nachweis
als Betrugsschutz – fehlt/verweigert wird sichtbar protokolliert).
"""
import json
import os
import uuid
from datetime import date, datetime

from app import feiertage

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


def check_in(user, loc=None, ip=None, ort=None, dist=None, now=None,
             booking_id=None, apartment=None):
    """Check-in. Gibt None zurück, wenn bereits ein offener Eintrag existiert.

    loc: GPS-Dict. ip: öffentliche IP. ort: erkanntes Objekt (Geofence). dist: m.
    booking_id/apartment: optionale Kopplung an eine Smoobu-Buchung/Wohnung.
    """
    items = _read()
    if any(e["user"] == user and not e.get("checkout") for e in items):
        return None
    now = now or datetime.now()
    e = {"id": now.strftime("%Y%m%d%H%M%S") + "-" + user, "user": user,
         "checkin": now.isoformat(timespec="seconds"),
         "checkin_loc": loc, "checkin_ip": ip, "checkin_ort": ort, "checkin_dist": dist,
         "booking_id": booking_id, "apartment": apartment,
         "checkout": None, "checkout_loc": None, "checkout_ip": None,
         "checkout_ort": None, "checkout_dist": None}
    items.append(e)
    _write(items)
    return e


def check_out(user, loc=None, ip=None, ort=None, dist=None, now=None):
    """Offenen Eintrag des Benutzers schließen. None, wenn keiner offen ist."""
    items = _read()
    now = now or datetime.now()
    for e in reversed(items):
        if e["user"] == user and not e.get("checkout"):
            e["checkout"] = now.isoformat(timespec="seconds")
            e["checkout_loc"] = loc
            e["checkout_ip"] = ip
            e["checkout_ort"] = ort
            e["checkout_dist"] = dist
            _write(items)
            return e
    return None


def add_manual(user, checkin, checkout, booking_id=None, apartment=None):
    """Arbeitszeit nachträglich erfassen (fertiger Eintrag mit Start+Ende)."""
    items = _read()
    e = {"id": "m-" + uuid.uuid4().hex[:10], "user": user,
         "checkin": checkin.isoformat(timespec="seconds"),
         "checkin_loc": None, "checkin_ip": None, "checkin_ort": None, "checkin_dist": None,
         "booking_id": booking_id, "apartment": apartment, "manual": True,
         "checkout": checkout.isoformat(timespec="seconds"),
         "checkout_loc": None, "checkout_ip": None, "checkout_ort": None, "checkout_dist": None}
    items.append(e)
    _write(items)
    return e


def entries(user=None):
    items = _read()
    if user:
        items = [e for e in items if e["user"] == user]
    return list(reversed(items))   # neueste zuerst


def entries_for_booking(booking_id):
    bid = str(booking_id)
    return [e for e in reversed(_read()) if str(e.get("booking_id")) == bid]


def delete_for_booking(booking_id):
    """Alle Zeiteinträge dieser Buchung entfernen (Admin-Reset). Anzahl zurück."""
    items = _read()
    bid = str(booking_id)
    kept = [e for e in items if str(e.get("booking_id")) != bid]
    _write(kept)
    return len(items) - len(kept)


def get_entry(entry_id):
    return next((e for e in _read() if e["id"] == entry_id), None)


def update_entry(entry_id, checkin=None, checkout=None, apartment=None):
    """Zeiteintrag bearbeiten. checkin/checkout = datetime, apartment = Name/'' ."""
    items = _read()
    for e in items:
        if e["id"] == entry_id:
            if checkin is not None:
                e["checkin"] = checkin.isoformat(timespec="seconds")
            if checkout is not None:
                e["checkout"] = checkout.isoformat(timespec="seconds")
            if apartment is not None:
                e["apartment"] = apartment
            e["edited"] = datetime.now().isoformat(timespec="seconds")
    _write(items)


def delete_entry(entry_id):
    items = _read()
    kept = [e for e in items if e["id"] != entry_id]
    _write(kept)
    return len(items) != len(kept)


def duration_minutes(e):
    if not e.get("checkout"):
        return None
    a = datetime.fromisoformat(e["checkin"])
    b = datetime.fromisoformat(e["checkout"])
    return int((b - a).total_seconds() // 60)


# ------------------------------------------------- Abrechnungsstatus
def is_billed(e):
    """Wurde dieser Eintrag schon ans Steuerbüro gemeldet?"""
    return bool(e.get("abgerechnet"))


def mark_billed(entry_ids, by, when=None):
    """Einträge als 'abgerechnet' markieren. Gibt die Anzahl der Änderungen zurück.

    Ein bereits markierter Eintrag bleibt unangetastet – der ursprüngliche
    Zeitpunkt der Meldung soll erhalten bleiben.
    """
    ids = {str(i) for i in entry_ids}
    ts = (when or datetime.now()).isoformat(timespec="seconds")
    items = _read()
    n = 0
    for e in items:
        if str(e.get("id")) in ids and not e.get("abgerechnet"):
            e["abgerechnet"] = ts
            e["abgerechnet_von"] = by
            n += 1
    if n:
        _write(items)
    return n


def unmark_billed(entry_ids):
    """Markierung wieder entfernen (Korrektur einer versehentlichen Meldung)."""
    ids = {str(i) for i in entry_ids}
    items = _read()
    n = 0
    for e in items:
        if str(e.get("id")) in ids and e.get("abgerechnet"):
            e.pop("abgerechnet", None)
            e.pop("abgerechnet_von", None)
            n += 1
    if n:
        _write(items)
    return n


def summary(rows, user_cfg=None, defaults=None):
    """Kennzahlen einer Eintragsmenge (nur abgeschlossene Einträge zählen).

    Liefert Minuten, Einsätze, Schnitt, Aufteilung Werktag/Wochenende sowie die
    Trennung offen / abgerechnet – jeweils in Minuten, Anzahl und Betrag.
    """
    done = [e for e in rows if e.get("checkout")]
    out = {"minutes": 0, "count": len(done), "avg_minutes": 0,
           "minutes_werktag": 0, "minutes_wochenende": 0, "amount": 0.0,
           "billed_minutes": 0, "billed_count": 0, "billed_amount": 0.0,
           "open_minutes": 0, "open_count": 0, "open_amount": 0.0,
           "apartments": set(), "last_date": None}
    for e in done:
        mins = duration_minutes(e) or 0
        kind = kind_of(e)
        betrag = amount(mins, rate_for(kind, user_cfg, defaults))
        out["minutes"] += mins
        out["amount"] += betrag
        if kind == feiertage.WOCHENENDE:
            out["minutes_wochenende"] += mins
        else:
            out["minutes_werktag"] += mins
        ziel = "billed" if is_billed(e) else "open"
        out[f"{ziel}_minutes"] += mins
        out[f"{ziel}_count"] += 1
        out[f"{ziel}_amount"] += betrag
        if e.get("apartment"):
            out["apartments"].add(e["apartment"])
        d = entry_date(e)
        if out["last_date"] is None or d > out["last_date"]:
            out["last_date"] = d
    out["amount"] = round(out["amount"], 2)
    out["billed_amount"] = round(out["billed_amount"], 2)
    out["open_amount"] = round(out["open_amount"], 2)
    out["avg_minutes"] = int(out["minutes"] / out["count"]) if out["count"] else 0
    return out


def fmt_dur(mins):
    if mins is None:
        return "läuft…"
    return f"{mins // 60}:{mins % 60:02d} h"


# ------------------------------------------------- Tagesart & Vergütung
def entry_date(e):
    """Datum des Eintrags = Tag des Check-in. Ein über Mitternacht laufender
    Einsatz zählt damit vollständig zum Anfangstag."""
    return date.fromisoformat(e["checkin"][:10])


def kind_of(e):
    """feiertage.WERKTAG oder feiertage.WOCHENENDE für einen Zeiteintrag."""
    return feiertage.kind_of(entry_date(e))


def _num(v):
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def rate_for(kind, user_cfg, defaults=None):
    """Stundensatz (€/h) für eine Tagesart.

    Der Wochenend-/Feiertagssatz greift nur, wenn er beim Mitarbeiter aktiviert
    und gesetzt ist – sonst gilt überall der Werktagssatz. Fehlt beim
    Mitarbeiter ein Wert, kommt der globale Vorgabewert zum Zug.
    """
    user_cfg = user_cfg or {}
    defaults = defaults or {}

    def pick(key):
        v = user_cfg.get(key)
        if v in (None, ""):
            v = defaults.get(key)
        return _num(v)

    if kind == feiertage.WOCHENENDE and user_cfg.get("wochenendsatz_aktiv"):
        r = pick("stundensatz_wochenende")
        if r:
            return r
    return pick("stundensatz_werktag")


def amount(minutes, rate):
    """Betrag in € für Minuten zum Stundensatz, kaufmännisch auf Cent gerundet."""
    return round((minutes or 0) / 60.0 * _num(rate), 2)


def aggregate(rows, users=None, defaults=None):
    """Zeiten je Mitarbeiter nach Tagesart summieren.

    rows: abgeschlossene Einträge. users: {username: user_cfg} für die Sätze.
    Rückgabe je Mitarbeiter: minutes/amount/rate je Tagesart plus Summen.
    """
    users = users or {}
    out = {}
    for e in rows:
        mins = duration_minutes(e) or 0
        u = e["user"]
        slot = out.setdefault(u, {
            "minutes": {feiertage.WERKTAG: 0, feiertage.WOCHENENDE: 0},
            "amount": {feiertage.WERKTAG: 0.0, feiertage.WOCHENENDE: 0.0},
            "rate": {k: rate_for(k, users.get(u), defaults)
                     for k in (feiertage.WERKTAG, feiertage.WOCHENENDE)},
            "total_minutes": 0, "total_amount": 0.0,
        })
        k = kind_of(e)
        slot["minutes"][k] += mins
        slot["total_minutes"] += mins
    for slot in out.values():
        for k, mins in slot["minutes"].items():
            slot["amount"][k] = amount(mins, slot["rate"][k])
        slot["total_amount"] = round(sum(slot["amount"].values()), 2)
    return out
