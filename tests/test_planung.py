"""Zuweisung mit Kopf: Stammzuständigkeit, Abwesenheiten, Vorschläge.

Ein Vorschlag, der jemanden im Urlaub einträgt, ist schlimmer als gar keiner:
man verlässt sich darauf, und es fällt am Morgen der Reinigung auf. Deshalb
liegt hier der Schwerpunkt auf dem, was der Vorschlag **nicht** tun darf.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import data, planung  # noqa: E402
from tests.test_web import _login, mock_backend  # noqa: E402,F401

STAFF = {"vale": "Valeriya", "gabriel": "Gabriel"}


@pytest.fixture(autouse=True)
def _saubere_config(monkeypatch):
    monkeypatch.setitem(data.CONFIG, "zustaendigkeit", {})
    monkeypatch.setattr(data, "save_config", lambda: None)


def _job(bid, apt_id, apt, tag):
    return {"id": bid, "apartment_id": apt_id, "apartment_name": apt, "departure": tag}


# ------------------------------------------------------------ Abwesenheiten
def test_abwesenheit_gilt_einschliesslich_der_randtage():
    """Der letzte Urlaubstag ist Urlaub – der klassische Zaunpfahl-Fehler."""
    planung.abwesenheit_anlegen("vale", "2026-08-10", "2026-08-20", "Urlaub")
    assert not planung.ist_abwesend("vale", "2026-08-09")
    assert planung.ist_abwesend("vale", "2026-08-10")
    assert planung.ist_abwesend("vale", "2026-08-20")
    assert not planung.ist_abwesend("vale", "2026-08-21")


def test_abwesenheit_gilt_nur_fuer_die_eingetragene_person():
    planung.abwesenheit_anlegen("vale", "2026-08-10", "2026-08-20")
    assert not planung.ist_abwesend("gabriel", "2026-08-15")


def test_ende_vor_anfang_wird_abgelehnt():
    with pytest.raises(ValueError):
        planung.abwesenheit_anlegen("vale", "2026-08-20", "2026-08-10")


def test_vergangene_abwesenheiten_verschwinden_aus_der_liste():
    planung.abwesenheit_anlegen("vale", "2026-01-01", "2026-01-05")
    planung.abwesenheit_anlegen("vale", "2026-12-01", "2026-12-05")
    kommend = planung.abwesenheiten("vale", ab="2026-08-06")
    assert [a["von"] for a in kommend] == ["2026-12-01"]


# ------------------------------------------------------------ Vorschlag
def test_stammkraft_wird_vorgeschlagen():
    planung.stammkraft_setzen(2748963, "vale")
    assert planung.vorschlag(_job(1, 2748963, "Cottaer", "2026-08-15"), STAFF) == "vale"


def test_abwesende_stammkraft_wird_uebersprungen():
    """Der eigentliche Zweck der ganzen Übung."""
    planung.stammkraft_setzen(2748963, "vale")
    planung.abwesenheit_anlegen("vale", "2026-08-10", "2026-08-20", "Urlaub")
    assert planung.vorschlag(_job(1, 2748963, "Cottaer", "2026-08-15"), STAFF) == "gabriel"
    # …und nach dem Urlaub wieder sie
    assert planung.vorschlag(_job(2, 2748963, "Cottaer", "2026-08-25"), STAFF) == "vale"


def test_ohne_stammkraft_entscheidet_die_last():
    a = planung.vorschlag(_job(1, 999, "Neu", "2026-08-15"), STAFF,
                          last={"vale": 3, "gabriel": 1})
    assert a == "gabriel"


def test_kein_vorschlag_wenn_alle_weg_sind():
    """Lieber gar kein Vorschlag als ein falscher – die Lücke muss auffallen."""
    for u in STAFF:
        planung.abwesenheit_anlegen(u, "2026-08-10", "2026-08-20")
    assert planung.vorschlag(_job(1, 2748963, "Cottaer", "2026-08-15"), STAFF) is None


def test_gleicher_bestand_ergibt_gleichen_vorschlag():
    """Ein Plan, der sich bei jedem Aufruf ändert, ist keiner."""
    jobs = [_job(i, 999, f"W{i}", "2026-08-15") for i in range(4)]
    erste = [(j["id"], w) for j, w in planung.vorschlaege(jobs, STAFF)]
    zweite = [(j["id"], w) for j, w in planung.vorschlaege(jobs, STAFF)]
    assert erste == zweite


# ------------------------------------------------------------ Verteilung über mehrere
def test_stapel_verteilt_sich_statt_sich_zu_haeufen():
    jobs = [_job(i, 999, f"W{i}", "2026-08-15") for i in range(4)]
    verteilt = planung.vorschlaege(jobs, STAFF)
    anzahl = {}
    for _job_, wer in verteilt:
        anzahl[wer] = anzahl.get(wer, 0) + 1
    assert anzahl == {"vale": 2, "gabriel": 2}


def test_vorhandene_last_wird_mitgezaehlt():
    """Wer schon fünf Reinigungen hat, bekommt nicht auch noch die neuen."""
    jobs = [_job(i, 999, f"W{i}", "2026-08-15") for i in range(2)]
    verteilt = planung.vorschlaege(jobs, STAFF, bereits={"vale": 5})
    assert [w for _j, w in verteilt] == ["gabriel", "gabriel"]


def test_stammzustaendigkeit_schlaegt_die_last():
    """Sonst wandert die Wohnung bei jedem Stapel zu jemand anderem – und
    genau das Wissen, wo der Schlüssel hängt, geht verloren."""
    planung.stammkraft_setzen(2748963, "vale")
    jobs = [_job(i, 2748963, "Cottaer", f"2026-08-1{i}") for i in range(1, 4)]
    verteilt = planung.vorschlaege(jobs, STAFF, bereits={"vale": 9})
    assert [w for _j, w in verteilt] == ["vale", "vale", "vale"]


def test_last_je_mitarbeiter_zaehlt_den_bestand():
    jobs = [_job(1, 999, "A", "2026-08-15"), _job(2, 999, "B", "2026-08-16"),
            _job(3, 999, "C", "2026-08-17")]
    zuweisung = {1: "vale", 2: "vale", 3: None}.get
    assert planung.last_je_mitarbeiter(jobs, zuweisung) == {"vale": 2}


# ------------------------------------------------------------ Planungshorizont
def test_horizont_schneidet_weit_entferntes_ab():
    from datetime import date, timedelta
    heute = date(2026, 8, 6)
    jobs = [_job(1, 999, "bald", (heute + timedelta(days=3)).isoformat()),
            _job(2, 999, "spaeter", (heute + timedelta(days=30)).isoformat()),
            _job(3, 999, "gestern", (heute - timedelta(days=1)).isoformat())]
    drin = [j["apartment_name"] for j in planung.naechste_tage(jobs, 14, ab=heute)]
    assert drin == ["bald"]


# ------------------------------------------------------------ Stammzuständigkeit
def test_stammkraft_setzen_und_loeschen():
    planung.stammkraft_setzen(2748963, "vale")
    assert planung.stammkraefte() == {"2748963": "vale"}
    planung.stammkraft_setzen(2748963, None)
    assert planung.stammkraft(2748963) is None


# ------------------------------------------------------------ Sammelzuweisung (Oberfläche)
async def test_offene_zuweisen_verteilt_alles_auf_einmal(user, mock_backend,  # noqa: F811
                                                         tmp_path, monkeypatch):
    """Der eigentliche Gewinn: nicht mehr Buchung für Buchung."""
    from datetime import date, timedelta
    from app import auth, bookings, data as _data, housekeeping as hk, web
    monkeypatch.setattr(hk, "MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setitem(web.USERS, "vale", {
        "password_hash": auth.hash_password("vale"), "role": "putzkraft",
        "totp_secret": "", "name": "Valeriya"})
    tag = (date.today() + timedelta(days=3)).isoformat()

    def _b(bid, apt_id, apt):
        return {"id": bid, "type": "reservation", "is-blocked-booking": False,
                "apartment": {"id": apt_id, "name": apt},
                "arrival": (date.today() + timedelta(days=1)).isoformat(),
                "departure": tag, "check-in": "15:00", "check-out": "10:00",
                "adults": 2, "children": 0, "guest-name": "Gast",
                "channel": {"name": "Direct booking"}, "notice": ""}
    monkeypatch.setattr(_data, "_reservations", lambda *a, **k: [
        _b(601, 2748963, "Cottaer Straße"), _b(602, 2960031, "Wernerstraße")])
    planung.stammkraft_setzen(2748963, "vale")

    await _login(user)
    await user.should_see("2 Reinigungen noch niemandem zugewiesen")
    user.find("Offene zuweisen").click()
    await user.should_see("Offene Reinigungen zuweisen")
    user.find("Zuweisen").click()
    await user.should_see("zugewiesen ✓")

    # Die Stammkraft hat ihre Wohnung bekommen, die andere ist auch vergeben.
    assert bookings.assignee_of(601) == "vale"
    assert bookings.assignee_of(602)
