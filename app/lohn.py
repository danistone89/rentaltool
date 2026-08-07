#!/usr/bin/env python3
"""Was am Monatsende auf dem Zettel steht – und die Minijob-Grenze im Blick.

Wer sich eine Reinigung nimmt, sieht heute erst am 19., was dabei herauskam.
Für einen Minijob ist das zu spät: **wird die Grenze überschritten, ist die
Beschäftigung nicht mehr geringfügig** – mit Folgen für Sozialversicherung und
Steuer, die niemand rückwirkend geradebiegt.

**Die Grenze wird gerechnet, nicht gepflegt.** Sie hängt am Mindestlohn:
Mindestlohn × 130 ÷ 3, aufgerundet auf volle Euro (§ 8 Abs. 1a SGB IV). Aus
12,82 € werden 556 (2025), aus 13,90 € werden 603 (2026), aus 14,60 € werden
633 (2027) – alle drei Werte trifft die Formel genau. Eine fest eingetragene
Zahl wäre spätestens im Januar falsch, und falsch würde sie still.

**Gerechnet wird im Abrechnungsmonat (19.–18.)**, nicht im Kalendermonat. Das
ist der Zeitraum, den das Steuerbüro meldet – die Zahl hier muss zu der dort
passen, sonst warnt sie vor etwas anderem, als am Ende gemeldet wird.

**Mehr arbeiten ist kein Fehler.** Wer in einem Monat über die Grenze kommt,
verliert die Stunden nicht: Ausgezahlt wird höchstens bis zur Grenze, der Rest
bleibt als Zeitkonto stehen und kommt in einem Monat mit Luft dazu. Ohne das
müsste jemand Arbeit ablehnen, die längst getan ist – oder die Grenze reißen.
"""
import math
import statistics
from datetime import date

from app import bookings, feiertage, timetrack

# Gesetzlicher Mindestlohn je Jahr. Nur diese Tabelle ist zu pflegen – die
# Grenze folgt daraus.
MINDESTLOHN = {2024: 12.41, 2025: 12.82, 2026: 13.90, 2027: 14.60}

# So oft darf die Grenze im Jahr überschritten werden (§ 8 Abs. 1b SGB IV).
AUSNAHMEN_JE_JAHR = 2

# Wie lange eine Reinigung dauert, wenn es dazu noch keine eigene Erfahrung
# gibt. Bewusst knapp: eine zu hohe Schätzung warnt vor einer Überschreitung,
# die gar nicht droht, und das nimmt der Anzeige den Ernst.
VORGABE_DAUER = 90


def mindestlohn(jahr):
    """Der Mindestlohn dieses Jahres – für unbekannte Jahre der letzte bekannte."""
    if jahr in MINDESTLOHN:
        return MINDESTLOHN[jahr]
    bekannt = sorted(MINDESTLOHN)
    return MINDESTLOHN[bekannt[-1] if jahr > bekannt[-1] else bekannt[0]]


def grenze(jahr=None):
    """Die Geringfügigkeitsgrenze dieses Jahres in Euro."""
    return math.ceil(mindestlohn(jahr or date.today().year) * 130 / 3)


# --------------------------------------------------------- Dauer schätzen
def dauer_schaetzung(eintraege):
    """Wie lange eine Reinigung bei diesem Mitarbeiter erfahrungsgemäß dauert.

    Der Median, nicht der Mittelwert: ein einziger vergessener Check-out über
    Nacht würde den Durchschnitt für Monate verderben. Ohne Erfahrung greift
    die Vorgabe.
    """
    dauern = [d for d in (timetrack.duration_minutes(e) for e in eintraege
                          if e.get("checkout")) if d and 5 <= d <= 480]
    if not dauern:
        return VORGABE_DAUER
    return int(statistics.median(dauern))


# ------------------------------------------------------------- Prognose
def _monatsfenster(abrechnungsmonat):
    from app.ui.basis import _billing_period
    return _billing_period(abrechnungsmonat)


def offene_einsaetze(user, jobs, von, bis):
    """Zugewiesene Reinigungen im Zeitraum, für die noch keine Zeit erfasst ist.

    Nur die zählen für die Vorschau: was schon erfasst ist, steckt bereits im
    verdienten Betrag und darf nicht doppelt erscheinen.
    """
    offen = []
    for j in jobs or []:
        tag = (j.get("departure") or "")[:10]
        if not (von.isoformat() <= tag <= bis.isoformat()):
            continue
        if bookings.assignee_of(j["id"]) != user:
            continue
        if any(e.get("checkout") for e in timetrack.entries_for_booking(j["id"])):
            continue
        offen.append(j)
    return offen


def monatswerte(user, user_cfg=None, defaults=None, heute=None):
    """Was in jedem Abrechnungsmonat erarbeitet wurde – ältester zuerst."""
    from app.ui.basis import _billing_month
    heute = heute or date.today()
    je_monat = {}
    for e in timetrack.entries(user):
        if e.get("checkout"):
            je_monat.setdefault(_billing_month(e["checkin"]), []).append(e)
    return [(m, timetrack.summary(rows, user_cfg, defaults)["amount"])
            for m, rows in sorted(je_monat.items())]


def zeitkonto(user, user_cfg=None, defaults=None, heute=None, bis_monat=None):
    """Was aus früheren Monaten noch offen ist.

    Wer in einem Monat mehr arbeitet, als die Grenze zulässt, verliert die
    Stunden nicht: Ausgezahlt wird höchstens bis zur Grenze, der Rest bleibt
    stehen und kommt in einem Monat mit Luft dazu. Das ist der übliche Weg,
    einen Minijob über Monate mit ungleicher Auslastung zu führen – ohne ihn
    müsste man Arbeit ablehnen, die längst getan ist.

    Gerechnet wird über alle abgeschlossenen Monate von vorn: jeder Monat
    zahlt bis zur Grenze aus, was er selbst und das Konto hergeben.
    """
    from app.ui.basis import _billing_month
    heute = heute or date.today()
    laufend = bis_monat or _billing_month(heute.isoformat())
    stand = 0.0
    for monat, wert in monatswerte(user, user_cfg, defaults, heute):
        if monat >= laufend:
            break
        verfuegbar = wert + stand
        stand = round(max(0.0, verfuegbar - grenze(int(monat[:4]))), 2)
    return stand


def prognose(user, jobs, user_cfg=None, defaults=None, heute=None, abrechnungsmonat=None):
    """Was dieser Monat voraussichtlich bringt – und ob die Grenze hält.

    `jobs` sind die anstehenden Reinigungen (siehe buchungen._cleaning_jobs).
    Zurück kommt alles, was die Anzeige braucht, in Euro und Minuten.
    """
    from app.ui.basis import _billing_month
    heute = heute or date.today()
    monat = abrechnungsmonat or _billing_month(heute.isoformat())
    von, bis = _monatsfenster(monat)

    eigene = [e for e in timetrack.entries(user) if e.get("checkout")]
    im_monat = [e for e in eigene if _billing_month(e["checkin"]) == monat]
    verdient = timetrack.summary(im_monat, user_cfg, defaults)["amount"]

    schnitt = dauer_schaetzung(eigene)
    offen = offene_einsaetze(user, jobs, max(von, heute), bis)
    erwartet, minuten = 0.0, 0
    for j in offen:
        try:
            tag = date.fromisoformat(j["departure"][:10])
        except (ValueError, KeyError, TypeError):
            continue
        satz = timetrack.rate_for(feiertage.kind_of(tag), user_cfg, defaults)
        erwartet += timetrack.amount(schnitt, satz)
        minuten += schnitt

    summe = round(verdient + erwartet, 2)
    limit = grenze(bis.year)
    vortrag = zeitkonto(user, user_cfg, defaults, heute, monat)
    verfuegbar = round(summe + vortrag, 2)
    auszahlbar = round(min(verfuegbar, limit), 2)
    neuer_vortrag = round(verfuegbar - auszahlbar, 2)
    return {
        "monat": monat, "von": von, "bis": bis,
        "verdient": round(verdient, 2),
        "erwartet": round(erwartet, 2),
        "summe": summe,                 # was dieser Monat an Arbeit wert ist
        "vortrag": round(vortrag, 2),   # was vom Zeitkonto dazukommt
        "auszahlbar": auszahlbar,       # was davon in diesem Monat ausgezahlt wird
        "zeitkonto": neuer_vortrag,     # was danach stehen bleibt
        "einsaetze_offen": len(offen),
        "minuten_offen": minuten,
        "dauer_schnitt": schnitt,
        "grenze": limit,
        "rest": round(limit - auszahlbar, 2),
        "ueber": verfuegbar > limit,
        "auslastung": (auszahlbar / limit) if limit else 0.0,
    }


def ueberschreitungen_im_jahr(user, user_cfg=None, defaults=None, heute=None):
    """Wie oft die Grenze dieses Jahr schon gerissen wurde.

    Gebraucht, damit die Warnung ehrlich bleibt: zweimal im Jahr ist erlaubt,
    und wer davor pauschal warnt, wird nicht mehr gelesen.
    """
    from app.ui.basis import _billing_month
    heute = heute or date.today()
    eigene = [e for e in timetrack.entries(user) if e.get("checkout")]
    je_monat = {}
    for e in eigene:
        monat = _billing_month(e["checkin"])
        if monat.startswith(str(heute.year)):
            je_monat.setdefault(monat, []).append(e)
    limit = grenze(heute.year)
    return sum(1 for rows in je_monat.values()
               if timetrack.summary(rows, user_cfg, defaults)["amount"] > limit)
