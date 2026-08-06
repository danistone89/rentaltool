#!/usr/bin/env python3
"""Reinigung & Qualität: Checklisten, Fotonachweis, Schäden, Bestand.

Datenhaltung in den Tabellen `checklisten`, `bestand`, `durchgaenge`, `schaeden`
und `nachkauf` (siehe app/db.py), Fotos als Dateien unter media/. Je Apartment:
Checkliste (Räume→Aufgaben, Soll-Foto) + Bestandsliste. Reinigungsdurchgänge,
Schadensmeldungen und Nachkauf-Wünsche werden protokolliert.
"""
import os
import shutil
import uuid
from datetime import datetime

from app import db, paths

HERE = paths.ROOT
DATA = paths.DATA_DIR
MEDIA_DIR = paths.p("media")

CHECKLISTS = "checklisten"
INVENTORY = "bestand"
CLEANINGS = "durchgaenge"
DAMAGES = "schaeden"
RESTOCK = "nachkauf"

DEFAULT_ROOMS = [
    ("Bad", ["Dusche/Wanne reinigen", "WC reinigen", "Waschbecken & Spiegel",
             "Handtücher wechseln", "Boden wischen"]),
    ("Küche", ["Arbeitsflächen", "Spüle", "Kühlschrank leeren/prüfen",
               "Herd/Backofen", "Müll leeren", "Boden wischen"]),
    ("Schlafzimmer", ["Bettwäsche wechseln", "Bett machen", "Staub wischen", "Boden saugen"]),
    ("Wohnbereich", ["Oberflächen abwischen", "Staub wischen", "Boden saugen/wischen", "Lüften"]),
    ("Allgemein", ["Fenster prüfen", "Willkommensmappe auffüllen", "Endkontrolle"]),
]
DEFAULT_INVENTORY = [
    ("Toilettenpapier", "verbrauch"), ("Küchenrolle", "verbrauch"),
    ("Spülmittel", "verbrauch"), ("Handseife", "verbrauch"), ("Kaffee", "verbrauch"),
    ("Dusch­gel/Shampoo", "verbrauch"), ("Müllbeutel", "verbrauch"),
    ("Handtücher", "waesche"), ("Bettwäsche-Set", "waesche"), ("Geschirrtücher", "waesche"),
]


def _uid():
    return uuid.uuid4().hex[:10]


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _status_setzen(tabelle, sid, status):
    with db.transaktion():
        satz = db.holen(tabelle, sid)
        if satz is None:
            return
        satz["status"] = status
        db.speichern(tabelle, sid, satz)


# ------------------------------------------------------------- Medien (Fotos)
def save_photo(kind, data, ext="jpg", mirror_dir=None):
    """Foto-Bytes speichern; gibt den relativen Dateinamen (kind/uid.ext) zurück."""
    os.makedirs(os.path.join(MEDIA_DIR, kind), exist_ok=True)
    rel = f"{kind}/{_uid()}.{ext}"
    path = os.path.join(MEDIA_DIR, rel)
    with open(path, "wb") as f:
        f.write(data)
    if mirror_dir:
        try:
            dst = os.path.join(mirror_dir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(path, dst)
        except Exception:
            pass
    return rel


# ------------------------------------------------------------- Checklisten
def get_checklist(apt_id):
    """Checkliste eines Apartments; legt bei Bedarf eine Standardvorlage an."""
    key = str(apt_id)
    with db.transaktion():
        cl = db.holen(CHECKLISTS, key)
        if cl is None:
            cl = {"rooms": [
                {"name": rn, "tasks": [{"id": _uid(), "text": txt, "ref_photo": None} for txt in tasks]}
                for rn, tasks in DEFAULT_ROOMS]}
            db.anlegen(CHECKLISTS, cl, sid=key)
        return cl


def save_checklist(apt_id, checklist):
    db.speichern(CHECKLISTS, apt_id, checklist)


def set_task_ref_photo(apt_id, task_id, rel_photo):
    cl = get_checklist(apt_id)
    for room in cl["rooms"]:
        for task in room["tasks"]:
            if task["id"] == task_id:
                task["ref_photo"] = rel_photo
    save_checklist(apt_id, cl)


# ------------------------------------------------------------- Bestand (Vorlage)
def get_inventory(apt_id):
    key = str(apt_id)
    with db.transaktion():
        satz = db.holen(INVENTORY, key)
        if satz is None:
            satz = {"items": [{"id": _uid(), "name": n, "kategorie": k}
                              for n, k in DEFAULT_INVENTORY]}
            db.anlegen(INVENTORY, satz, sid=key)
        return satz["items"]


def save_inventory(apt_id, items):
    # Eine Zeile speichert immer ein Objekt – die Liste steckt deshalb unter
    # "items" statt direkt in der Zeile.
    db.speichern(INVENTORY, apt_id, {"items": items})


# ------------------------------------------------------------- Durchgänge
def get_open_run(apt_id, user):
    for r in db.finden(CLEANINGS, benutzer=user, fertig=None):
        if str(r["apartment_id"]) == str(apt_id):
            return r
    return None


def start_run(apt_id, apt_name, user):
    with db.transaktion():
        ex = get_open_run(apt_id, user)
        if ex:
            return ex
        r = {"id": _uid(), "apartment_id": apt_id, "apartment_name": apt_name,
             "user": user, "started": now_iso(), "finished": None, "tasks": {}}
        db.anlegen(CLEANINGS, r)
    return r


def update_task(run_id, task_id, done=None, ist_photo=None):
    with db.transaktion():
        r = db.holen(CLEANINGS, run_id)
        if r is None:
            return
        t = r["tasks"].setdefault(task_id, {"done": False, "ist_photo": None})
        if done is not None:
            t["done"] = done
        if ist_photo is not None:
            t["ist_photo"] = ist_photo
        db.speichern(CLEANINGS, run_id, r)


def finish_run(run_id):
    with db.transaktion():
        r = db.holen(CLEANINGS, run_id)
        if r is None:
            return
        r["finished"] = now_iso()
        db.speichern(CLEANINGS, run_id, r)


def get_run(run_id):
    return db.holen(CLEANINGS, run_id)


def list_runs(limit=100):
    return db.alle(CLEANINGS, neueste_zuerst=True)[:limit]


# ------------------------------------------------------------- Schäden
def add_damage(apt_id, apt_name, room, desc, urgency, photo, reporter, booking_id=None):
    d = {"id": _uid(), "apartment_id": apt_id, "apartment_name": apt_name, "room": room,
         "desc": desc, "urgency": urgency, "photo": photo, "reporter": reporter,
         "booking_id": booking_id, "ts": now_iso(), "status": "offen"}
    db.anlegen(DAMAGES, d)
    return d


def list_damages(only_open=False):
    if only_open:
        return db.finden(DAMAGES, neueste_zuerst=True, status="offen")
    return db.alle(DAMAGES, neueste_zuerst=True)


def damages_for_booking(booking_id):
    bid = str(booking_id)
    return [d for d in list_damages() if str(d.get("booking_id")) == bid]


def set_damage_status(damage_id, status):
    _status_setzen(DAMAGES, damage_id, status)


# ------------------------------------------------------------- Nachkauf/Bestand
def add_restock(apt_id, apt_name, item, menge, kategorie, reporter, booking_id=None):
    r = {"id": _uid(), "apartment_id": apt_id, "apartment_name": apt_name, "item": item,
         "menge": menge, "kategorie": kategorie, "reporter": reporter,
         "booking_id": booking_id, "ts": now_iso(), "status": "offen"}
    db.anlegen(RESTOCK, r)
    return r


def list_restock(only_open=True):
    if only_open:
        return db.finden(RESTOCK, neueste_zuerst=True, status="offen")
    return db.alle(RESTOCK, neueste_zuerst=True)


def restock_for_booking(booking_id):
    bid = str(booking_id)
    return [r for r in list_restock(only_open=False) if str(r.get("booking_id")) == bid]


def set_restock_status(restock_id, status):
    _status_setzen(RESTOCK, restock_id, status)
