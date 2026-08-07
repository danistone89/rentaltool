#!/usr/bin/env python3
"""Der Weg einer Monatsmeldung: offen → erzeugt → gesendet → bezahlt.

Ohne Oberfläche. Die Rechnung selbst steht in `app/steuer.py`, der Nachweis im
revisionssicheren Archiv (`app/archive.py`) – hier steht nur, **wo ein Monat
gerade steht** und **was ihn aufhält**.

Warum es das braucht: Bisher war das Archiv der einzige Merker, und es kennt nur
„für 2026-05 liegt ein PDF". Ein Monat, der berechnet, aber nie abgeschickt
wurde, sah aus wie einer, den nie jemand angefasst hat. Und ob die Steuer
überwiesen ist, wusste die App überhaupt nicht – das stand allein auf dem
Kontoauszug.

**Die Frist ist der 7. des Folgemonats**, für Meldung *und* Überweisung. Fällt
sie auf einen Samstag, Sonntag oder gesetzlichen Feiertag, verschiebt sie sich
auf den nächsten Werktag (§ 108 Abs. 3 AO i. V. m. § 193 BGB). Die Feiertage
kommen aus `app/feiertage.py` und gelten für Sachsen.
"""
from datetime import date, timedelta

from app import archive, data, db, feiertage, protokoll

TABELLE = "meldungen"

# Die vier Zustände in der Reihenfolge, in der ein Monat sie durchläuft.
OFFEN, ERZEUGT, GESENDET, BEZAHLT = "offen", "erzeugt", "gesendet", "bezahlt"
STUFEN = [OFFEN, ERZEUGT, GESENDET, BEZAHLT]

# Bis zum 7. des Folgemonats – so steht es im Bescheid der Stadt.
STICHTAG = 7


def periode(jahr, monat):
    return f"{jahr}-{monat:02d}"


def jahr_monat(periode_iso):
    return int(periode_iso[:4]), int(periode_iso[5:7])


def _naechster_werktag(tag):
    """Samstag, Sonntag und Feiertage schieben die Frist nach hinten."""
    while tag.weekday() >= 5 or feiertage.is_feiertag(tag):
        tag += timedelta(days=1)
    return tag


def frist(periode_iso):
    """Wann Meldung und Überweisung spätestens draußen sein müssen."""
    jahr, monat = jahr_monat(periode_iso)
    folge = date(jahr + (monat == 12), 1 if monat == 12 else monat + 1, STICHTAG)
    return _naechster_werktag(folge)


def tage_bis_frist(periode_iso, heute=None):
    """Negativ heißt überfällig, 0 heißt heute."""
    return (frist(periode_iso) - (heute or date.today())).days


# ------------------------------------------------------------------ Zustand
def _eintrag(periode_iso):
    return db.holen(TABELLE, periode_iso) or {}


def _archiv_hat(periode_iso):
    """Liegt für diesen Monat ein Dokument im revisionssicheren Archiv?

    Das Archiv ist die Wahrheit über „erzeugt": ein PDF entsteht nie, ohne
    abgelegt zu werden.
    """
    return any(e.get("period") == periode_iso for e in archive.list_entries())


def status(periode_iso):
    """Wo der Monat steht – aus Archiv und Merker zusammen."""
    e = _eintrag(periode_iso)
    if e.get("bezahlt"):
        return BEZAHLT
    if e.get("gesendet"):
        return GESENDET
    if e.get("erzeugt") or _archiv_hat(periode_iso):
        return ERZEUGT
    return OFFEN


def _merken(periode_iso, **felder):
    with db.transaktion():
        e = db.holen(TABELLE, periode_iso) or {"id": periode_iso,
                                               "periode": periode_iso}
        e.update(felder)
        if db.holen(TABELLE, periode_iso) is None:
            db.anlegen(TABELLE, e)
        else:
            db.speichern(TABELLE, periode_iso, e)
    return e


def _jetzt():
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


def erzeugt(periode_iso, wer=""):
    """Das PDF wurde gebaut und abgelegt."""
    return _merken(periode_iso, erzeugt=_jetzt(), erzeugt_von=wer)


def gesendet(periode_iso, wer="", an=""):
    """Die Anmeldung ist raus. Setzt die App selbst – sie verschickt ja."""
    return _merken(periode_iso, erzeugt=_eintrag(periode_iso).get("erzeugt") or _jetzt(),
                   gesendet=_jetzt(), gesendet_von=wer, gesendet_an=an)


def bezahlt(periode_iso, wer=""):
    """Überwiesen. Das kann nur ein Mensch bestätigen: die App sieht das
    Bankkonto nicht."""
    return _merken(periode_iso, bezahlt=_jetzt(), bezahlt_von=wer)


def zuruecknehmen(periode_iso, stufe, wer=""):
    """Eine Stufe zurücknehmen – versehentlich abgehakt kommt vor.

    Zurückgenommen wird immer mitsamt allem, was darauf aufbaut: „nicht
    gesendet, aber bezahlt" wäre ein Zustand, den es nicht gibt. Und es steht
    im Protokoll: eine Meldung, die als erledigt galt und es plötzlich nicht
    mehr ist, muss nachvollziehbar bleiben.
    """
    protokoll.notieren(wer, protokoll.MELDUNG_ZURUECKGESETZT, periode_iso,
                       f"zurück auf vor „{stufe}\u201c")
    felder = {}
    if stufe == BEZAHLT:
        felder = {"bezahlt": "", "bezahlt_von": ""}
    elif stufe == GESENDET:
        felder = {"gesendet": "", "gesendet_von": "", "gesendet_an": "",
                  "bezahlt": "", "bezahlt_von": ""}
    return _merken(periode_iso, **felder)


def eintrag(periode_iso):
    """Der Merker samt abgeleitetem Status und Frist – für die Anzeige."""
    e = dict(_eintrag(periode_iso))
    e.update({"periode": periode_iso, "status": status(periode_iso),
              "frist": frist(periode_iso).isoformat()})
    return e


def startmonat(heute=None):
    """Ab wann diese Instanz zuständig ist.

    Ohne diese Grenze meldet eine frisch aufgesetzte App zwölf überfällige
    Monate – für Zeiträume, die längst außerhalb erledigt wurden. Eine Liste,
    die beim ersten Blick komplett rot ist, liest danach niemand mehr.

    Vorrang hat `config.meldungen_ab` ("JJJJ-MM"). Sonst zählt der älteste
    Monat im Archiv: was dort liegt, hat diese App erzeugt. Und wenn auch das
    fehlt, beginnt die Zuständigkeit mit dem laufenden Monat.
    """
    gesetzt = (data.CONFIG.get("meldungen_ab") or "").strip()
    if len(gesetzt) == 7 and gesetzt[4] == "-":
        return gesetzt
    perioden = sorted(e.get("period", "") for e in archive.list_entries())
    perioden = [p for p in perioden if len(p) == 7]
    if perioden:
        return perioden[0]
    heute = heute or date.today()
    return periode(heute.year, heute.month)


def offene(heute=None, monate_zurueck=24):
    """Die Monate, die noch nicht bezahlt sind – ältester zuerst.

    Nur abgeschlossene Monate: der laufende ist noch nicht zu melden. Und nur
    ab `startmonat()` – davor war diese App nicht zuständig.
    """
    heute = heute or date.today()
    ab = startmonat(heute)
    jahr, monat = heute.year, heute.month
    liste = []
    for _ in range(monate_zurueck):
        monat -= 1
        if monat == 0:
            jahr, monat = jahr - 1, 12
        p = periode(jahr, monat)
        if p < ab:
            break
        if status(p) != BEZAHLT:
            liste.append(eintrag(p))
    return sorted(liste, key=lambda e: e["periode"])


def ueberfaellig(heute=None):
    """Was die Frist gerissen hat und noch nicht bezahlt ist."""
    heute = heute or date.today()
    return [e for e in offene(heute) if tage_bis_frist(e["periode"], heute) < 0]


# --------------------------------------------------- Vollständigkeitsprüfung
def vollstaendigkeit(ergebnis, buchungen, heute=None):
    """Was gegen ein Erzeugen spricht – in Klartext, vor dem PDF.

    Das amtliche Formular ist ein Nachweis. Was das Ergebnis unzuverlässig
    macht, gehört davor, nicht hinterher in eine Korrekturmeldung.

    `ergebnis` ist das Dict aus `steuer.compute`, `buchungen` die Rohdaten
    desselben Zeitraums (für das, was compute wegwirft).
    """
    heute = heute or date.today()
    jahr, monat = ergebnis["year"], ergebnis["month"]
    p = periode(jahr, monat)
    letzter = _letzter_tag(jahr, monat)
    befund = []

    if heute <= letzter:
        befund.append(f"Der Monat läuft noch bis zum {letzter.strftime('%d.%m.')} – "
                      "Abreisen danach fehlen in der Rechnung.")

    kuenftig = _abreisen_nach_heute(buchungen, jahr, monat, heute)
    if kuenftig:
        befund.append(f"{kuenftig} Buchung(en) reisen erst nach heute ab und zählen "
                      "deshalb noch nicht mit.")

    ohne_datum = _ohne_abreisedatum(buchungen)
    if ohne_datum:
        befund.append(f"{ohne_datum} Buchung(en) haben kein Abreisedatum – sie "
                      "fallen aus der Rechnung, ohne aufzufallen.")

    if not ergebnis.get("rows"):
        befund.append("Für diesen Monat liegt keine einzige Buchung vor.")

    if ergebnis.get("uebernachtungen_airbnb") and not ergebnis.get("umsatz_steuerpflichtig"):
        befund.append("Es gibt Airbnb-Übernachtungen, aber keinen steuerpflichtigen "
                      "Umsatz – bitte prüfen, ob das stimmt.")

    if status(p) in (GESENDET, BEZAHLT):
        befund.append(f"Für {p} ist bereits eine Anmeldung raus – ein neues PDF wäre "
                      "eine Korrekturmeldung.")

    return befund


def _letzter_tag(jahr, monat):
    return (date(jahr + (monat == 12), 1 if monat == 12 else monat + 1, 1)
            - timedelta(days=1))


def _abreisen_nach_heute(buchungen, jahr, monat, heute):
    n = 0
    for b in buchungen or []:
        if b.get("is-blocked-booking") or b.get("type") == "cancellation":
            continue
        dep = b.get("departure")
        if not dep:
            continue
        try:
            d = date.fromisoformat(dep[:10])
        except ValueError:
            continue
        if d.year == jahr and d.month == monat and d > heute:
            n += 1
    return n


def _ohne_abreisedatum(buchungen):
    return sum(1 for b in (buchungen or [])
               if not b.get("is-blocked-booking")
               and b.get("type") != "cancellation"
               and not b.get("departure"))
