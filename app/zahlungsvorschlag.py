#!/usr/bin/env python3
"""Welche Rechnungen könnten zu dieser Zahlung gehören? (B3)

**Eine Kandidatenliste, keine Automatik.** Nachgemessen an den echten Daten:
von 65 Zahlungseingängen entspricht genau **einer** exakt einem
Rechnungsbetrag. Booking und Airbnb zahlen netto nach Provision aus, der Betrag
*kann* gar nicht stimmen; und die Reservierungsnummer steht nicht im
Verwendungszweck – dort steht nur die Wohnung. Eine Automatik, die aus Beträgen
Kombinationen sucht, würde falsch buchen und es nicht sagen.

Was stattdessen trägt:

* **Der Gastname** im Verwendungszweck – bei Direktzahlern eindeutig
  („Buchung Katarina Gockel Cottaer Straße").
* **Die Wohnung** aus der Portal-Kennung (`ID.14005823`). Sie sagt nicht,
  welche Buchung gemeint ist, aber sie halbiert die Liste. Welche Kennung zu
  welcher Wohnung gehört, **lernt** das Werkzeug bei der ersten Zuordnung.
**Zugeordnet wird der Rechnungsbetrag, nicht die Auszahlung.** Sonst wäre der
Umsatz um die Provision zu niedrig und die Provision tauchte als Ausgabe nie
auf. Was übrig bleibt, ist die einbehaltene Provision.

⚠ **Die Provision aus Smoobu (`commission-included`) ist nicht verlässlich** –
so der Betreiber am 8.8.2026. Maßgeblich sind die **monatlichen Belege von
Booking und Airbnb**, die das Steuerbüro gegen die Auszahlungen bucht. Die
Smoobu-Zahl wird deshalb weder angezeigt noch zur Prüfung herangezogen.

Der Mensch entscheidet, das Werkzeug sortiert nur vor.
"""
import re

from app import rechnung, zuordnung

# Wie eine Portal-Kennung im Verwendungszweck aussieht: „…/ID.14005823".
_KENNUNG = re.compile(r"ID\.(\d+)")

# Wo die gelernte Zuordnung Kennung -> Wohnung steht.
CFG_SCHLUESSEL = "portal_wohnungen"


def kennung(bewegung):
    """Die Portal-Kennung aus dem Verwendungszweck – oder ''."""
    m = _KENNUNG.search(bewegung.get("text") or "")
    return m.group(1) if m else ""


def wohnung_zu_kennung(kennung_nr, cfg=None):
    return ((cfg or {}).get(CFG_SCHLUESSEL) or {}).get(str(kennung_nr or ""), "")


def kennung_lernen(cfg, kennung_nr, wohnung_id):
    """Merken, welche Wohnung hinter einer Portal-Kennung steckt.

    Booking nennt im Verwendungszweck seine eigene Objektnummer. Welche das
    ist, weiß nur der Betrieb – und er sagt es dem Werkzeug, indem er einmal
    eine Rechnung zuordnet.
    """
    if not (kennung_nr and wohnung_id):
        return None
    cfg.setdefault(CFG_SCHLUESSEL, {})[str(kennung_nr)] = wohnung_id
    return wohnung_id


def _name_teile(text):
    """Wortstücke aus dem Verwendungszweck, die ein Nachname sein könnten."""
    return {w.lower().strip(",.") for w in re.split(r"[^A-Za-zÄÖÜäöüß]+", text or "")
            if len(w) > 3}


def ist_bezahlt(r):
    """Hängt diese Rechnung schon an einer Bankbewegung?"""
    return bool(zuordnung.bewegung_zu(zuordnung.RECHNUNG, r["id"]))


def offene(jahr=None):
    """Rechnungen, die auf ihr Geld warten.

    Entwürfe zählen nicht – sie tragen noch keine Nummer und sind nicht
    hinausgegangen. Stornierte auch nicht.
    """
    return [r for r in rechnung.rechnungen(jahr)
            if r.get("status") in (rechnung.FESTGESCHRIEBEN, rechnung.GESENDET)
            and not ist_bezahlt(r)]


def erwartet(r, buchungen=None):
    """Rechnungsbetrag minus geschätzter Provision – **ein Anhalt, kein Wert**.

    ⚠ Die Provision aus Smoobu (`commission-included`) ist nicht verlässlich
    (siehe `provisionsprobe`). Zugeordnet und angezeigt wird deshalb der
    **Rechnungsbetrag**; diese Funktion dient nur noch der Sortierung und
    späteren Plausibilitätsprüfungen.
    """
    brutto = round((r.get("summen") or {}).get("brutto", 0.0), 2)
    b = (buchungen or {}).get(r.get("buchung"))
    provision = 0.0
    if b:
        try:
            provision = round(float(b.get("commission-included") or 0), 2)
        except (TypeError, ValueError):
            provision = 0.0
    return round(brutto - provision, 2), provision


def kandidaten(bewegung, cfg=None, buchungen=None, jahr=None):
    """Rechnungen zu dieser Zahlung, die wahrscheinlichste zuerst.

    Sortiert wird nach drei Merkmalen – **nicht** nach Betragsgleichheit, die
    trifft an den echten Daten in 1,5 % der Fälle:

    1. **Namenstreffer** im Verwendungszweck (Direktzahler),
    2. **passende Wohnung** über die gelernte Portal-Kennung,
    3. **Datum** – wer länger wartet, steht weiter oben.

    Jeder Treffer trägt seinen erwarteten Auszahlungsbetrag und den Grund, aus
    dem er vorgeschlagen wird. Der Grund gehört dazu: ein Vorschlag, den man
    nicht nachvollziehen kann, wird entweder blind übernommen oder ignoriert.
    """
    text = ((bewegung.get("gegenpartei") or "") + " " + (bewegung.get("text") or ""))
    woerter = _name_teile(text)
    wohnung = wohnung_zu_kennung(kennung(bewegung), cfg)
    raus = []
    for r in offene(jahr):
        betrag, provision = erwartet(r, buchungen)
        gast = _name_teile(r.get("gast", ""))
        namenstreffer = bool(gast & woerter)
        passt_wohnung = bool(wohnung) and r.get("wohnung") == wohnung
        grund = ("Name im Verwendungszweck" if namenstreffer else
                 "gleiche Wohnung" if passt_wohnung else "offen")
        raus.append({"rechnung": r, "erwartet": betrag, "provision": provision,
                     "namenstreffer": namenstreffer, "wohnung": passt_wohnung,
                     "naehe": _naehe(r, bewegung), "grund": grund})
    raus.sort(key=lambda k: (not k["namenstreffer"], not k["wohnung"], k["naehe"]))
    return raus


def provisionsprobe(bewegung, buchungen=None):
    """Der offene Rest gegen die Provisionen aus Smoobu – **nur als Anhalt**.

    ⚠ **Nicht als Wahrheit verwenden.** Der Betreiber hat am 8.8.2026
    widersprochen: `commission-included` aus Smoobu stimmt nicht verlässlich.
    Maßgeblich sind die **monatlichen Belege von Booking und Airbnb**, die das
    Steuerbüro gegen die Auszahlungen bucht.

    Die Funktion bleibt für spätere Plausibilitätsprüfungen erhalten, wird aber
    in der Oberfläche **nicht** mehr als Befund gezeigt – eine Nachrechnung
    gegen eine unzuverlässige Zahl erzeugt Fehlalarme („es fehlt eine
    Rechnung", wo nur die Schätzung daneben lag).

    Gibt (rest, geschaetzte_provision, stimmt) zurück.
    """
    from app import db
    rest = zuordnung.rest(bewegung)
    summe = 0.0
    for z in zuordnung.posten(bewegung["id"]):
        if z["art"] != zuordnung.RECHNUNG or not z.get("ziel_id"):
            continue
        r = db.holen("rechnungen", z["ziel_id"]) or {}
        _betrag, provision = erwartet(r, buchungen)
        summe += provision
    erwartete = round(-summe, 2)          # sie mindert die Auszahlung
    return rest, erwartete, abs(rest - erwartete) < 0.02


def _naehe(r, bewegung):
    """Wie weit liegt der **Aufenthalt** vom Zahltag entfernt (in Tagen)?

    **Nicht das Rechnungsdatum.** Eine frühere Fassung schloss Rechnungen aus,
    die nach dem Zahltag ausgestellt wurden – das schien plausibel und war
    falsch: Gäste zahlen **vor** dem Aufenthalt, die Rechnung folgt danach. An
    den echten Daten trugen alle 48 Rechnungen den Tag ihrer Erstellung
    (7.8.2026), während die Zahlungen von Januar bis Juli reichten. Die Regel
    hat damit **jeden** Kandidaten verworfen: null Vorschläge für eine Zahlung,
    zu der es eine passende Rechnung gab.

    Deshalb wird nichts mehr ausgeschlossen, nur noch sortiert – und zwar über
    den Aufenthalt, der tatsächlich mit der Zahlung zusammenhängt.
    """
    tag = (bewegung.get("datum") or "")[:10]
    if not tag:
        return 10 ** 6
    from datetime import date

    def _d(s):
        try:
            j, m, t = str(s)[:10].split("-")
            return date(int(j), int(m), int(t))
        except (ValueError, AttributeError):
            return None
    zahltag = _d(tag)
    an, ab = _d(r.get("anreise")), _d(r.get("abreise"))
    if not zahltag or not (an or ab):
        return 10 ** 5
    # Liegt der Zahltag im Aufenthalt, ist die Nähe null.
    if an and ab and an <= zahltag <= ab:
        return 0
    kandidat = min((abs((x - zahltag).days) for x in (an, ab) if x), default=10 ** 5)
    return kandidat
