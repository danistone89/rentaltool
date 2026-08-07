#!/usr/bin/env python3
"""Ausgangsrechnungen: aus einer Buchung wird ein Beleg.

Ohne Oberfläche. Hier steht, **wie** aus dem Betrag, den der Gast zahlt, eine
Rechnung mit Positionen wird – und welchen Weg sie danach nimmt.

**Rückwärts gerechnet, weil nur der Gesamtbetrag verlässlich ist.** Booking.com
und Airbnb geben ihre Aufschlüsselung unvollständig an Smoobu weiter: von 85
Buchungen des Jahres tragen 78 eine Reinigungsgebühr, 58 eine
Übernachtungssteuer, 55 eine Mehrwertsteuer, drei gar nichts. Verlässlich ist
allein `price`. Also:

    Gesamtbetrag
    − Beherbergungssteuer      (aus price-details, sonst herausgerechnet)
    − Reinigung                (aus price-details, sonst Produktpreis)
    = Beherbergung             (der Rest)

Die erste Zeile stammt aus `steuer.ohne_citytax` – **derselben Funktion, die
die Steueranmeldung trägt**. Weicht die Rechnung von der Anmeldung ab, ist eine
von beiden falsch, und das darf nicht möglich sein.

**Die Probe gehört dazu.** Die Summe der Positionen muss den Smoobu-Betrag auf
den Cent treffen. Tut sie es nicht, entsteht kein Entwurf, sondern ein Klärfall.
Eine Rechnung, die sich still um zwei Cent verrechnet, findet niemand wieder.

**Die Nummer entsteht beim Festschreiben**, nicht beim Öffnen des Entwurfs – ein
verworfener Entwurf hinterlässt sonst eine Lücke, und ein lückenhafter
Nummernkreis ist ein Mangel, den jede Prüfung findet.
"""
import uuid
from datetime import date, datetime

from app import db, stammdaten, steuer

TABELLE = "rechnungen"

# Der Weg einer Rechnung. Ein Entwurf ist noch nichts – erst das Festschreiben
# vergibt die Nummer und macht ihn unveränderlich.
ENTWURF, FESTGESCHRIEBEN, GESENDET, STORNIERT = (
    "entwurf", "festgeschrieben", "gesendet", "storniert")

# Voreinstellung des Nummernkreises. Das Rechnungsausgangsbuch des Workbooks
# führt 2026 bereits 75 Nummern – der Kreis beginnt dahinter, damit nichts
# doppelt vergeben wird.
VORGABE_STARTNUMMER = 76

USTSATZ = 0.07


def _jetzt():
    return datetime.now().isoformat(timespec="seconds")


# ------------------------------------------------------------- Nummernkreis
def nummernkreis_start(jahr, cfg=None):
    """Die erste Nummer eines Jahres.

    `config.rechnung_startnummer` gilt nur für das Jahr, in dem umgestellt
    wurde – jedes weitere Jahr beginnt bei 1. Sonst hinge die Zählung eines
    Jahres 2030 noch an einer Zahl aus dem Workbook von 2026.
    """
    cfg = cfg if cfg is not None else _cfg()
    start_jahr = str(cfg.get("rechnung_startjahr", "") or "")
    if start_jahr and str(jahr) == start_jahr:
        try:
            return int(cfg.get("rechnung_startnummer", VORGABE_STARTNUMMER))
        except (TypeError, ValueError):
            return VORGABE_STARTNUMMER
    return 1


def _cfg():
    from app import data
    return data.CONFIG


def naechste_nummer(jahr=None, cfg=None):
    """Die nächste freie Rechnungsnummer dieses Jahres, etwa „2026-0076".

    Lückenlos und fortlaufend: gezählt wird, was vergeben ist, nicht was
    existiert. Ein stornierter Beleg behält seine Nummer – Storno heißt
    Gutschrift, nicht Löschung.
    """
    jahr = jahr or date.today().year
    vergeben = [int(r["nummer"].split("-")[1]) for r in db.alle(TABELLE)
                if (r.get("nummer") or "").startswith(f"{jahr}-")]
    start = nummernkreis_start(jahr, cfg)
    naechste = max(vergeben) + 1 if vergeben else start
    return f"{jahr}-{max(naechste, start):04d}"


# --------------------------------------------------------------- Aufteilung
def _pos(bezeichnung, brutto, ustsatz):
    """Eine Rechnungsposition. Brutto ist die Vorgabe, weil der Gast einen
    Bruttobetrag bezahlt hat – netto und Steuer folgen daraus."""
    brutto = round(float(brutto), 2)
    netto = round(brutto / (1 + ustsatz), 2) if ustsatz else brutto
    return {"bezeichnung": bezeichnung, "brutto": brutto,
            "netto": netto, "ust": round(brutto - netto, 2), "ustsatz": ustsatz}


def aufteilung(buchung, reinigungspreis=None, steuersatz=0.06, airbnb_channel="Airbnb"):
    """Positionen einer Buchung – oder ein Befund, warum es nicht geht.

    `reinigungspreis` ist der hinterlegte Produktpreis; er greift nur, wenn
    Smoobu keine Reinigungsgebühr mitschickt. Was Smoobu liefert, gilt: der
    Gast hat diesen Betrag bezahlt, nicht den, den wir für richtig halten.

    Gibt (positionen, befunde) zurück. Sind Befunde da, ist die Aufteilung
    nicht belastbar.
    """
    brutto = round(float(buchung.get("price") or 0.0), 2)
    befunde = []
    if brutto <= 0:
        return [], ["Die Buchung hat keinen Betrag."]

    basis, citytax = steuer.ohne_citytax(buchung, steuersatz, airbnb_channel)

    reinigung = steuer._pricedetail(buchung.get("price-details"), "Reinigungsgebühr")
    quelle = "Smoobu"
    if not reinigung:
        reinigung = round(float(reinigungspreis or 0), 2)
        quelle = "Produktpreis"
        if not reinigung:
            befunde.append("Keine Reinigungsgebühr – weder von Smoobu noch als Preis "
                           "hinterlegt.")
    elif reinigungspreis and abs(reinigung - float(reinigungspreis)) > 0.005:
        befunde.append(f"Smoobu berechnet {reinigung:.2f} € Reinigung, hinterlegt sind "
                       f"{float(reinigungspreis):.2f} €.")

    beherbergung = round(basis - reinigung, 2)
    if beherbergung < 0:
        befunde.append("Die Reinigungsgebühr ist größer als der ganze Betrag.")
        return [], befunde

    positionen = [_pos("Übernachtung", beherbergung, USTSATZ)]
    if reinigung:
        positionen.append(_pos("Endreinigung", reinigung, USTSATZ))
    if citytax:
        # Durchlaufender Posten: keine Umsatzsteuer, 1:1 wie in der Anmeldung.
        positionen.append(_pos("Beherbergungssteuer", citytax, 0.0))

    probe = round(sum(p["brutto"] for p in positionen), 2)
    if abs(probe - brutto) > 0.005:
        befunde.append(f"Die Positionen ergeben {probe:.2f} €, der Gast zahlt "
                       f"{brutto:.2f} €.")
    for p in positionen:
        p["quelle"] = quelle if p["bezeichnung"] == "Endreinigung" else ""
    return positionen, befunde


def summen(positionen):
    """Netto, Umsatzsteuer, Brutto – und was davon durchlaufend ist."""
    netto = round(sum(p["netto"] for p in positionen if p["ustsatz"]), 2)
    ust = round(sum(p["ust"] for p in positionen), 2)
    durchlaufend = round(sum(p["brutto"] for p in positionen if not p["ustsatz"]), 2)
    return {"netto": netto, "ust": ust, "durchlaufend": durchlaufend,
            "brutto": round(netto + ust + durchlaufend, 2)}


# --------------------------------------------------------------- Empfänger
def empfaenger_aus_gast(gast):
    """Rechnungsempfänger aus den Smoobu-Gastdaten.

    Ohne Straße, PLZ und Ort ist die Anschrift unvollständig – über 250 €
    brutto verlangt § 14 UStG beides. Der Entwurf entsteht trotzdem, aber er
    sagt es.
    """
    gast = gast or {}
    a = gast.get("address") or {}
    name = " ".join(x for x in [(gast.get("firstName") or "").strip(),
                                (gast.get("lastName") or "").strip()] if x)
    mails = gast.get("emails") or []
    return {"name": name or (gast.get("name") or ""),
            "strasse": (a.get("street") or "").strip(),
            "plz": (a.get("postalCode") or "").strip(),
            "ort": (a.get("city") or "").strip(),
            "land": (a.get("country") or "").strip(),
            "email": (mails[0] if mails else gast.get("email", "")) or ""}


def anschrift_vollstaendig(empfaenger):
    e = empfaenger or {}
    return all((e.get(k) or "").strip() for k in ("name", "strasse", "plz", "ort"))


KLEINBETRAG = 250.0


def braucht_anschrift(brutto):
    """Bis 250 € genügt die Kleinbetragsrechnung ohne Empfängeranschrift
    (§ 33 UStDV). Darüber verlangt § 14 UStG Name und Anschrift."""
    return round(float(brutto or 0), 2) > KLEINBETRAG


# ---------------------------------------------------------------- Bestand
def rechnungen(jahr=None):
    """Alle Rechnungen, neueste zuerst."""
    alle = db.alle(TABELLE)
    if jahr:
        alle = [r for r in alle if (r.get("datum") or "").startswith(str(jahr))]
    return sorted(alle, key=lambda r: (r.get("datum") or "", r.get("nummer") or ""),
                  reverse=True)


def zu_buchung(buchung_id):
    """Die Rechnung dieser Buchung – None, wenn es noch keine gibt."""
    for r in db.alle(TABELLE):
        if str(r.get("buchung")) == str(buchung_id) and r.get("status") != STORNIERT:
            return r
    return None


def entwurf_anlegen(buchung, positionen, empfaenger, befunde=None, wer=""):
    """Einen Entwurf ablegen – ohne Nummer, die kommt erst beim Festschreiben."""
    s = summen(positionen)
    eintrag = {
        "id": uuid.uuid4().hex[:12], "status": ENTWURF, "nummer": "",
        "buchung": buchung.get("id"),
        "wohnung": (buchung.get("apartment") or {}).get("id"),
        "wohnung_name": (buchung.get("apartment") or {}).get("name", ""),
        "anreise": (buchung.get("arrival") or "")[:10],
        "abreise": (buchung.get("departure") or "")[:10],
        "gast": buchung.get("guest-name") or "",
        "empfaenger": empfaenger or {},
        "positionen": positionen,
        "summen": s,
        "datum": date.today().isoformat(),
        "befunde": list(befunde or []),
        "angelegt": _jetzt(), "angelegt_von": wer,
    }
    db.anlegen(TABELLE, eintrag)
    return eintrag


def aendern(rechnung_id, **felder):
    """Nur Entwürfe lassen sich ändern. Was festgeschrieben ist, ist fest."""
    with db.transaktion():
        r = db.holen(TABELLE, rechnung_id)
        if r is None or r.get("status") != ENTWURF:
            return None
        for k, v in felder.items():
            if k in ("empfaenger", "positionen", "datum", "befunde"):
                r[k] = v
        r["summen"] = summen(r.get("positionen", []))
        db.speichern(TABELLE, rechnung_id, r)
    return r


def versandbereit(r):
    """Darf diese Rechnung raus? Gibt (ja, grund)."""
    if not r:
        return False, "Rechnung fehlt."
    if r.get("status") == ENTWURF:
        return False, "Noch ein Entwurf – erst festschreiben."
    if r.get("status") == STORNIERT:
        return False, "Storniert."
    if r.get("befunde"):
        return False, "Es steht noch etwas offen."
    brutto = (r.get("summen") or {}).get("brutto", 0)
    if braucht_anschrift(brutto) and not anschrift_vollstaendig(r.get("empfaenger")):
        return False, "Über 250 € ohne vollständige Anschrift."
    if not (r.get("empfaenger") or {}).get("email"):
        return False, "Keine E-Mail-Adresse."
    return True, ""


def festschreiben(rechnung_id, wer="", cfg=None):
    """Nummer vergeben und den Entwurf schließen.

    Ab hier ist die Rechnung unveränderlich. Wer etwas korrigieren muss,
    storniert und schreibt neu – so bleibt nachvollziehbar, was einmal
    hinausgegangen ist.
    """
    with db.transaktion():
        r = db.holen(TABELLE, rechnung_id)
        if r is None or r.get("status") != ENTWURF:
            return None
        if r.get("befunde"):
            raise ValueError("Rechnung hat offene Befunde")
        jahr = int((r.get("datum") or date.today().isoformat())[:4])
        r["nummer"] = naechste_nummer(jahr, cfg)
        r["status"] = FESTGESCHRIEBEN
        r["festgeschrieben"] = _jetzt()
        r["festgeschrieben_von"] = wer
        db.speichern(TABELLE, rechnung_id, r)
    return r


def gesendet(rechnung_id, an="", wer=""):
    with db.transaktion():
        r = db.holen(TABELLE, rechnung_id)
        if r is None or r.get("status") not in (FESTGESCHRIEBEN, GESENDET):
            return None
        r["status"] = GESENDET
        r["gesendet"] = _jetzt()
        r["gesendet_an"] = an
        r["gesendet_von"] = wer
        db.speichern(TABELLE, rechnung_id, r)
    return r


def stornieren(rechnung_id, grund="", wer=""):
    """Storno statt Löschung – die Nummer bleibt vergeben.

    Eine verschwundene Rechnungsnummer ist ein Mangel, den jede Prüfung findet.
    Der Beleg bleibt also stehen und trägt seinen Grund.
    """
    with db.transaktion():
        r = db.holen(TABELLE, rechnung_id)
        if r is None or r.get("status") == ENTWURF:
            return None
        r["status"] = STORNIERT
        r["storniert"] = _jetzt()
        r["storno_grund"] = grund
        r["storniert_von"] = wer
        db.speichern(TABELLE, rechnung_id, r)
    return r


def loeschen(rechnung_id):
    """Nur Entwürfe. Alles andere wird storniert, nicht gelöscht."""
    r = db.holen(TABELLE, rechnung_id)
    if r is not None and r.get("status") == ENTWURF:
        db.loeschen(TABELLE, rechnung_id)
        return True
    return False


# ------------------------------------------------- Entwürfe nach Check-out
def faellige_buchungen(jobs, heute=None):
    """Abgereiste Buchungen ohne Rechnung – dafür entsteht ein Entwurf.

    Erst nach dem Check-out: vorher kann sich der Betrag noch ändern, und eine
    Rechnung über einen Aufenthalt, der noch läuft, ist keine.
    """
    heute = (heute or date.today()).isoformat()
    faellig = []
    for j in jobs or []:
        ab = (j.get("departure") or "")[:10]
        if not ab or ab > heute:
            continue
        if zu_buchung(j.get("id")):
            continue
        faellig.append(j)
    return faellig


def entwurf_fuer(buchung, gast=None, cfg=None, wer=""):
    """Aus einer Buchung einen Entwurf machen – mit allem, was dazugehört."""
    cfg = cfg if cfg is not None else _cfg()
    wohnung = (buchung.get("apartment") or {}).get("id")
    gebucht = (buchung.get("created-at") or buchung.get("arrival") or "")[:10]
    produkt = stammdaten.produkt_der_art(stammdaten.FEST)
    preis = stammdaten.preis_am(produkt, wohnung, gebucht) if produkt else None
    positionen, befunde = aufteilung(
        buchung, preis,
        steuersatz=cfg.get("steuersatz", 0.06),
        airbnb_channel=cfg.get("airbnb_channel_name", "Airbnb"))
    if not positionen:
        return None, befunde
    empf = empfaenger_aus_gast(gast)
    brutto = summen(positionen)["brutto"]
    if braucht_anschrift(brutto) and not anschrift_vollstaendig(empf):
        befunde.append("Über 250 € – Anschrift des Gastes fehlt noch.")
    return entwurf_anlegen(buchung, positionen, empf, befunde, wer), befunde
