#!/usr/bin/env python3
"""Belege/Rechnungen: Upload durch Mitarbeiter, chronologische Ablage, OCR.

Fotos werden über housekeeping.save_photo unter media/beleg/ gespeichert (+ Spiegel
nach Nextcloud). Metadaten je Beleg in der Tabelle `belege` (siehe app/db.py).
OCR über die Tesseract-CLI (best-effort; ohne Tesseract bleibt der Text leer).
"""
import os
import re
import shutil
import subprocess
from datetime import datetime

from app import db, housekeeping, paths

HERE = paths.ROOT
TABELLE = "belege"

# `datum` ist das Belegdatum und NICHT `ts` (der Upload). Ein Beleg vom 29.,
# der am 2. fotografiert wird, gehoert in den alten Monat – siehe
# buchhaltung.belegdatum().
_EDITABLE = {"merchant", "amount", "note", "kategorie", "klasse", "datum",
             "apartment_id", "apartment_name", "kreditor_id"}
_KNOWN_MERCHANTS = ["ALDI", "LIDL", "REWE", "EDEKA", "KAUFLAND", "PENNY", "NETTO",
                    "ROSSMANN", "IKEA", "OBI", "BAUHAUS", "HORNBACH", "METRO",
                    "TEDI", "ACTION", "MÜLLER", "MEDIAMARKT", "SATURN", "AMAZON",
                    "DM"]


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def add_receipt(uploader, photo, ocr_text="", amount="", merchant="", note="",
                kategorie="", pdf=None, apartment_id=None, apartment_name=""):
    r = {"id": housekeeping._uid(), "uploader": uploader, "ts": now_iso(),
         "photo": photo, "pdf": pdf, "apartment_id": apartment_id,
         "apartment_name": apartment_name or "", "ocr_text": ocr_text or "",
         "amount": amount or "", "merchant": merchant or "", "note": note or "",
         "kategorie": kategorie or ""}
    db.anlegen(TABELLE, r)
    return r


def list_receipts(limit=500):
    return db.alle(TABELLE, neueste_zuerst=True)[:limit]


def update_receipt(receipt_id, von_hand=False, **fields):
    """Felder eines Belegs setzen.

    `von_hand=True` merkt sich, welche Felder ein Mensch gepflegt hat. Das
    Nachlesen (`nachlesen`) laesst diese Felder danach in Ruhe – sonst naehme
    ein spaeterer Lauf jede Korrektur wieder zurueck.
    """
    with db.transaktion():
        r = db.holen(TABELLE, receipt_id)
        if r is None:
            return
        for k, v in fields.items():
            if k in _EDITABLE:
                r[k] = v
                if von_hand:
                    r["hand"] = sorted(set(r.get("hand") or []) | {k})
        db.speichern(TABELLE, receipt_id, r)


def nachlesen(eigene=None, belege=None):
    """Haendler und Betrag aus dem gespeicherten Text neu bestimmen – als
    **Vorschlag**, noch ohne zu schreiben.

    **Warum das noetig ist.** Die alte Erkennung lag oft daneben (siehe
    `guess_merchant`). Wer schon Belege hochgeladen hat – am 8.8.2026 waren es
    31 –, muesste sie sonst alle von Hand berichtigen.

    Zurueck kommt je Beleg ein Satz mit `alt` und `neu`, damit der Mensch vor
    dem Schreiben sieht, was sich aendert. Ein Nachlesen, das stillschweigend
    31 Datensaetze umschreibt, waere nicht nachvollziehbar.

    **Von Hand gepflegte Felder bleiben unangetastet.**
    """
    raus = []
    for r in (belege if belege is not None else list_receipts(100000)):
        text = r.get("ocr_text") or ""
        if not text.strip():
            continue
        hand = set(r.get("hand") or [])
        alt_m, alt_a = r.get("merchant") or "", r.get("amount") or ""
        neu_m = alt_m if "merchant" in hand else (guess_merchant(text, eigene) or alt_m)
        neu_a = alt_a if "amount" in hand else (guess_amount(text) or alt_a)
        if (neu_m, neu_a) != (alt_m, alt_a):
            raus.append({"beleg": r, "alt": (alt_m, alt_a), "neu": (neu_m, neu_a)})
    return raus


def uebernehmen(aenderungen):
    """Vorgeschlagene Aenderungen schreiben. Gibt die Anzahl zurueck."""
    n = 0
    for a in aenderungen:
        update_receipt(a["beleg"]["id"], merchant=a["neu"][0], amount=a["neu"][1])
        n += 1
    return n


def delete_receipt(receipt_id):
    """Beleg-Eintrag + lokale Bilddatei entfernen (Nextcloud-Spiegel bleibt Archiv)."""
    with db.transaktion():
        gone = db.holen(TABELLE, receipt_id)
        if gone:
            db.loeschen(TABELLE, receipt_id)
    if gone:
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


# Ein Geldbetrag – aber NICHT als Teil eines Datums. „31.12.2026" lieferte
# vorher den Betrag „31,12"; an den echten Belegen war das der haeufigste
# Fehler. Die Ausschluesse: keine Ziffer davor mit Punkt (Tag.Monat), keine
# Ziffer dahinter mit Punkt (Monat.Jahr), keine weitere Ziffer direkt daneben.
_MONEY = re.compile(r"(?<![\d.,])(\d{1,4}[.,]\d{2})(?![\d.,])")

# Wonach der Endbetrag benannt ist – von der staerksten Aussage abwaerts.
_SUMMENWORT = ("zu zahlen", "zahlbetrag", "rechnungsbetrag", "gesamtbetrag",
               "gesamtsumme", "endbetrag", "summe", "gesamt", "total",
               # Ganz zum Schluss das schwaechste Wort: „Den Betrag von 8,79 EUR
               # buchen wir ab" ist die einzige Betragsangabe mancher Rechnung.
               "betrag")

# Zeilen, die zwar einen Betrag tragen, aber nie den Endbetrag: der Nettoanteil
# und die Steuer stehen ueber dem, was zu zahlen ist.
_TEILBETRAG = ("netto", "mwst", "ust", "umsatzsteuer", "steuer", "zwischensumme",
               "rabatt", "skonto", "anzahlung")


def guess_amount(text):
    """Der zu zahlende Betrag aus dem Belegtext.

    **Zwei Fehler, die der erste grosse Upload zeigte (8.8.2026):**

    1. **Datumsangaben galten als Betraege.** „31.12.2026" wurde als „31,12"
       gelesen. Da im Rueckfall der *groesste* Fund gewann, schlug ein Datum
       jeden echten Kleinbetrag.
    2. **Der Nettobetrag schlug den Gesamtbetrag.** Das Schluesselwort „betrag"
       traf die Zeile „Nettobetrag 29,24" genauso wie „Gesamtbetrag 34,80" –
       und die Nettozeile steht weiter oben.

    Deshalb: Datumsanteile sind ausgeschlossen, die Schluesselwoerter sind
    geordnet, und Zeilen mit Netto/Steuer/Zwischensumme zaehlen nur, wenn sich
    sonst nichts findet.
    """
    if not text:
        return ""
    zeilen = text.splitlines()
    for wort in _SUMMENWORT:
        for i, ln in enumerate(zeilen):
            klein = ln.lower()
            if wort not in klein or any(x in klein for x in _TEILBETRAG):
                continue
            # Aus einer PDF-Tabelle kommen Beschriftung und Wert oft in
            # getrennten Zeilen: „Gesamtbetrag EUR" / „41,41". Deshalb bis zu
            # zwei Zeilen weiterlesen, bevor das Schluesselwort aufgegeben wird.
            for kandidat in zeilen[i:i + 3]:
                treffer = _MONEY.findall(kandidat)
                if treffer:
                    return treffer[-1].replace(".", ",")
    # Erst jetzt die Zeilen, die einen Teilbetrag benennen – besser der
    # Nettobetrag als gar nichts.
    for ln in zeilen:
        if any(x in ln.lower() for x in _SUMMENWORT):
            treffer = _MONEY.findall(ln)
            if treffer:
                return treffer[-1].replace(".", ",")
    alle = _MONEY.findall(text)
    if alle:
        def _wert(x):
            return float(x.replace(".", "").replace(",", "."))
        return max(alle, key=_wert).replace(".", ",")
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


def crop_quad(src_path, dst_path, corners):
    """Vier vom Nutzer gesetzte Ecken -> entzerrtes Dokument.

    corners: [(x, y), ...] als **Anteile 0..1** der Bildbreite/-höhe, Reihenfolge
    oben-links, oben-rechts, unten-rechts, unten-links. Anteile statt Pixel,
    damit die Anzeigegröße im Browser keine Rolle spielt.

    Mit OpenCV wird perspektivisch entzerrt. Fehlt OpenCV, wird auf einen
    achsenparallelen Zuschnitt auf das umgebende Rechteck zurückgefallen –
    schräg fotografiert bleibt das Bild dann schief, aber der Rand ist weg.
    """
    if not corners or len(corners) != 4:
        return False
    try:
        pts = [(float(x), float(y)) for x, y in corners]
    except (TypeError, ValueError):
        return False
    if not all(-0.05 <= v <= 1.05 for p in pts for v in p):
        return False

    try:
        import cv2
        import numpy as np
    except Exception:
        return _crop_bbox(src_path, dst_path, pts)

    img = cv2.imread(src_path)
    if img is None:
        return False
    h, w = img.shape[:2]
    src = np.array([[min(max(x, 0.0), 1.0) * w, min(max(y, 0.0), 1.0) * h]
                    for x, y in pts], dtype="float32")
    (tl, tr, br, bl) = src
    maxW = int(round(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl))))
    maxH = int(round(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl))))
    if maxW < 80 or maxH < 80:
        return False
    dst = np.array([[0, 0], [maxW - 1, 0], [maxW - 1, maxH - 1], [0, maxH - 1]],
                   dtype="float32")
    warped = cv2.warpPerspective(img, cv2.getPerspectiveTransform(src, dst), (maxW, maxH))
    return bool(cv2.imwrite(dst_path, warped))


def _crop_bbox(src_path, dst_path, pts):
    """Rückfall ohne OpenCV: auf das umgebende Rechteck zuschneiden (PyMuPDF)."""
    try:
        import fitz
        doc = fitz.open(src_path)
        page = doc[0]
        r = page.rect
        xs = [min(max(x, 0.0), 1.0) * r.width for x, _ in pts]
        ys = [min(max(y, 0.0), 1.0) * r.height for _, y in pts]
        clip = fitz.Rect(min(xs), min(ys), max(xs), max(ys))
        if clip.width < 20 or clip.height < 20:
            doc.close(); return False
        # 2x rendern, damit der Zuschnitt nicht an Auflösung verliert
        pix = page.get_pixmap(clip=clip, matrix=fitz.Matrix(2, 2))
        pix.save(dst_path)
        doc.close()
        return True
    except Exception:
        return False


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


def ist_pdf(data):
    """Kommt hier eine PDF an? Am Inhalt erkannt, nicht an der Dateiendung –
    die lügt bei Anhängen aus Mailprogrammen regelmäßig."""
    return bytes(data or b"")[:5] == b"%PDF-"


def text_aus_pdf(pdf_pfad, mindestens=20):
    """Text einer PDF lesen. Leerer String, wenn nichts Brauchbares drinsteht.

    Lieferantenrechnungen sind fast immer echte PDFs mit Textschicht – dort
    steht der Betrag exakt, statt von der Zeichenerkennung geraten zu werden.
    Nur wenn kaum Text herauskommt (eingescanntes Papier), lohnt sich OCR.

    `mindestens` ist die Grenze dazwischen. Nicht null, weil eingescanntes
    Papier oft ein paar Zeichen Bodensatz mitbringt – einen Stempel, eine
    Fusszeile – und den wollen wir nicht fuer den Inhalt halten.
    """
    try:
        import fitz
    except Exception:
        return ""
    try:
        with fitz.open(pdf_pfad) as doc:
            text = "\n".join(seite.get_text() for seite in doc)
    except Exception:
        return ""
    return text if len(text.strip()) >= mindestens else ""


def _pdf_vorschau(pdf_pfad, bild_pfad):
    """Erste Seite als JPG – fürs Vorschaubild und als Rückfall für die OCR."""
    try:
        import fitz
        with fitz.open(pdf_pfad) as doc:
            if not doc.page_count:
                return False
            doc[0].get_pixmap(matrix=fitz.Matrix(2, 2)).save(bild_pfad)
        return True
    except Exception:
        return False


def save_document(data, ext, mirror_dir=None, crop=True, corners=None):
    """Beleg-Bytes speichern, zuschneiden und als PDF ablegen.

    Nimmt Fotos **und** fertige PDFs an. Eine PDF wird nicht zugeschnitten und
    nicht neu erzeugt – sie ist bereits das Dokument; erzeugt wird nur ein
    Vorschaubild aus der ersten Seite. Rechnungen von Lieferanten kommen per
    Mail und werden nicht abfotografiert.

    corners: vom Nutzer im Scanner gesetzte Ecken (Anteile 0..1) – hat Vorrang
    vor der automatischen Erkennung. crop=False lässt das Bild unverändert.
    Gibt {'photo': rel_jpg, 'pdf': rel_pdf|None} zurück (+ Spiegelung nach mirror_dir)."""
    uid = housekeeping._uid()
    if ist_pdf(data):
        base = os.path.join(housekeeping.MEDIA_DIR, "beleg")
        os.makedirs(base, exist_ok=True)
        pdf_rel = f"beleg/{uid}.pdf"
        with open(os.path.join(housekeeping.MEDIA_DIR, pdf_rel), "wb") as f:
            f.write(data)
        bild_rel = f"beleg/{uid}_seite1.jpg"
        if not _pdf_vorschau(os.path.join(housekeeping.MEDIA_DIR, pdf_rel),
                             os.path.join(housekeeping.MEDIA_DIR, bild_rel)):
            bild_rel = None
        if mirror_dir:
            for rel in [x for x in (pdf_rel, bild_rel) if x]:
                try:
                    dst = os.path.join(mirror_dir, rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(os.path.join(housekeeping.MEDIA_DIR, rel), dst)
                except Exception:
                    pass
        return {"photo": bild_rel, "pdf": pdf_rel}
    base = os.path.join(housekeeping.MEDIA_DIR, "beleg")
    os.makedirs(base, exist_ok=True)
    orig_rel = f"beleg/{uid}.{ext}"
    orig_path = os.path.join(housekeeping.MEDIA_DIR, orig_rel)
    with open(orig_path, "wb") as f:
        f.write(data)

    img_rel = orig_rel
    crop_rel = f"beleg/{uid}_doc.jpg"
    crop_path = os.path.join(housekeeping.MEDIA_DIR, crop_rel)
    if corners:
        try:
            if crop_quad(orig_path, crop_path, corners):
                img_rel = crop_rel
        except Exception:
            pass
    elif crop:
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


# Wie weit oben der Briefkopf steht. Der Absender einer Rechnung steht in den
# ersten Zeilen; was weiter unten auftaucht, ist Fliesstext oder Tabelle.
_KOPF_ZEILEN = 20

# Rechtsformen, an denen ein Absender zu erkennen ist.
_RECHTSFORM = re.compile(
    r"(\bGmbH\b|\bmbH\b|\bAG\b|\bKG\b|\bUG\b|\bGbR\b|\bSE\b|"
    r"\be\.\s?K\.|\be\.\s?V\.|&\s?Co\b|\bUC\b|\bLtd\b|\bB\.?V\.?\b)", re.I)

# Zeilen, die nie ein Haendler sind: Seitenzahlen („1/2"), Beschriftungen
# („Rechnungsnr.:"), Netzadressen, reine Zahlen und Daten.
_KEIN_NAME = re.compile(
    r"^(\d+\s*/\s*\d+|[\d.,\s€-]+|.*:\s*$|www\..*|.*@.*|"
    r"\d{1,2}\.\d{1,2}\.\d{2,4}.*|"
    # Anschriftzeilen des EMPFAENGERS: „01219 Dresden", „Herr", „Frau".
    r"\d{5}\s+\S.*|(Herr|Frau|Firma|z\.\s?Hd\.?)\s*$)$", re.I)


def _kopfzeilen(text, wie_viele=_KOPF_ZEILEN):
    return [z.strip() for z in (text or "").splitlines() if len(z.strip()) > 2][:wie_viele]


def _ist_eigener(zeile, eigene):
    z = re.sub(r"\W+", "", (zeile or "").lower())
    return any(z and re.sub(r"\W+", "", (e or "").lower()) in z for e in (eigene or []) if e)


def guess_merchant(text, eigene=None):
    """Wer hat diesen Beleg ausgestellt?

    **Der Haendler steht im Briefkopf, nicht irgendwo im Dokument.** Die
    fruehere Fassung suchte die bekannten Namen als Teilzeichenkette im ganzen
    Text. Ergebnis nach dem ersten grossen Upload (8.8.2026): **13 von 31**
    Belegen hiessen „Netto" – darunter Rechnungen von Telekom, Lexware, JYSK
    und der Landeshauptstadt Dresden. Auf jeder Rechnung steht „Nettobetrag",
    und in jeder Betragstabelle steht „Netto" als Spaltenkopf. Wortgrenzen
    allein haetten den Spaltenkopf nicht abgefangen.

    Drei Stufen, alle nur im Kopf des Dokuments:

    1. **Bekannter Haendler** als ganzes Wort – dafuer war die Liste gedacht:
       auf einem Kassenbon steht der Name oben und gross.
    2. **Eine Zeile mit Rechtsform** (GmbH, AG, KG, UC …) – so stehen
       Lieferanten auf Rechnungen. Der Ort hinter dem Komma faellt weg.
    3. **Die erste brauchbare Zeile** – Behoerden und Vereine tragen keine
       Rechtsform. Seitenzahlen, Beschriftungen („Rechnungsnr.:"),
       Netzadressen und reine Zahlen zaehlen nicht.

    `eigene`: Namen des eigenen Betriebs. Auf Portalabrechnungen steht der
    eigene Name oben – als Empfaenger. Ohne diese Angabe hiesse der Beleg nach
    dem eigenen Betrieb (an den echten Daten 5 von 31).
    """
    zeilen = [z for z in _kopfzeilen(text) if not _ist_eigener(z, eigene)]
    # Der bekannte Haendler zaehlt nur ganz oben und nur, wenn die Zeile ihm
    # gehoert: entweder faengt sie mit ihm an, oder sie ist kurz. Sonst gewinnt
    # der Spaltenkopf „Position  Netto  Steuer  Brutto" einer Telekomrechnung –
    # genau der gemeldete Fall.
    for z in zeilen[:3]:
        up = z.upper()
        # „Gesamt Netto" ist eine Tabellenbeschriftung, kein Discounter. Eine
        # Zeile, die einen Betrag benennt, kann kein Briefkopf sein.
        # Bewusst OHNE „netto" selbst – sonst faellt der echte Kassenbon
        # „NETTO Marken-Discount" mit heraus.
        if any(w in z.lower() for w in _SUMMENWORT
               + ("mwst", "ust", "umsatzsteuer", "steuer", "zwischensumme")):
            continue
        for k in _KNOWN_MERCHANTS:
            muster = r"\b" + re.escape(k) + r"\b"
            if re.match(muster, up) or (len(z) <= 25 and re.search(muster, up)):
                return "dm" if k == "DM" else k.capitalize()
    for z in zeilen:
        if _ist_firmenzeile(z):
            return _saeubern(z)
    for z in zeilen:
        if not _KEIN_NAME.match(z) and not _ist_fliesstext(z):
            return _saeubern(z)
    return ""


def _ist_firmenzeile(zeile):
    """Eine Zeile, die einen Firmennamen traegt – nicht bloss eine Rechtsform.

    Zwei Ausschluesse, beide an echten Belegen gefunden:

    * **Fliesstext.** Im Kleingedruckten einer Lexware-Rechnung steht „… erfolgt
      durch die Haufe Service Center GmbH im eigenen Namen …". Das ist ein Satz,
      kein Briefkopf.
    * **Bruchstuecke.** Bei einem mehrzeilig gesetzten Namen bleibt „GmbH wy"
      uebrig. Vor der Rechtsform muss ein Name stehen.
    """
    m = _RECHTSFORM.search(zeile or "")
    if not m or _KEIN_NAME.match(zeile) or _ist_fliesstext(zeile):
        return False
    return m.start() > 0 and len(zeile) <= 60


def _ist_fliesstext(zeile):
    """Ein Satz statt eines Namens: faengt klein an oder traegt Satzwoerter."""
    z = (zeile or "").strip()
    if not z:
        return True
    if z[0].islower():
        return True
    # Ein Briefkopf endet nicht mit einem Punkt. „VCW Verlag für
    # ControllingWissen AG, Schäffer-Poeschel GmbH." ist das Ende eines Satzes
    # im Kleingedruckten – und stand sonst als Absender da.
    if z.endswith(".") and len(z.split()) >= 4 and not re.search(r"\b[A-Za-zÄÖÜ]\.$", z):
        return True
    return bool(re.search(r"\b(erfolgt|wir|ihre|ihr|bitte|durch die|im eigenen|"
                          r"gemäß|gemaess|entsprechend|siehe|zahlen sie|"
                          r"sind u\.|kommittenten)\b", z, re.I))


def _saeubern(zeile):
    """Ort, Postfach und OCR-Reste hinter dem Namen abschneiden."""
    z = re.split(r"[,*]|\s+Postfach\b|\s+PF\b", zeile, 1)[0]
    return z.strip(" -–·").strip()[:40]


# --------------------------------------------------- Sammelmappe (AP10)
def sammelmappe(belege, titel, zeilen):
    """Alle Belege eines Monats zu einer PDF binden – das, was das Steuerbüro
    sonst einzeln anfordert.

    Erste Seite ist die Aufstellung (dieselben Zahlen wie im CSV), danach je
    Beleg seine Seiten mit einer Kopfzeile darüber. Ohne die Kopfzeile ist ein
    abfotografierter Kassenbon in einem Stapel von vierzig nicht mehr
    zuzuordnen – und genau das ist die Arbeit, die sonst beim Steuerberater
    anfällt.

    `zeilen` sind die Journalzeilen (siehe buchhaltung.journal_zeilen), damit
    dieses Modul nichts über Buchhaltung wissen muss.
    """
    import fitz
    aus = fitz.open()
    breite, hoehe = fitz.paper_size("a4")
    rand, schrift = 40, "helv"

    # ---- Aufstellung ----
    seite = aus.new_page(width=breite, height=hoehe)
    y = rand + 20
    seite.insert_text((rand, y), titel, fontname=schrift, fontsize=16)
    y += 28
    for z in zeilen:
        if y > hoehe - rand:
            seite = aus.new_page(width=breite, height=hoehe)
            y = rand + 20
        text = f"{z['Datum']}   {z['Gegenkonto'][:28]:28}  {z['Betrag']:>10}   {z['Kategorie'][:34]}"
        seite.insert_text((rand, y), text, fontname="cour", fontsize=8)
        y += 13

    # ---- die Belege selbst ----
    for beleg, z in zip(belege, zeilen):
        kopf = (f"{z['Datum']} · {z['Gegenkonto']} · {z['Betrag']} € · {z['Kategorie']}")
        rel_pdf, rel_bild = beleg.get("pdf"), beleg.get("photo")
        pfad_pdf = os.path.join(housekeeping.MEDIA_DIR, rel_pdf) if rel_pdf else None
        pfad_bild = os.path.join(housekeeping.MEDIA_DIR, rel_bild) if rel_bild else None
        vorher = aus.page_count
        if pfad_pdf and os.path.exists(pfad_pdf):
            try:
                with fitz.open(pfad_pdf) as quelle:
                    aus.insert_pdf(quelle)
            except Exception:
                pass
        if aus.page_count == vorher and pfad_bild and os.path.exists(pfad_bild):
            try:
                seite = aus.new_page(width=breite, height=hoehe)
                kasten = fitz.Rect(rand, rand + 24, breite - rand, hoehe - rand)
                seite.insert_image(kasten, filename=pfad_bild, keep_proportion=True)
            except Exception:
                pass
        if aus.page_count == vorher:            # weder PDF noch Bild lesbar
            aus.new_page(width=breite, height=hoehe)
        # Kopfzeile auf die erste Seite dieses Belegs
        aus[vorher].insert_text((rand, rand - 10), kopf, fontname=schrift, fontsize=8,
                                color=(0.35, 0.16, 0.52))
    roh = aus.tobytes()
    aus.close()
    return roh


def eigene_namen(cfg):
    """Namen, unter denen der eigene Betrieb auf fremden Belegen auftaucht.

    Auf Portalabrechnungen und Lieferantenrechnungen steht der eigene Name
    oben – als **Empfänger**. Ohne diese Liste hieße der Beleg nach dem eigenen
    Betrieb; an den echten Daten betraf das 5 von 31 Belegen.
    """
    b = (cfg or {}).get("betreiber") or {}
    # Bewusst OHNE den blossen Vornamen (`zusatz`): „Daniel" allein wuerde auch
    # einen Lieferanten „Daniel Mueller GmbH" verwerfen.
    teile = [b.get("name", ""), b.get("strasse", "")]
    voll = " ".join(x for x in (b.get("zusatz", ""), b.get("name", "")) if x).strip()
    for apt in ((cfg or {}).get("apartments") or {}).values():
        if isinstance(apt, dict) and apt.get("name"):
            teile.append(apt["name"])
    return [x.strip() for x in teile + [voll] if x and len(x.strip()) > 2]
