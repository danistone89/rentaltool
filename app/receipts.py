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

_EDITABLE = {"merchant", "amount", "note", "kategorie", "apartment_id", "apartment_name"}
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


def add_receipt(uploader, photo, ocr_text="", amount="", merchant="", note="",
                kategorie="", pdf=None, apartment_id=None, apartment_name=""):
    items = _read()
    r = {"id": housekeeping._uid(), "uploader": uploader, "ts": now_iso(),
         "photo": photo, "pdf": pdf, "apartment_id": apartment_id,
         "apartment_name": apartment_name or "", "ocr_text": ocr_text or "",
         "amount": amount or "", "merchant": merchant or "", "note": note or "",
         "kategorie": kategorie or ""}
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
        for rel in (gone.get("photo"), gone.get("pdf")):
            try:
                if rel:
                    p = os.path.join(housekeeping.MEDIA_DIR, rel)
                    if os.path.exists(p):
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


# ------------------------------------------------------------ Dokument -> PDF
def _order_pts(pts):
    import numpy as np
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]      # oben-links
    rect[2] = pts[np.argmax(s)]      # unten-rechts
    d = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(d)]      # oben-rechts
    rect[3] = pts[np.argmax(d)]      # unten-links
    return rect


def autocrop(src_path, dst_path):
    """Dokument-Ränder erkennen und perspektivisch zuschneiden. True bei Erfolg
    (schreibt dst_path); False, wenn kein Dokument erkennbar oder OpenCV fehlt."""
    try:
        import cv2
        import numpy as np
    except Exception:
        return False
    img = cv2.imread(src_path)
    if img is None or img.shape[0] < 300:
        return False
    ratio = img.shape[0] / 500.0
    small = cv2.resize(img, (int(img.shape[1] / ratio), 500))
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = cv2.Canny(gray, 60, 200)
    edged = cv2.dilate(edged, None, iterations=1)
    cnts, _ = cv2.findContours(edged.copy(), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    cnts = sorted(cnts, key=cv2.contourArea, reverse=True)[:6]
    area_small = small.shape[0] * small.shape[1]
    doc = None
    for c in cnts:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4 and cv2.contourArea(c) > 0.2 * area_small:
            doc = approx
            break
    if doc is None:
        return False
    rect = _order_pts(doc.reshape(4, 2).astype("float32") * ratio)
    (tl, tr, br, bl) = rect
    maxW = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    maxH = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    if maxW < 200 or maxH < 200:
        return False
    dst = np.array([[0, 0], [maxW - 1, 0], [maxW - 1, maxH - 1], [0, maxH - 1]],
                   dtype="float32")
    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(img, M, (maxW, maxH))
    cv2.imwrite(dst_path, warped)
    return True


def image_to_pdf(img_path, pdf_path, page="a4"):
    """Bild -> PDF (PyMuPDF). True bei Erfolg.

    Das Bild wird seitenverhältnistreu auf eine A4-Seite eingepasst und zentriert,
    damit das Ergebnis wie ein echter Scan aussieht und sich normal ausdrucken
    lässt. Schlägt das fehl, wird auf eine Seite in Bildgröße zurückgefallen.
    """
    try:
        import fitz
    except Exception:
        return False
    try:
        src = fitz.open(img_path)
        rect = src[0].rect
        if page and rect.width and rect.height:
            pw, ph = fitz.paper_size(page)
            if rect.width > rect.height:      # Querformat -> Seite drehen
                pw, ph = ph, pw
            margin = 18                        # ca. 6 mm Rand
            box = fitz.Rect(margin, margin, pw - margin, ph - margin)
            scale = min(box.width / rect.width, box.height / rect.height)
            w, h = rect.width * scale, rect.height * scale
            x = (pw - w) / 2
            y = (ph - h) / 2
            out = fitz.open()
            out.new_page(width=pw, height=ph).insert_image(
                fitz.Rect(x, y, x + w, y + h), filename=img_path)
            out.save(pdf_path)
            out.close()
            src.close()
            return True
        pdf_bytes = src.convert_to_pdf()
        src.close()
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)
        return True
    except Exception:
        try:                                   # Rückfall: Seite in Bildgröße
            src = fitz.open(img_path)
            pdf_bytes = src.convert_to_pdf()
            src.close()
            with open(pdf_path, "wb") as f:
                f.write(pdf_bytes)
            return True
        except Exception:
            return False


def save_document(data, ext, mirror_dir=None, crop=True):
    """Beleg-Bytes speichern, Dokument (optional) automatisch zuschneiden und als PDF
    ablegen. crop=False, wenn der Client (Scanner) bereits zugeschnitten hat.
    Gibt {'photo': rel_jpg, 'pdf': rel_pdf|None} zurück (+ Spiegelung nach mirror_dir)."""
    uid = housekeeping._uid()
    base = os.path.join(housekeeping.MEDIA_DIR, "beleg")
    os.makedirs(base, exist_ok=True)
    orig_rel = f"beleg/{uid}.{ext}"
    orig_path = os.path.join(housekeeping.MEDIA_DIR, orig_rel)
    with open(orig_path, "wb") as f:
        f.write(data)

    img_rel = orig_rel
    if crop:
        crop_rel = f"beleg/{uid}_doc.jpg"
        crop_path = os.path.join(housekeeping.MEDIA_DIR, crop_rel)
        try:
            if autocrop(orig_path, crop_path):
                img_rel = crop_rel
        except Exception:
            pass

    pdf_rel = f"beleg/{uid}.pdf"
    if not image_to_pdf(os.path.join(housekeeping.MEDIA_DIR, img_rel),
                        os.path.join(housekeeping.MEDIA_DIR, pdf_rel)):
        pdf_rel = None

    if mirror_dir:
        for rel in [img_rel] + ([pdf_rel] if pdf_rel else []):
            try:
                dst = os.path.join(mirror_dir, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(os.path.join(housekeeping.MEDIA_DIR, rel), dst)
            except Exception:
                pass
    return {"photo": img_rel, "pdf": pdf_rel}


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
