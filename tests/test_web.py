"""Headless-UI-Test der NiceGUI-Oberfläche (ohne Browser).

Prüft Login, dass die Seite lädt und „Berechnen" das Ergebnis rendert.
Netzwerk (Smoobu) wird gemockt, Ergebnis aus der Dezember-Fixture.
"""
import json
import os
from datetime import date

import pytest
from nicegui.testing import User

from app import data, steuer, web, archive, auth, timetrack, bookings  # noqa: F401

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
    monkeypatch.setattr(data, "_reservations", lambda *a, **k: [])   # Buchungen-Hub
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
    await user.should_see("Buchungen")             # Standard-Landeseite = Hub
    user.find(marker="nav-beherbergungssteuer").click()
    await user.should_see("Berechnen")


async def test_berechnen_zeigt_ergebnis(user: User, mock_backend):
    await _login(user)
    user.find(marker="nav-beherbergungssteuer").click()
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
    await user.should_see("Standorte")        # GPS-Standorte-Tab


async def test_reinigung_admin(user: User, mock_backend, tmp_path, monkeypatch):
    from app import housekeeping as hk
    for attr in ("CHECKLISTS", "INVENTORY", "CLEANINGS", "DAMAGES", "RESTOCK"):
        monkeypatch.setattr(hk, attr, str(tmp_path / (attr.lower() + ".json")))
    monkeypatch.setattr(hk, "MEDIA_DIR", str(tmp_path / "media"))
    await _login(user)
    user.find(marker="nav-reinigung").click()
    await user.should_see("Durchgänge")       # Admin-Tabs
    await user.should_see("Schäden")
    await user.should_see("Einkaufsliste")
    await user.should_see("Konfiguration")


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


async def test_putzkraft_sieht_nur_reinigung_und_zeit(user: User, mock_backend,
                                                      tmp_path, monkeypatch):
    from app import housekeeping as hk
    monkeypatch.setattr(timetrack, "LOG", str(tmp_path / "worklog.json"))
    for attr in ("CHECKLISTS", "INVENTORY", "CLEANINGS", "DAMAGES", "RESTOCK"):
        monkeypatch.setattr(hk, attr, str(tmp_path / (attr.lower() + ".json")))
    monkeypatch.setattr(hk, "MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setitem(web.USERS, "putzi", {
        "password_hash": auth.hash_password("putzi"), "role": "putzkraft",
        "totp_secret": "", "name": "putzi"})
    await user.open("/login")
    user.find("Benutzername").type("putzi")
    user.find("Passwort").type("putzi")
    user.find("Anmelden").click()
    await user.open("/")
    await user.should_see("Reinigung")       # Standard-Bereich der Putzkraft
    await user.should_see("Zeiterfassung")   # zweiter erlaubter Bereich (Menü)
    await user.should_not_see("Berechnen")   # kein Zugriff auf Beherbergungssteuer


async def test_reinigung_putzkraft_picker(user: User, mock_backend, tmp_path, monkeypatch):
    """Putzkraft-Startansicht (Apartment-Auswahl) rendert ohne Fehler."""
    from app import housekeeping as hk
    for attr in ("CHECKLISTS", "INVENTORY", "CLEANINGS", "DAMAGES", "RESTOCK"):
        monkeypatch.setattr(hk, attr, str(tmp_path / (attr.lower() + ".json")))
    monkeypatch.setattr(hk, "MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setitem(web.USERS, "putzi", {
        "password_hash": auth.hash_password("putzi"), "role": "putzkraft",
        "totp_secret": "", "name": "putzi"})
    await user.open("/login")
    user.find("Benutzername").type("putzi")
    user.find("Passwort").type("putzi")
    user.find("Anmelden").click()
    await user.open("/")
    user.find(marker="nav-reinigung").click()
    await user.should_see("Apartment wählen:")
    await user.should_see("Reinigung starten")


async def test_buchungen_hub(user: User, mock_backend, tmp_path, monkeypatch):
    """Buchungs-Hub rendert eine Buchung mit Zuweisungs-Aktion."""
    monkeypatch.setattr(bookings, "ASSIGN", str(tmp_path / "assignments.json"))
    fake = [{"id": 999, "type": "reservation", "is-blocked-booking": False,
             "apartment": {"id": 2748963, "name": "Cottaer Straße"},
             "arrival": "2026-07-01", "departure": date.today().isoformat(),
             "check-in": "15:00", "check-out": "10:00", "adults": 2, "children": 0,
             "guest-name": "Max Muster", "email": "x@y.de", "phone": "",
             "channel": {"name": "Booking.com"}, "notice": ""}]
    monkeypatch.setattr(data, "_reservations", lambda *a, **k: fake)
    await _login(user)            # Standard-Landeseite = Buchungen-Hub
    await user.should_see("Cottaer Straße")
    await user.should_see("Ich übernehme")
    # Detail-Dialog muss sich beim Klick wirklich ÖFFNEN (value=True),
    # nicht nur im Elementbaum existieren.
    from nicegui import ui as _ui
    user.find("Details").click()
    await user.should_see("Zuständig")
    assert any(getattr(d, "value", False) for d in user.find(_ui.dialog).elements), \
        "Buchungs-Detail-Dialog wurde nicht geöffnet (dlg.open() fehlt?)"
    # Kalender-Tab rendert Timeline (Datumsband ab heute vorhanden)
    await user.should_see(f"{date.today().strftime('%d.%m.')} –")


async def test_archiv_dialog(user: User, mock_backend, tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "ARCHIVE_DIR", str(tmp_path))
    monkeypatch.setattr(archive, "LEDGER_PATH", str(tmp_path / "ledger.jsonl"))
    await _login(user)
    user.find(marker="nav-beherbergungssteuer").click()
    user.find("Archiv").click()
    await user.should_see("revisionssicher abgelegte")
