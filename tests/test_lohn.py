"""Lohnvorschau und Minijob-Grenze.

Wer sich eine Reinigung nimmt, sah bisher erst am 19., was dabei herauskam. Für
einen Minijob ist das zu spät: Wird die Grenze überschritten, ist die
Beschäftigung nicht mehr geringfügig – und das lässt sich rückwirkend nicht
geradebiegen.

`test_die_grenze_wird_gerechnet_nicht_gepflegt` ist der Test, der hier am
meisten trägt: Die Grenze folgt dem Mindestlohn, und eine fest eingetragene Zahl
wäre spätestens im Januar falsch. Still falsch, was schlimmer ist.
"""
from datetime import date, datetime, timedelta

import pytest

from app import bookings, lohn, timetrack
from app.ui.basis import _billing_month, _billing_period


# ------------------------------------------------------------------ Grenze
@pytest.mark.parametrize("jahr,mindestlohn,erwartet", [
    (2024, 12.41, 538),
    (2025, 12.82, 556),
    (2026, 13.90, 603),
    (2027, 14.60, 633),
])
def test_die_grenze_wird_gerechnet_nicht_gepflegt(jahr, mindestlohn, erwartet):
    """Mindestlohn × 130 ÷ 3, aufgerundet (§ 8 Abs. 1a SGB IV). Die Formel
    trifft alle vier amtlich bekannten Werte – eine Tabelle mit festen Beträgen
    wäre beim nächsten Januar falsch, ohne dass es jemand merkt."""
    assert lohn.mindestlohn(jahr) == mindestlohn
    assert lohn.grenze(jahr) == erwartet


def test_unbekannte_jahre_nehmen_den_letzten_bekannten_wert():
    """Lieber der vorjährige Wert als ein Absturz – und lieber zu niedrig als zu
    hoch, damit die Warnung eher zu früh kommt als zu spät."""
    assert lohn.grenze(2035) == lohn.grenze(2027)


# ------------------------------------------------------------ Dauerschätzung
def _eintrag(user, tag, minuten, buchung=None):
    start = datetime.combine(tag, datetime.min.time()).replace(hour=9)
    return timetrack.add_manual(user, start, start + timedelta(minutes=minuten),
                                booking_id=buchung)


def test_ohne_erfahrung_gilt_die_vorgabe():
    assert lohn.dauer_schaetzung([]) == lohn.VORGABE_DAUER


def test_der_median_schuetzt_vor_dem_vergessenen_checkout():
    """Ein einziger über Nacht offener Eintrag würde den Durchschnitt für
    Monate verderben – der Median nicht."""
    heute = date.today()
    for minuten in (80, 90, 100):
        _eintrag("vale", heute, minuten)
    _eintrag("vale", heute, 470)          # vergessener Check-out
    schnitt = lohn.dauer_schaetzung(timetrack.entries("vale"))
    assert 80 <= schnitt <= 100, f"Ausreisser hat durchgeschlagen: {schnitt}"


def test_unsinnige_dauern_zaehlen_nicht():
    heute = date.today()
    _eintrag("vale", heute, 2)            # zu kurz, Fehlbedienung
    _eintrag("vale", heute, 600)          # zu lang, ueber Nacht
    assert lohn.dauer_schaetzung(timetrack.entries("vale")) == lohn.VORGABE_DAUER


# ---------------------------------------------------------------- Prognose
SAETZE = {"stundensatz_werktag": "15", "stundensatz_wochenende": ""}


def _job(nr, tag):
    return {"id": nr, "departure": tag.isoformat(), "apartment_id": 1,
            "apartment_name": "Cottaer Straße"}


def test_ohne_alles_ist_die_prognose_null():
    p = lohn.prognose("vale", [], defaults=SAETZE)
    assert p["verdient"] == 0 and p["erwartet"] == 0 and p["summe"] == 0
    assert p["grenze"] == lohn.grenze(p["bis"].year)
    assert not p["ueber"]


def test_erfasste_zeit_zaehlt_zum_verdienten():
    heute = date.today()
    _eintrag("vale", heute, 120)          # 2 Stunden à 15 € = 30 €
    p = lohn.prognose("vale", [], defaults=SAETZE)
    assert p["verdient"] == 30.0
    assert p["erwartet"] == 0.0


def test_zugewiesene_reinigung_geht_in_die_erwartung():
    """Das ist der Kern: was noch kommt, steht schon in der Zahl."""
    heute = date.today()
    _, bis = _billing_period(_billing_month(heute.isoformat()))
    morgen = min(heute + timedelta(days=1), bis)
    bookings.set_assignment(4711, "vale", by="chef")
    p = lohn.prognose("vale", [_job(4711, morgen)], defaults=SAETZE)
    assert p["einsaetze_offen"] == 1
    assert p["erwartet"] == timetrack.amount(lohn.VORGABE_DAUER, 15)
    assert p["summe"] == p["erwartet"]


def test_fremde_reinigungen_zaehlen_nicht():
    heute = date.today()
    _, bis = _billing_period(_billing_month(heute.isoformat()))
    bookings.set_assignment(4711, "olga", by="chef")
    p = lohn.prognose("vale", [_job(4711, min(heute + timedelta(days=1), bis))],
                      defaults=SAETZE)
    assert p["einsaetze_offen"] == 0


def test_bereits_erfasste_reinigung_zaehlt_nicht_doppelt():
    """Sie steckt schon im verdienten Betrag – zweimal wäre eine erfundene
    Erwartung."""
    heute = date.today()
    bookings.set_assignment(4711, "vale", by="chef")
    _eintrag("vale", heute, 120, buchung=4711)
    p = lohn.prognose("vale", [_job(4711, heute)], defaults=SAETZE)
    assert p["einsaetze_offen"] == 0
    assert p["summe"] == 30.0


def test_reinigungen_ausserhalb_des_monats_zaehlen_nicht():
    heute = date.today()
    bookings.set_assignment(4711, "vale", by="chef")
    weit = _job(4711, heute + timedelta(days=90))
    assert lohn.prognose("vale", [weit], defaults=SAETZE)["einsaetze_offen"] == 0


def test_die_grenze_wird_als_ueberschritten_gemeldet():
    heute = date.today()
    _eintrag("vale", heute, 60 * 45)      # 45 Stunden à 15 € = 675 €
    p = lohn.prognose("vale", [], defaults=SAETZE)
    assert p["summe"] == 675.0
    assert p["ueber"] is True
    assert p["rest"] < 0
    assert p["auslastung"] > 1


def test_knapp_darunter_ist_nicht_ueber():
    heute = date.today()
    _eintrag("vale", heute, 60 * 40)      # 600 € bei Grenze 603
    p = lohn.prognose("vale", [], defaults=SAETZE)
    assert not p["ueber"]
    assert 0 < p["rest"] <= 3


def test_ohne_stundensatz_kommt_kein_betrag():
    """Eine Zahl ohne Satz wäre geraten – und geraten hilft hier niemandem."""
    heute = date.today()
    _eintrag("vale", heute, 120)
    p = lohn.prognose("vale", [], defaults={"stundensatz_werktag": "",
                                            "stundensatz_wochenende": ""})
    assert p["verdient"] == 0.0


# ------------------------------------------------------- Erlaubte Ausnahmen
def test_ueberschreitungen_werden_gezaehlt():
    """Zweimal im Jahr ist erlaubt. Wer davor pauschal warnt, wird nicht mehr
    gelesen – deshalb muss die Anzeige wissen, wie oft es schon war."""
    heute = date.today()
    _eintrag("vale", heute, 60 * 45)      # 675 € in diesem Abrechnungsmonat
    assert lohn.ueberschreitungen_im_jahr("vale", defaults=SAETZE) == 1


def test_normale_monate_zaehlen_nicht_als_ausnahme():
    heute = date.today()
    _eintrag("vale", heute, 120)
    assert lohn.ueberschreitungen_im_jahr("vale", defaults=SAETZE) == 0


def test_zwei_erlaubte_male_stehen_im_modul():
    assert lohn.AUSNAHMEN_JE_JAHR == 2


# ------------------------------------------------------- Das Vorschaufenster
def test_die_liste_blickt_zwei_monate_voraus():
    """Bis 7.8.2026 waren es 21 Tage, zweimal fest eingetragen. Am Monatsanfang
    reichte die Liste damit kaum über den laufenden Monat hinaus – wer im August
    für Oktober planen wollte, sah nichts."""
    from app.ui.buchungen import vorschau_tage
    assert vorschau_tage() == 60


def test_das_fenster_laesst_sich_einstellen(monkeypatch):
    from app import data
    from app.ui.buchungen import vorschau_tage
    monkeypatch.setitem(data.CONFIG, "buchungen_vorschau_tage", 120)
    assert vorschau_tage() == 120


def test_unsinnige_werte_fallen_auf_etwas_brauchbares_zurueck(monkeypatch):
    """Eine Null im Feld darf die Reinigungsliste nicht leeren."""
    from app import data
    from app.ui.buchungen import vorschau_tage
    monkeypatch.setitem(data.CONFIG, "buchungen_vorschau_tage", 0)
    assert vorschau_tage() >= 7
    monkeypatch.setitem(data.CONFIG, "buchungen_vorschau_tage", "Unfug")
    assert vorschau_tage() == 60


def test_die_prognose_deckt_jetzt_den_ganzen_monat():
    """Mit 21 Tagen fehlten der Lohnvorschau am Monatsanfang die Reinigungen
    der letzten Monatswoche – sie versprach zu wenig."""
    from app.ui.basis import _billing_month, _billing_period
    from app.ui.buchungen import vorschau_tage
    heute = date.today()
    _von, bis = _billing_period(_billing_month(heute.isoformat()))
    assert (bis - heute).days <= vorschau_tage(), (
        "Das Vorschaufenster reicht nicht bis zum Ende des Abrechnungsmonats")
