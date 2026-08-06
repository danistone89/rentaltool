"""Tests für die Arbeitszeit-Erfassung (ohne Standort, DSGVO)."""
from datetime import date, datetime

from app import feiertage, timetrack


def test_checkin_checkout():
    e = timetrack.check_in("putzi", now=datetime(2026, 7, 2, 8, 0, 0))
    assert e and timetrack.get_open("putzi")
    assert timetrack.check_in("putzi", now=datetime(2026, 7, 2, 8, 5)) is None
    c = timetrack.check_out("putzi", now=datetime(2026, 7, 2, 10, 30))
    assert c and not timetrack.get_open("putzi")
    assert timetrack.duration_minutes(c) == 150
    assert timetrack.fmt_dur(150) == "2:30 h"


def test_getrennte_benutzer():
    timetrack.check_in("a", now=datetime(2026, 7, 2, 8))
    timetrack.check_in("b", now=datetime(2026, 7, 2, 9))
    assert timetrack.get_open("a") and timetrack.get_open("b")
    assert len(timetrack.entries("a")) == 1
    assert len(timetrack.entries()) == 2


def test_offene_dauer():
    e = timetrack.check_in("a", now=datetime(2026, 7, 2, 8))
    assert timetrack.duration_minutes(e) is None
    assert timetrack.fmt_dur(None) == "läuft…"


# ---------------------------------------------- Tagesart, Stundensätze, Aggregat
def _eintrag(user, tag, von, bis, tmp_path=None):
    return {"user": user, "checkin": f"{tag}T{von}:00", "checkout": f"{tag}T{bis}:00"}


def test_kind_of_nutzt_den_checkin_tag():
    # Einsatz laeuft ueber Mitternacht in den Feiertag hinein -> zaehlt zum Starttag
    e = {"user": "a", "checkin": "2026-04-30T22:00:00", "checkout": "2026-05-01T02:00:00"}
    assert timetrack.kind_of(e) == feiertage.WERKTAG
    assert timetrack.entry_date(e) == date(2026, 4, 30)


def test_rate_ohne_wochenendsatz_gilt_werktagssatz_ueberall():
    u = {"stundensatz_werktag": 15}
    assert timetrack.rate_for(feiertage.WERKTAG, u) == 15
    assert timetrack.rate_for(feiertage.WOCHENENDE, u) == 15


def test_rate_mit_aktiviertem_wochenendsatz():
    u = {"stundensatz_werktag": 15, "stundensatz_wochenende": 20,
         "wochenendsatz_aktiv": True}
    assert timetrack.rate_for(feiertage.WERKTAG, u) == 15
    assert timetrack.rate_for(feiertage.WOCHENENDE, u) == 20


def test_rate_aktiv_aber_ohne_wert_faellt_auf_werktag_zurueck():
    u = {"stundensatz_werktag": 15, "wochenendsatz_aktiv": True}
    assert timetrack.rate_for(feiertage.WOCHENENDE, u) == 15


def test_rate_globale_vorgabe_greift_ohne_eigenen_satz():
    d = {"stundensatz_werktag": 14, "stundensatz_wochenende": 18}
    assert timetrack.rate_for(feiertage.WERKTAG, {}, d) == 14
    assert timetrack.rate_for(feiertage.WOCHENENDE, {"wochenendsatz_aktiv": True}, d) == 18
    # eigener Satz schlaegt die Vorgabe
    assert timetrack.rate_for(feiertage.WERKTAG, {"stundensatz_werktag": 16}, d) == 16


def test_rate_akzeptiert_komma_und_muell():
    assert timetrack.rate_for(feiertage.WERKTAG, {"stundensatz_werktag": "15,50"}) == 15.5
    assert timetrack.rate_for(feiertage.WERKTAG, {"stundensatz_werktag": "abc"}) == 0.0
    assert timetrack.rate_for(feiertage.WERKTAG, {}) == 0.0


def test_amount():
    assert timetrack.amount(90, 20) == 30.0
    assert timetrack.amount(50, 15) == 12.5
    assert timetrack.amount(0, 20) == 0.0


def test_aggregate_trennt_werktag_und_wochenende():
    rows = [
        _eintrag("a", "2026-07-01", "08:00", "12:00"),   # Mi  -> 240 min Werktag
        _eintrag("a", "2026-07-05", "09:00", "12:00"),   # So  -> 180 min Wochenende
        _eintrag("a", "2026-05-01", "10:00", "11:00"),   # Feiertag -> 60 min
        _eintrag("b", "2026-07-02", "08:00", "10:00"),   # Do  -> 120 min Werktag
    ]
    users = {"a": {"stundensatz_werktag": 15, "stundensatz_wochenende": 20,
                   "wochenendsatz_aktiv": True},
             "b": {"stundensatz_werktag": 12}}
    agg = timetrack.aggregate(rows, users)

    a = agg["a"]
    assert a["minutes"][feiertage.WERKTAG] == 240
    assert a["minutes"][feiertage.WOCHENENDE] == 240      # 180 + 60
    assert a["total_minutes"] == 480
    assert a["amount"][feiertage.WERKTAG] == 60.0         # 4 h * 15
    assert a["amount"][feiertage.WOCHENENDE] == 80.0      # 4 h * 20
    assert a["total_amount"] == 140.0

    b = agg["b"]
    assert b["minutes"][feiertage.WOCHENENDE] == 0
    assert b["total_amount"] == 24.0                      # 2 h * 12


def test_aggregate_ohne_saetze_liefert_null_betraege():
    rows = [_eintrag("a", "2026-07-01", "08:00", "12:00")]
    agg = timetrack.aggregate(rows, {})
    assert agg["a"]["total_minutes"] == 240
    assert agg["a"]["total_amount"] == 0.0


# --------------------------------------------------- Abrechnungsstatus
def test_abrechnen_markieren_und_zuruecknehmen():
    a = timetrack.add_manual("putzi", datetime(2026, 7, 2, 8), datetime(2026, 7, 2, 10))
    b = timetrack.add_manual("putzi", datetime(2026, 7, 3, 8), datetime(2026, 7, 3, 11))
    assert not timetrack.is_billed(a) and not timetrack.is_billed(b)

    n = timetrack.mark_billed([a["id"]], "admin", when=datetime(2026, 8, 1, 12))
    assert n == 1
    eintraege = {e["id"]: e for e in timetrack.entries("putzi")}
    assert timetrack.is_billed(eintraege[a["id"]])
    assert eintraege[a["id"]]["abgerechnet_von"] == "admin"
    assert not timetrack.is_billed(eintraege[b["id"]])

    # erneutes Markieren aendert nichts (Meldezeitpunkt bleibt erhalten)
    assert timetrack.mark_billed([a["id"]], "wer-anders") == 0
    eintraege = {e["id"]: e for e in timetrack.entries("putzi")}
    assert eintraege[a["id"]]["abgerechnet_von"] == "admin"

    assert timetrack.unmark_billed([a["id"]]) == 1
    assert not timetrack.is_billed(timetrack.get_entry(a["id"]))


def test_summary_kennzahlen():
    a = timetrack.add_manual("putzi", datetime(2026, 7, 2, 8), datetime(2026, 7, 2, 10),
                             apartment="Cottaer Straße")          # Do, 120 min
    timetrack.add_manual("putzi", datetime(2026, 7, 4, 8), datetime(2026, 7, 4, 11),
                         apartment="Wernerstraße")                # Sa, 180 min
    timetrack.mark_billed([a["id"]], "admin")

    s = timetrack.summary(timetrack.entries("putzi"),
                          {"stundensatz_werktag": 15, "stundensatz_wochenende": 20,
                           "wochenendsatz_aktiv": True})
    assert s["minutes"] == 300 and s["count"] == 2
    assert s["avg_minutes"] == 150
    assert s["minutes_werktag"] == 120 and s["minutes_wochenende"] == 180
    assert s["amount"] == 90.0                    # 2h*15 + 3h*20
    assert s["billed_minutes"] == 120 and s["billed_count"] == 1
    assert s["open_minutes"] == 180 and s["open_count"] == 1
    assert s["billed_amount"] == 30.0 and s["open_amount"] == 60.0
    assert s["apartments"] == {"Cottaer Straße", "Wernerstraße"}
    assert s["last_date"] == date(2026, 7, 4)


def test_summary_ignoriert_laufende_einsaetze():
    timetrack.check_in("putzi", now=datetime(2026, 7, 2, 8))
    s = timetrack.summary(timetrack.entries("putzi"))
    assert s["count"] == 0 and s["minutes"] == 0 and s["avg_minutes"] == 0
