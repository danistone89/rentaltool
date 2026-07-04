#!/usr/bin/env python3
"""Belege/Rechnungen: Upload durch Mitarbeiter, chronologische Ablage, OCR.

Fotos werden über housekeeping.save_photo unter media/beleg/ gespeichert (+ Spiegel
nach Nextcloud). Metadaten je Beleg in receipts.json (gitignored, betrieblich).
OCR über die Tesseract-CLI (best-effort; ohne Tesseract bleibt der Text leer).
"""
import json
import os
import re
import shutil
import subprocess
from datetime import datetime

from app import housekeeping

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECEIPTS = os.path.join(HERE, "receipts.json")

_EDITABLE = {"merchant", "amount", "note", "kategorie"}
_KNOWN_MERCHANTS = ["ALDI", "LIDL", "REWE", "EDEKA", "KAUFLAND", "PENNY", "NETTO",
                    "ROSSMANN", "IKEA", "OBI", "BAUHAUS", "HORNBACH", "METRO",
                    "TEDI", "ACTION", "MÜLLER", "MEDIAMARKT", "SATURN", "AMAZON",
                    "DM"]


def _read():
    if os.path.exists(RECEIPTS):
        with open(RECEIPTS, encoding="utf-8") as f:
            return json.load(f)
    return []


def _write(items):
    with open(RECEIPTS, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def add_receipt(uploader, photo, ocr_text="", amount="", merchant="", note="", kategorie=""):
    items = _read()
    r = {"id": housekeeping._uid(), "uploader": uploader, "ts": now_iso(),
         "photo": photo, "ocr_text": ocr_text or "", "amount": amount or "",
         "merchant": merchant or "", "note": note or "", "kategorie": kategorie or ""}
    items.append(r)
    _write(items)
    return r


def list_receipts(limit=500):
    return list(reversed(_read()))[:limit]


def update_receipt(receipt_id, **fields):
    items = _read()
    for r in items:
        if r["id"] == receipt_id:
            for k, v in fields.items():
                if k in _EDITABLE:
                    r[k] = v
    _write(items)


def delete_receipt(receipt_id):
    """Beleg-Eintrag + lokale Bilddatei entfernen (Nextcloud-Spiegel bleibt Archiv)."""
    items = _read()
    keep, gone = [], None
    for r in items:
        if r["id"] == receipt_id:
            gone = r
        else:
            keep.append(r)
    if gone:
        _write(keep)
        try:
            p = os.path.join(housekeeping.MEDIA_DIR, gone.get("photo", ""))
            if gone.get("photo") and os.path.exists(p):
                os.remove(p)
        except Exception:
            pass
    return gone


# ------------------------------------------------------------------ OCR
def ocr_available():
    return shutil.which("tesseract") is not None


def ocr_image(path, lang="deu"):
    """Text aus einem Beleg-Bild lesen (Tesseract-CLI). Leerer String bei Fehler."""
    if not shutil.which("tesseract") or not os.path.exists(path):
        return ""
    try:
        out = subprocess.run(["tesseract", path, "stdout", "-l", lang],
                             capture_output=True, timeout=90)
        return out.stdout.decode("utf-8", "replace").strip()
    except Exception:
        try:  # ohne deutsches Sprachpaket erneut versuchen
            out = subprocess.run(["tesseract", path, "stdout"],
                                 capture_output=True, timeout=90)
            return out.stdout.decode("utf-8", "replace").strip()
        except Exception:
            return ""


_MONEY = re.compile(r"(\d{1,4}[.,]\d{2})")


def guess_amount(text):
    if not text:
        return ""
    lines = text.splitlines()
    for kw in ("summe", "gesamt", "zu zahlen", "total", "betrag", "eur", "€"):
        for ln in lines:
            if kw in ln.lower():
                m = _MONEY.findall(ln)
                if m:
                    return m[-1].replace(".", ",")
    allm = _MONEY.findall(text)
    if allm:
        def _val(x):
            return float(x.replace(".", "").replace(",", "."))
        return max(allm, key=_val).replace(".", ",")
    return ""


def guess_merchant(text):
    up = (text or "").upper()
    for k in _KNOWN_MERCHANTS:
        if k in up:
            return "dm" if k == "DM" else k.capitalize()
    for ln in (text or "").splitlines():
        s = ln.strip()
        if len(s) >= 3:
            return s[:40]
    return ""
