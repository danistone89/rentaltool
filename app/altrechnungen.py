#!/usr/bin/env python3
"""Die Rechnungen aus dem alten Weg übernehmen (B10).

**Der Anlass.** Bis einschließlich der Buchung *Alexander Josan* (Nr. 78) sind
die Rechnungen über Smoobu erzeugt und verschickt; ab der nächsten übernimmt
das Werkzeug. Ohne Übernahme fehlten ihm 78 Rechnungen – und damit die halbe
Einnahmenseite, an der die Zahlungseingänge hängen (B3).

**Die PDFs sind die Quelle, nicht das Workbook.** Das Rechnungsausgangsbuch
deckt nur Nr. 1–59 ab, die PDFs alle 78 – und ihr Text ist vollständig
maschinenlesbar:

    Rechnung / 78 / Ausstellungsdatum / 31.07.2026
    Rechnungsempfänger / Alexander Josan
    1 / Cottaer Straße, 28.07.26 - 31.07.26, 2 Erwachsene / 358,66 €
    2 / Reinigungsgebühr / 75,00 €
    3 / Übernachtungssteuer / 26,02 €
    USt / 405,29 € / 7% / 28,37 €
    Gesamt zu zahlen / 459,68 €

**Was hinausgegangen ist, ist hinausgegangen.** Keine Neuberechnung der
Beherbergungssteuer, keine Korrektur der Beträge, kein Festschreiben-Lauf. Die
Sätze tragen `quelle="smoobu"`, und für sie wird **kein PDF neu gebaut**: der
Gast hat ein bestimmtes Dokument bekommen, ein zweites mit anderem Layout unter
derselben Nummer wäre ein zweiter Beleg zum selben Vorgang.
"""
import os
import re
import shutil
import unicodedata

from app import db, housekeeping, rechnung, receipts

QUELLE = "smoobu"

_NUMMER_AUS_NAME = re.compile(r"Rechnungen_(\d+)_(.+)\.pdf$")
_GELD = re.compile(r"(-?\d{1,3}(?:\.\d{3})*,\d{2})\s*€")
_DATUM = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
# „Cottaer Straße, 28.07.26 - 31.07.26, 2 Erwachsene"
_ZEILE = re.compile(r"^(.+?),\s*(\d{2}\.\d{2}\.\d{2})\s*-\s*(\d{2}\.\d{2}\.\d{2})")


def _geld(text):
    return round(float(text.replace(".", "").replace(",", ".")), 2)


def _tag(t, m, j):
    return f"{j}-{m}-{t}"


def _kurzdatum(s):
    """„28.07.26" -> „2026-07-28"."""
    t, m, j = s.split(".")
    return f"20{j}-{m}-{t}"


def lesen(pfad):
    """Eine alte Rechnung aus ihrer PDF lesen. None, wenn sie keine ist.

    Bewusst genügsam: gelesen wird nur, was auf jedem dieser Dokumente steht.
    Was fehlt, bleibt leer – ein geratener Wert wäre schlimmer als eine Lücke,
    weil er später wie eine Angabe des alten Systems aussähe.
    """
    name = os.path.basename(pfad)
    m = _NUMMER_AUS_NAME.search(name)
    if not m:
        return None
    text = receipts.text_aus_pdf(pfad)
    if not text or "Rechnung" not in text:
        return None
    zeilen = [z.strip() for z in text.splitlines()]

    datum = ""
    for i, z in enumerate(zeilen):
        if z.lower().startswith("ausstellungsdatum"):
            for kandidat in zeilen[i:i + 3]:
                d = _DATUM.search(kandidat)
                if d:
                    datum = _tag(*d.groups())
                    break
            break

    wohnung = anreise = abreise = ""
    for z in zeilen:
        treffer = _ZEILE.match(z)
        if treffer:
            wohnung = treffer.group(1).strip()
            anreise, abreise = (_kurzdatum(treffer.group(2)),
                                _kurzdatum(treffer.group(3)))
            break

    return {"nummer": m.group(1),
            # macOS legt Dateinamen in ZERLEGTER Unicode-Form ab („Ju"+"¨"
            # statt „ü"). Ungewandelt sieht der Name im Werkzeug zwar richtig
            # aus, vergleicht sich aber mit keinem anderen – beim Abgleich
            # gegen die vorhandenen Rechnungen fielen dadurch alle Umlaut-Namen
            # durch (Jürgen Ollmann, Thomas Künne, Helga Schäk …).
            "gast": unicodedata.normalize(
                "NFC", m.group(2).replace("_", " ")).strip(),
            "datum": datum,
            "wohnung_name": wohnung,
            "anreise": anreise, "abreise": abreise,
            "summen": _summen(zeilen),
            "datei": pfad}


def _summen(zeilen):
    """Brutto, USt, Netto und der durchlaufende Posten aus dem Steuerblock.

    **„Gesamt zu zahlen" hat Vorrang** – nicht „Summe", nicht „Gesamt". Auf
    diesen Dokumenten stehen alle drei nebeneinander (459,68 / 459,68 / 431,31),
    und nur die eine ist der Betrag, den der Gast gezahlt hat. Ein Vergleich,
    der nur mit „gesamt" beginnt, trifft heute zufällig das Richtige, weil die
    Zeile zuletzt kommt – bei einem anderen Layout nicht mehr.
    """
    def _nach(wort, tiefe=3):
        for i, z in enumerate(zeilen):
            if not z.strip().lower().startswith(wort):
                continue
            for kandidat in zeilen[i:i + tiefe]:
                g = _GELD.search(kandidat)
                if g:
                    return _geld(g.group(1))
        return None

    brutto = _nach("gesamt zu zahlen")
    if brutto is None:
        brutto = _nach("summe") or 0.0
    ust = _nach("inklusive ust") or 0.0
    durchlaufend = (_nach("übernachtungssteuer", 4)
                    or _nach("beherbergungssteuer", 4) or 0.0)
    return {"brutto": brutto, "ust": ust,
            "netto": round(brutto - ust - durchlaufend, 2),
            "durchlaufend": durchlaufend}


def vorhandene():
    """Die schon übernommenen Nummern – damit ein zweiter Lauf nichts doppelt."""
    return {r.get("nummer") for r in db.alle(rechnung.TABELLE)
            if r.get("quelle") == QUELLE}


def einlesen(ordner, bis_nummer=None):
    """Alle Alt-PDFs eines Ordners lesen – **ohne zu schreiben**.

    Zurück kommt die Liste der gelesenen Rechnungen, aufsteigend nach Nummer.
    `bis_nummer` schneidet oben ab: alles darüber gehört schon dem neuen Weg.
    """
    raus = []
    for name in sorted(os.listdir(ordner)):
        if not name.lower().endswith(".pdf"):
            continue
        satz = lesen(os.path.join(ordner, name))
        if not satz:
            continue
        if bis_nummer is not None and int(satz["nummer"]) > int(bis_nummer):
            continue
        raus.append(satz)
    return sorted(raus, key=lambda r: int(r["nummer"]))


def uebernehmen(saetze, wohnungen=None):
    """Die gelesenen Rechnungen ablegen. Gibt (neu, uebersprungen) zurück.

    Status **gesendet**: sie sind beim Gast. Nicht „festgeschrieben" – das ist
    ein Vorgang *dieses* Werkzeugs, und ihn nachträglich zu behaupten wäre eine
    Aussage über etwas, das hier nie stattgefunden hat.

    Die Original-PDF wird in die Medienablage kopiert und am Satz vermerkt.
    """
    vorhanden = vorhandene()
    neu = uebersprungen = 0
    for s in saetze:
        if s["nummer"] in vorhanden:
            uebersprungen += 1
            continue
        rel = _pdf_kopieren(s["datei"], s["nummer"])
        eintrag = {
            "id": f"alt-{s['nummer']}", "status": rechnung.GESENDET,
            "nummer": s["nummer"], "buchung": "",
            "wohnung": _wohnung_id(s["wohnung_name"], wohnungen),
            "wohnung_name": s["wohnung_name"],
            "anreise": s["anreise"], "abreise": s["abreise"],
            "gast": s["gast"], "empfaenger": {"name": s["gast"]},
            "positionen": [], "summen": s["summen"],
            "datum": s["datum"], "befunde": [],
            "quelle": QUELLE, "pdf": rel,
            "angelegt": rechnung._jetzt(), "angelegt_von": "übernahme",
        }
        db.anlegen(rechnung.TABELLE, eintrag, sid=eintrag["id"])
        neu += 1
    return neu, uebersprungen


def _wohnung_id(name, wohnungen):
    """Die Wohnungskennung zum Namen aus der PDF – '' wenn keine passt."""
    for wid, wname in (wohnungen or {}).items():
        if name and wname and name.strip().lower() in wname.strip().lower():
            return wid
        if name and wname and wname.strip().lower() in name.strip().lower():
            return wid
    return ""


def _pdf_kopieren(quelle, nummer):
    ziel_rel = f"rechnung-alt/{nummer}.pdf"
    ziel = os.path.join(housekeeping.MEDIA_DIR, ziel_rel)
    os.makedirs(os.path.dirname(ziel), exist_ok=True)
    shutil.copy2(quelle, ziel)
    return ziel_rel


def ist_uebernommen(r):
    """Für die Anzeige: diese Rechnung stammt aus dem alten Weg."""
    return (r or {}).get("quelle") == QUELLE


def original_pfad(r):
    """Die Datei, die der Gast bekommen hat – oder '' wenn es keine gibt."""
    rel = (r or {}).get("pdf") or ""
    if not rel:
        return ""
    pfad = os.path.join(housekeeping.MEDIA_DIR, rel)
    return pfad if os.path.exists(pfad) else ""
