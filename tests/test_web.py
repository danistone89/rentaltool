"""Headless-UI-Test der NiceGUI-Oberfläche (ohne Browser).

Prüft Login, dass die Seite lädt und „Berechnen" das Ergebnis rendert.
Netzwerk (Smoobu) wird gemockt, Ergebnis aus der Dezember-Fixture.
"""
import json
import os
from datetime import date

import pytest
from nicegui.testing import User

from app import data, steuer, web, archive, auth  # noqa: F401

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
    # Login: bekanntes Passwort, kein TOTP
    monkeypatch.setitem(web.AUTH, "password_hash", auth.hash_password("test"))
    monkeypatch.setitem(web.AUTH, "totp_secret", "")


async def _login(user):
    await user.open("/login")
    user.find("Passwort").type("test")
    user.find("Anmelden").click()
    await user.open("/")


async def test_login_schuetzt_startseite(user: User, mock_backend):
    await user.open("/")               # unangemeldet -> Login
    await user.should_see("Anmelden")


async def test_seite_laedt(user: User, mock_backend):
    await _login(user)
    await user.should_see("DS Apartments & Suites")   # App-Name (Header)
    await user.should_see("Beherbergungssteuer")       # Feature-Titel
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
    await user.should_see("Nextcloud (WebDAV)")   # Spiegel-Feld
    await user.should_see("Betreiberdaten")
    await user.should_see("2FA aktivieren")    # Sicherheits-Sektion


async def test_archiv_dialog(user: User, mock_backend, tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "ARCHIVE_DIR", str(tmp_path))
    monkeypatch.setattr(archive, "LEDGER_PATH", str(tmp_path / "ledger.jsonl"))
    await _login(user)
    user.find("Archiv").click()
    await user.should_see("revisionssicher abgelegte")
