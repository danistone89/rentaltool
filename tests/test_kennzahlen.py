"""Kennzahlen: Auslastung, Umsatz, Reinigungskosten, Deckungsbeitrag.

Eine Auswertung, die falsch rechnet, merkt niemand – sie sieht ja aus wie eine
Auswertung. Deshalb hier vor allem die Fälle, in denen man sich vertut:
Buchungen über den Monatswechsel, die durchlaufende Beherbergungssteuer, und
die Frage, was überhaupt in den Deckungsbeitrag gehört.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import kennzahlen, steuer  # noqa: E402
from tests.test_web import _login, mock_backend  # noqa: E402,F401

APTS = {2748963: "Cottaer Straße", 2960031: "Wernerstraße"}


def _buchung(bid, apt_id, apt, an, ab, preis, erwachsene=2, kanal="Direct booking",
             details=""):
    return {"id": bid, "type": "reservation", "is-blocked-booking": False,
            "apartment": {"id": apt_id, "name": apt}, "arrival": an, "departure": ab,
            "price": preis, "adults": erwachsene, "children": 0,
            "channel": {"name": kanal}, "price-details": details}


def _zeit(user, tag, minuten, buchung=None, wohnung=None):
    beginn = datetime.fromisoformat(f"{tag}T09:00:00")
    ende = beginn.replace(hour=9 + minuten // 60, minute=minuten % 60)
    return {"id": f"{tag}-{user}", "user": user, "checkin": beginn.isoformat(),
            "checkout": ende.isoformat(), "booking_id": buchung, "apartment": wohnung}


# ------------------------------------------------------------ Nächte
def test_naechte_zaehlen_naechte_und_nicht_tage():
    """Anreise 29.10., Abreise 1.11. sind drei Nächte – alle im Oktober."""
    b = _buchung(1, 2748963, "Cottaer Straße", "2025-10-29", "2025-11-01", 300)
    assert kennzahlen.naechte_je_monat(b) == {"2025-10": 3}


def test_naechte_ueber_den_monatswechsel_werden_geteilt():
    b = _buchung(1, 2748963, "Cottaer Straße", "2025-10-30", "2025-11-03", 500)
    assert kennzahlen.naechte_je_monat(b) == {"2025-10": 2, "2025-11": 2}


def test_stornos_und_blockierungen_zaehlen_nicht():
    storno = dict(_buchung(1, 2748963, "C", "2026-08-01", "2026-08-05", 400),
                  type="cancellation")
    block = dict(_buchung(2, 2748963, "C", "2026-08-01", "2026-08-05", 0))
    block["is-blocked-booking"] = True
    assert kennzahlen.naechte_je_monat(storno) == {}
    assert kennzahlen.naechte_je_monat(block) == {}


# ------------------------------------------------------------ Umsatz
def test_umsatz_ist_ohne_die_durchlaufende_beherbergungssteuer():
    """Die vom Gast gezahlte Beherbergungssteuer geht an die Stadt – sie ist
    kein Umsatz. Dieselbe Regel wie in der Steueranmeldung."""
    b = _buchung(1, 2748963, "Cottaer Straße", "2026-08-01", "2026-08-05", 400.07)
    netto, cityt = steuer.ohne_citytax(b)
    assert netto == 377.42 and cityt == 22.65        # Rechnung 60 (Anja Ernst)
    assert kennzahlen.umsatz_je_monat(b) == {"2026-08": 377.42}


def test_ausgewiesene_steuer_schlaegt_die_umrechnung():
    """Die Wernerstraße rechnet bei Booking.com mit 7 % – nur der ausgewiesene
    Betrag trifft dann die Wirklichkeit."""
    b = _buchung(1, 2960031, "Wernerstraße", "2026-08-01", "2026-08-03", 329.68,
                 kanal="Booking.com",
                 details="Reinigungsgebühr - EUR 95\nÜbernachtungssteuer - EUR 13.28")
    assert kennzahlen.umsatz_je_monat(b) == {"2026-08": 316.40}


def test_umsatz_folgt_den_naechten_ueber_den_monatswechsel():
    b = _buchung(1, 2748963, "Cottaer Straße", "2025-10-30", "2025-11-03", 424.0)
    verteilt = kennzahlen.umsatz_je_monat(b)
    assert set(verteilt) == {"2025-10", "2025-11"}
    # 424 / 1,06 = 400,00 netto, hälftig auf zwei Nächte je Monat
    assert verteilt == {"2025-10": 200.0, "2025-11": 200.0}


def test_rundungsrest_geht_nicht_verloren():
    """Sonst fehlen in der Jahressumme Cent-Beträge, die niemand wiederfindet."""
    b = _buchung(1, 2748963, "Cottaer Straße", "2025-10-31", "2025-11-03", 106.0)
    verteilt = kennzahlen.umsatz_je_monat(b)
    netto, _s = steuer.ohne_citytax(b)
    assert round(sum(verteilt.values()), 2) == netto


# ------------------------------------------------------------ Reinigungskosten
def test_reinigungskosten_rechnen_mit_dem_stundensatz():
    zeiten = [_zeit("vale", "2026-08-05", 120, buchung="601")]
    users = {"vale": {"stundensatz_werktag": 15}}
    kosten = kennzahlen.reinigungskosten(zeiten, 2026, 8, users, {},
                                         {"601": "Cottaer Straße"})
    assert kosten == {"Cottaer Straße": {"minuten": 120, "kosten": 30.0}}


def test_reinigung_ohne_buchung_zaehlt_ueber_den_wohnungsnamen():
    zeiten = [_zeit("vale", "2026-08-05", 60, wohnung="Wernerstraße")]
    kosten = kennzahlen.reinigungskosten(zeiten, 2026, 8,
                                         {"vale": {"stundensatz_werktag": 20}}, {})
    assert kosten["Wernerstraße"]["kosten"] == 20.0


def test_laufender_einsatz_zaehlt_noch_nicht():
    """Ein offener Check-in hat noch keine Dauer – er darf die Kosten nicht
    mit 0 Minuten verwässern oder abstürzen."""
    offen = _zeit("vale", "2026-08-05", 60)
    offen["checkout"] = None
    offen["apartment"] = "Cottaer Straße"
    assert kennzahlen.reinigungskosten([offen], 2026, 8) == {}


def test_zeiten_aus_anderen_monaten_bleiben_draussen():
    zeiten = [_zeit("vale", "2026-07-30", 60, wohnung="Cottaer Straße")]
    assert kennzahlen.reinigungskosten(zeiten, 2026, 8) == {}


# ------------------------------------------------------------ Material
def test_belege_werden_der_wohnung_zugeordnet():
    belege = [{"ts": "2026-08-03T10:00:00", "amount": "12,34",
               "apartment_name": "Cottaer Straße"},
              {"ts": "2026-08-04T10:00:00", "amount": "7,66",
               "apartment_name": "Cottaer Straße"}]
    assert kennzahlen.material(belege, 2026, 8) == {"Cottaer Straße": 20.0}


def test_beleg_ohne_wohnung_wird_nicht_still_verteilt():
    """Eine erfundene Aufteilung sähe genauer aus, als sie ist."""
    belege = [{"ts": "2026-08-03T10:00:00", "amount": "50,00"}]
    assert kennzahlen.material(belege, 2026, 8) == {"ohne Zuordnung": 50.0}


def test_unlesbarer_betrag_wird_uebersprungen():
    belege = [{"ts": "2026-08-03T10:00:00", "amount": "?", "apartment_name": "C"}]
    assert kennzahlen.material(belege, 2026, 8) == {}


# ------------------------------------------------------------ Monatsbild
def test_monat_fuehrt_alles_zusammen():
    buchungen = [_buchung(601, 2748963, "Cottaer Straße", "2026-08-01", "2026-08-06",
                          530.0)]          # 500,00 netto, 5 Nächte
    zeiten = [_zeit("vale", "2026-08-06", 120, buchung="601")]
    belege = [{"ts": "2026-08-06T12:00:00", "amount": "20,00",
               "apartment_name": "Cottaer Straße"}]
    users = {"vale": {"stundensatz_werktag": 15}}
    e = kennzahlen.monat(2026, 8, buchungen, zeiten, belege, APTS, users, {})

    cottaer = next(z for z in e["zeilen"] if z["wohnung"] == "Cottaer Straße")
    assert cottaer["naechte"] == 5
    assert cottaer["auslastung"] == round(5 / 31, 4)
    assert cottaer["umsatz"] == 500.0
    assert cottaer["reinigung_kosten"] == 30.0
    assert cottaer["material"] == 20.0
    assert cottaer["deckungsbeitrag"] == 450.0
    assert cottaer["umsatz_je_nacht"] == 100.0

    # Wohnung ohne Buchungen ist eine Aussage, keine Leerstelle
    werner = next(z for z in e["zeilen"] if z["wohnung"] == "Wernerstraße")
    assert werner["naechte"] == 0 and werner["auslastung"] == 0.0

    assert e["summe"]["umsatz"] == 500.0
    assert e["summe"]["verfuegbar"] == 62        # zwei Wohnungen × 31 Tage
    assert e["summe"]["deckungsbeitrag"] == 450.0


def test_auslastung_kann_nicht_ueber_hundert_prozent_gehen():
    """Zwei Buchungen am selben Tag (Wechseltag) zählen die Nacht einmal – der
    Anreisetag des einen ist der Abreisetag des anderen."""
    buchungen = [_buchung(1, 2748963, "Cottaer Straße", "2026-08-01", "2026-08-15", 0),
                 _buchung(2, 2748963, "Cottaer Straße", "2026-08-15", "2026-09-01", 0)]
    e = kennzahlen.monat(2026, 8, buchungen, [], [], {2748963: "Cottaer Straße"})
    zeile = e["zeilen"][0]
    assert zeile["naechte"] == 31 and zeile["auslastung"] == 1.0


def test_reinigung_je_buchung_beantwortet_die_frage_nach_der_wohnung():
    buchungen = [_buchung(601, 2960031, "Wernerstraße", "2026-08-01", "2026-08-06", 500)]
    zeiten = [_zeit("vale", "2026-08-06", 90, buchung="601"),
              _zeit("gabriel", "2026-08-06", 30, buchung="601")]
    users = {"vale": {"stundensatz_werktag": 20}, "gabriel": {"stundensatz_werktag": 20}}
    ergebnis = kennzahlen.reinigung_je_buchung(zeiten, buchungen, users, {})
    assert len(ergebnis) == 1
    _b, minuten, kosten = ergebnis[0]
    assert minuten == 120 and kosten == 40.0


# ------------------------------------------------------------ Oberfläche
async def test_kennzahlen_reiter_zeigt_die_zahlen(user, mock_backend, tmp_path,  # noqa: F811
                                                  monkeypatch):
    """Der Reiter muss auch dann tragen, wenn Smoobu echte Buchungen liefert."""
    from datetime import date
    from app import data as _data, housekeeping as hk, web
    monkeypatch.setattr(hk, "MEDIA_DIR", str(tmp_path / "media"))
    heute = date.today()
    monkeypatch.setattr(_data, "_reservations", lambda *a, **k: [
        _buchung(701, 2748963, "Cottaer Straße",
                 heute.replace(day=1).isoformat(),
                 heute.replace(day=min(6, heute.day if heute.day > 5 else 6)).isoformat(),
                 530.0)])
    monkeypatch.setitem(web.CFG, "stundensatz_werktag", 15)
    await _login(user)
    user.find(marker="nav-uebersicht").click()
    await user.should_see("Kennzahlen")
    user.find("Kennzahlen").click()
    await user.should_see("Auslastung")
    await user.should_see("Deckungsbeitrag")
    await user.should_see("Cottaer Straße")
    # Der Hinweis, der die Zahl vor Fehldeutung schützt
    await user.should_see("ist kein Gewinn")


async def test_kennzahlen_ueberleben_einen_smoobu_ausfall(user, mock_backend,  # noqa: F811
                                                          tmp_path, monkeypatch):
    """Fällt Smoobu aus, darf die Übersicht nicht weiß werden."""
    from app import data as _data, housekeeping as hk, smoobu
    monkeypatch.setattr(hk, "MEDIA_DIR", str(tmp_path / "media"))

    def kaputt(*a, **k):
        raise smoobu.SmoobuError("Smoobu nicht erreichbar")
    monkeypatch.setattr(_data, "_reservations", kaputt)
    await _login(user)
    user.find(marker="nav-uebersicht").click()
    user.find("Kennzahlen").click()
    await user.should_see("nicht verfügbar")
