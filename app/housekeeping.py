#!/usr/bin/env python3
"""Reinigung & Qualität: Checklisten, Fotonachweis, Schäden, Bestand.

Datenhaltung in JSON-Dateien (gitignored, betrieblich/personenbezogen), Fotos
unter media/. Je Apartment: Checkliste (Räume→Aufgaben, Soll-Foto) + Bestandsliste.
Reinigungsdurchgänge, Schadensmeldungen und Nachkauf-Wünsche werden protokolliert.
"""
import os
import shutil
import uuid
from datetime import datetime

from app import paths, store

HERE = paths.ROOT
DATA = paths.DATA_DIR
MEDIA_DIR = paths.p("media")

CHECKLISTS = os.path.join(DATA, "checklists.json")
INVENTORY = os.path.join(DATA, "inventory.json")
CLEANINGS = os.path.join(DATA, "cleanings.json")
DAMAGES = os.path.join(DATA, "damages.json")
RESTOCK = os.path.join(DATA, "restock.json")

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


def _read(path, default):
    return store.read(path, default)


def _write(path, obj):
    store.write(path, obj)


def _aendern(path, default):
    """Datei unter Sperre lesen, ändern, zurückschreiben (siehe app/store.py)."""
    return store.edit(path, default)


def _uid():
    return uuid.uuid4().hex[:10]


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


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
    with _aendern(CHECKLISTS, {}) as a:
        if key not in a.wert:
            a.wert[key] = {"rooms": [
                {"name": rn, "tasks": [{"id": _uid(), "text": txt, "ref_photo": None} for txt in tasks]}
                for rn, tasks in DEFAULT_ROOMS]}
        else:
            a.verwerfen()
        return a.wert[key]


def save_checklist(apt_id, checklist):
    with _aendern(CHECKLISTS, {}) as a:
        a.wert[str(apt_id)] = checklist


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
    with _aendern(INVENTORY, {}) as a:
        if key not in a.wert:
            a.wert[key] = [{"id": _uid(), "name": n, "kategorie": k}
                           for n, k in DEFAULT_INVENTORY]
        else:
            a.verwerfen()
        return a.wert[key]


def save_inventory(apt_id, items):
    with _aendern(INVENTORY, {}) as a:
        a.wert[str(apt_id)] = items


# ------------------------------------------------------------- Durchgänge
def get_open_run(apt_id, user):
    for r in _read(CLEANINGS, []):
        if str(r["apartment_id"]) == str(apt_id) and r["user"] == user and not r.get("finished"):
            return r
    return None


def start_run(apt_id, apt_name, user):
    with _aendern(CLEANINGS, []) as a:
        ex = next((r for r in a.wert if str(r["apartment_id"]) == str(apt_id)
                   and r["user"] == user and not r.get("finished")), None)
        if ex:
            a.verwerfen()
            return ex
        r = {"id": _uid(), "apartment_id": apt_id, "apartment_name": apt_name,
             "user": user, "started": now_iso(), "finished": None, "tasks": {}}
        a.wert.append(r)
    return r


def update_task(run_id, task_id, done=None, ist_photo=None):
    with _aendern(CLEANINGS, []) as a:
        for r in a.wert:
            if r["id"] == run_id:
                t = r["tasks"].setdefault(task_id, {"done": False, "ist_photo": None})
                if done is not None:
                    t["done"] = done
                if ist_photo is not None:
                    t["ist_photo"] = ist_photo


def finish_run(run_id):
    with _aendern(CLEANINGS, []) as a:
        for r in a.wert:
            if r["id"] == run_id:
                r["finished"] = now_iso()


def list_runs(limit=100):
    return list(reversed(_read(CLEANINGS, [])))[:limit]


# ------------------------------------------------------------- Schäden
def add_damage(apt_id, apt_name, room, desc, urgency, photo, reporter, booking_id=None):
    d = {"id": _uid(), "apartment_id": apt_id, "apartment_name": apt_name, "room": room,
         "desc": desc, "urgency": urgency, "photo": photo, "reporter": reporter,
         "booking_id": booking_id, "ts": now_iso(), "status": "offen"}
    with _aendern(DAMAGES, []) as a:
        a.wert.append(d)
    return d


def list_damages(only_open=False):
    items = list(reversed(_read(DAMAGES, [])))
    return [d for d in items if d["status"] == "offen"] if only_open else items


def damages_for_booking(booking_id):
    bid = str(booking_id)
    return [d for d in list_damages() if str(d.get("booking_id")) == bid]


def set_damage_status(damage_id, status):
    with _aendern(DAMAGES, []) as a:
        for d in a.wert:
            if d["id"] == damage_id:
                d["status"] = status


# ------------------------------------------------------------- Nachkauf/Bestand
def add_restock(apt_id, apt_name, item, menge, kategorie, reporter, booking_id=None):
    r = {"id": _uid(), "apartment_id": apt_id, "apartment_name": apt_name, "item": item,
         "menge": menge, "kategorie": kategorie, "reporter": reporter,
         "booking_id": booking_id, "ts": now_iso(), "status": "offen"}
    with _aendern(RESTOCK, []) as a:
        a.wert.append(r)
    return r


def list_restock(only_open=True):
    items = list(reversed(_read(RESTOCK, [])))
    return [r for r in items if r["status"] == "offen"] if only_open else items


def restock_for_booking(booking_id):
    bid = str(booking_id)
    return [r for r in list_restock(only_open=False) if str(r.get("booking_id")) == bid]


def set_restock_status(restock_id, status):
    with _aendern(RESTOCK, []) as a:
        for r in a.wert:
            if r["id"] == restock_id:
                r["status"] = status
