#!/usr/bin/env python3
"""Reinigung & Qualität: Checklisten, Fotonachweis, Schäden, Bestand.

Datenhaltung in JSON-Dateien (gitignored, betrieblich/personenbezogen), Fotos
unter media/. Je Apartment: Checkliste (Räume→Aufgaben, Soll-Foto) + Bestandsliste.
Reinigungsdurchgänge, Schadensmeldungen und Nachkauf-Wünsche werden protokolliert.
"""
import json
import os
import shutil
import uuid
from datetime import datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = HERE
MEDIA_DIR = os.path.join(HERE, "media")

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
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def _write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


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
    all_cl = _read(CHECKLISTS, {})
    key = str(apt_id)
    if key not in all_cl:
        all_cl[key] = {"rooms": [
            {"name": rn, "tasks": [{"id": _uid(), "text": t, "ref_photo": None} for t in tasks]}
            for rn, tasks in DEFAULT_ROOMS]}
        _write(CHECKLISTS, all_cl)
    return all_cl[key]


def save_checklist(apt_id, checklist):
    all_cl = _read(CHECKLISTS, {})
    all_cl[str(apt_id)] = checklist
    _write(CHECKLISTS, all_cl)


def set_task_ref_photo(apt_id, task_id, rel_photo):
    cl = get_checklist(apt_id)
    for room in cl["rooms"]:
        for t in room["tasks"]:
            if t["id"] == task_id:
                t["ref_photo"] = rel_photo
    save_checklist(apt_id, cl)


# ------------------------------------------------------------- Bestand (Vorlage)
def get_inventory(apt_id):
    all_inv = _read(INVENTORY, {})
    key = str(apt_id)
    if key not in all_inv:
        all_inv[key] = [{"id": _uid(), "name": n, "kategorie": k} for n, k in DEFAULT_INVENTORY]
        _write(INVENTORY, all_inv)
    return all_inv[key]


def save_inventory(apt_id, items):
    all_inv = _read(INVENTORY, {})
    all_inv[str(apt_id)] = items
    _write(INVENTORY, all_inv)


# ------------------------------------------------------------- Durchgänge
def get_open_run(apt_id, user):
    for r in _read(CLEANINGS, []):
        if str(r["apartment_id"]) == str(apt_id) and r["user"] == user and not r.get("finished"):
            return r
    return None


def start_run(apt_id, apt_name, user):
    runs = _read(CLEANINGS, [])
    ex = next((r for r in runs if str(r["apartment_id"]) == str(apt_id)
               and r["user"] == user and not r.get("finished")), None)
    if ex:
        return ex
    r = {"id": _uid(), "apartment_id": apt_id, "apartment_name": apt_name, "user": user,
         "started": now_iso(), "finished": None, "tasks": {}}
    runs.append(r)
    _write(CLEANINGS, runs)
    return r


def update_task(run_id, task_id, done=None, ist_photo=None):
    runs = _read(CLEANINGS, [])
    for r in runs:
        if r["id"] == run_id:
            t = r["tasks"].setdefault(task_id, {"done": False, "ist_photo": None})
            if done is not None:
                t["done"] = done
            if ist_photo is not None:
                t["ist_photo"] = ist_photo
    _write(CLEANINGS, runs)


def finish_run(run_id):
    runs = _read(CLEANINGS, [])
    for r in runs:
        if r["id"] == run_id:
            r["finished"] = now_iso()
    _write(CLEANINGS, runs)


def list_runs(limit=100):
    return list(reversed(_read(CLEANINGS, [])))[:limit]


# ------------------------------------------------------------- Schäden
def add_damage(apt_id, apt_name, room, desc, urgency, photo, reporter):
    items = _read(DAMAGES, [])
    d = {"id": _uid(), "apartment_id": apt_id, "apartment_name": apt_name, "room": room,
         "desc": desc, "urgency": urgency, "photo": photo, "reporter": reporter,
         "ts": now_iso(), "status": "offen"}
    items.append(d)
    _write(DAMAGES, items)
    return d


def list_damages(only_open=False):
    items = list(reversed(_read(DAMAGES, [])))
    return [d for d in items if d["status"] == "offen"] if only_open else items


def set_damage_status(damage_id, status):
    items = _read(DAMAGES, [])
    for d in items:
        if d["id"] == damage_id:
            d["status"] = status
    _write(DAMAGES, items)


# ------------------------------------------------------------- Nachkauf/Bestand
def add_restock(apt_id, apt_name, item, menge, kategorie, reporter):
    items = _read(RESTOCK, [])
    r = {"id": _uid(), "apartment_id": apt_id, "apartment_name": apt_name, "item": item,
         "menge": menge, "kategorie": kategorie, "reporter": reporter,
         "ts": now_iso(), "status": "offen"}
    items.append(r)
    _write(RESTOCK, items)
    return r


def list_restock(only_open=True):
    items = list(reversed(_read(RESTOCK, [])))
    return [r for r in items if r["status"] == "offen"] if only_open else items


def set_restock_status(restock_id, status):
    items = _read(RESTOCK, [])
    for r in items:
        if r["id"] == restock_id:
            r["status"] = status
    _write(RESTOCK, items)
