"""Headless-UI-Test der NiceGUI-Oberfläche (ohne Browser).

Prüft Login, dass die Seite lädt und „Berechnen" das Ergebnis rendert.
Netzwerk (Smoobu) wird gemockt, Ergebnis aus der Dezember-Fixture.
"""
import json
import os
from datetime import date

import pytest
from nicegui.testing import User

from app import data, steuer, web, archive, auth, timetrack  # noqa: F401

FIXTURE = os.path.join(os.path.dirname(__file__), "fixture_2025-12.json")
STICHTAG = date(2026, 6, 29)


@pytest.fixture
def mock_backend(monkeypatch):
    bookings = json.load(open(FIXTURE, encoding="utf-8"))
    result = steuer.compute(bookings, 2025, 12, today=STICHTAG)
    monkeypatch.setattr(data, "get_apartments", lambda: [
        {"id": 2748963, "name": "Cottaer Straße"},
        {"id": 2960031, "name": "Wernerstraße"},
    ])
    monkeypatch.setattr(data, "compute", lambda *a, **k: result)
    web._APARTMENTS.clear()
    # Login: Test-Admin (Benutzer "test"), kein TOTP
    monkeypatch.setitem(web.USERS, "test", {
        "password_hash": auth.hash_password("test"), "role": "admin",
        "totp_secret": "", "name": "test"})


async def _login(user):
    await user.open("/login")
    user.find("Benutzername").type("test")
    user.find("Passwort").type("test")
    user.find("Anmelden").click()
    await user.open("/")


async def test_login_schuetzt_startseite(user: User, mock_backend):
    await user.open("/")               # unangemeldet -> Login
    await user.should_see("Anmelden")


async def test_seite_laedt(user: User, mock_backend):
    await _login(user)
    await user.should_see("Beherbergungssteuer")   # Feature-Titel
    await user.should_see("Berechnen")


async def test_berechnen_zeigt_ergebnis(user: User, mock_backend):
    await _login(user)
    user.find("Berechnen").click()
    await user.should_see("341,90")          # Steuer-KPI
    await user.should_see("Buchungen")        # Tabellen-Überschrift
    await user.should_see("Erzeugen & ablegen")   # Festschreiben-Button
    await user.should_see("per E-Mail senden")    # E-Mail-Button


async def test_einstellungen_dialog(user: User, mock_backend):
    await _login(user)
    user.find("Einstellungen").click()
    await user.should_see("Ablage-Ordner")   # Ordner-Ablage
    await user.should_see("Betreiberdaten")


async def test_benutzerverwaltung_admin(user: User, mock_backend):
    await _login(user)
    user.find("Benutzer").click()
    await user.should_see("Benutzer verwalten")
    await user.should_see("Neuen Benutzer anlegen")


async def test_mein_konto(user: User, mock_backend):
    await _login(user)
    user.find("Mein Konto").click()
    await user.should_see("Angemeldet als test")
    await user.should_see("2FA aktivieren")


def test_geofence(monkeypatch):
    monkeypatch.setitem(web.CFG, "arbeitsorte",
                        [{"name": "Objekt A", "lat": 51.05, "lon": 13.74, "radius_m": 150}])
    ort, dist = web._match_geofence({"lat": 51.0503, "lon": 13.7403})
    assert ort == "Objekt A" and dist < 150
    ort2, dist2 = web._match_geofence({"lat": 51.20, "lon": 13.90})   # weit weg
    assert ort2 is None and dist2 and dist2 > 1000
    assert web._match_geofence({"error": "denied"}) == (None, None)


async def test_putzkraft_sieht_nur_zeiterfassung(user: User, mock_backend,
                                                  tmp_path, monkeypatch):
    monkeypatch.setattr(timetrack, "LOG", str(tmp_path / "worklog.json"))
    monkeypatch.setitem(web.USERS, "putzi", {
        "password_hash": auth.hash_password("putzi"), "role": "putzkraft",
        "totp_secret": "", "name": "putzi"})
    await user.open("/login")
    user.find("Benutzername").type("putzi")
    user.find("Passwort").type("putzi")
    user.find("Anmelden").click()
    await user.open("/")
    await user.should_see("Zeiterfassung")
    await user.should_see("Check-in")
    await user.should_not_see("Berechnen")   # kein Zugriff auf Beherbergungssteuer


async def test_archiv_dialog(user: User, mock_backend, tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "ARCHIVE_DIR", str(tmp_path))
    monkeypatch.setattr(archive, "LEDGER_PATH", str(tmp_path / "ledger.jsonl"))
    await _login(user)
    user.find("Archiv").click()
    await user.should_see("revisionssicher abgelegte")
