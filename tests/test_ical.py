"""Kalender-Export eines Reinigungsauftrags."""
from datetime import datetime

from app import ical


def _job(**kw):
    job = {"id": 901, "apartment_name": "Cottaer Straße", "departure": "2026-08-05",
           "checkout_time": "10:00", "guest": "Abreise Gast", "next": None}
    job.update(kw)
    return job


def _felder(daten):
    """Felder des VEVENT-Blocks als dict + alle (entfalteten) Zeilen.

    Nur der VEVENT-Block, und ohne den VALARM darin: VTIMEZONE traegt ein
    eigenes DTSTART, der VALARM eine eigene DESCRIPTION – beides wuerde die
    Werte des Termins ueberdecken.
    """
    text = daten.decode("utf-8").replace("\r\n ", "")     # Faltung aufheben
    zeilen = text.split("\r\n")
    d, drin = {}, False
    for z in zeilen:
        if z == "BEGIN:VEVENT":
            drin = True; continue
        if z in ("END:VEVENT", "BEGIN:VALARM"):
            drin = False; continue
        if z == "END:VALARM":
            drin = True; continue
        if drin and ":" in z:
            k, v = z.split(":", 1)
            d[k.split(";")[0]] = v
    return d, zeilen


def test_grundgeruest_und_zeiten():
    daten = ical.cleaning_event(_job(), jetzt=datetime(2026, 8, 1, 12, 0, 0))
    d, zeilen = _felder(daten)
    assert zeilen[0] == "BEGIN:VCALENDAR"
    assert zeilen[-2] == "END:VCALENDAR"          # letzte Zeile ist leer (CRLF)
    assert "BEGIN:VTIMEZONE" in zeilen and "TZID:Europe/Berlin" in zeilen
    assert d["UID"] == "reinigung-901@livaro-suites"
    assert d["DTSTAMP"] == "20260801T120000"
    assert d["DTSTART"] == "20260805T100000"      # Check-out
    assert d["DTEND"] == "20260805T120000"        # ohne Folgebuchung: +2 h
    assert "TZID=Europe/Berlin" in daten.decode("utf-8")
    assert d["SUMMARY"] == "Reinigung Cottaer Straße"


def test_wechseltag_endet_zur_anreise():
    job = _job(next={"arrival": "2026-08-05", "checkin_time": "15:00",
                     "adults": 3, "children": 2, "guest": "Familie Neu"})
    d, _ = _felder(ical.cleaning_event(job))
    assert d["DTSTART"] == "20260805T100000"
    assert d["DTEND"] == "20260805T150000"        # bis zur Anreise
    assert d["SUMMARY"].endswith("(Wechseltag)")
    assert "Vorbereiten für 5 Personen" in d["DESCRIPTION"]
    assert "Familie Neu" in d["DESCRIPTION"]


def test_anreise_vor_checkout_faellt_auf_zwei_stunden_zurueck():
    """Kaputte Daten dürfen kein Ende vor dem Anfang erzeugen."""
    job = _job(next={"arrival": "2026-08-05", "checkin_time": "08:00"})
    d, _ = _felder(ical.cleaning_event(job))
    assert d["DTEND"] == "20260805T120000"


def test_folgebuchung_an_anderem_tag_zaehlt_nicht_als_fenster():
    job = _job(next={"arrival": "2026-08-08", "checkin_time": "15:00", "adults": 2})
    d, _ = _felder(ical.cleaning_event(job))
    assert d["DTEND"] == "20260805T120000"        # +2 h, nicht 3 Tage
    assert "Anreise 2026-08-08" in d["DESCRIPTION"]


def test_sonderzeichen_werden_maskiert():
    job = _job(apartment_name="Haus A; B, C\\D", next=None)
    text = ical.cleaning_event(job).decode("utf-8")
    assert "Haus A\\; B\\, C\\\\D" in text
    # Mehrzeilige Beschreibung wird zu \n, nie zu echtem Zeilenumbruch im Feld
    d, _ = _felder(ical.cleaning_event(_job()))
    assert "\\n" in d["DESCRIPTION"]


def test_zeilen_werden_auf_75_oktette_gefaltet():
    job = _job(apartment_name="Sehr langer Wohnungsname " * 6)
    text = ical.cleaning_event(job).decode("utf-8")
    for zeile in text.split("\r\n"):
        assert len(zeile.encode("utf-8")) <= 75, f"zu lang: {zeile!r}"
    # nach dem Entfalten muss der Name wieder vollständig da sein
    d, _ = _felder(ical.cleaning_event(job))
    assert "Sehr langer Wohnungsname" in d["SUMMARY"]


def test_erinnerung_optional():
    mit = ical.cleaning_event(_job()).decode("utf-8")
    assert "BEGIN:VALARM" in mit and "TRIGGER:-PT60M" in mit
    ohne = ical.cleaning_event(_job(), erinnerung_min=0).decode("utf-8")
    assert "VALARM" not in ohne


def test_dateiname_ohne_sonderzeichen():
    assert ical.dateiname(_job()) == "Reinigung_Cottaer_Straße_2026-08-05.ics"
    # Pfadtrenner duerfen nicht durchkommen
    name = ical.dateiname(_job(apartment_name="../a b/c"))
    assert "/" not in name and ".." not in name, name
    assert name.endswith("_2026-08-05.ics")


def test_fehlende_zeiten_stuerzen_nicht_ab():
    d, _ = _felder(ical.cleaning_event(_job(checkout_time=None)))
    assert d["DTSTART"] == "20260805T100000"      # Vorgabe 10:00
