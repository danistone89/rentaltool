"""Headless-UI-Test der NiceGUI-Oberfläche (ohne Browser).

Prüft Login, dass die Seite lädt und „Berechnen" das Ergebnis rendert.
Netzwerk (Smoobu) wird gemockt, Ergebnis aus der Dezember-Fixture.
"""
import json
import os
from datetime import date

import pytest
from nicegui.testing import User

from app import data, steuer, web, archive, auth, timetrack, bookings, mailer  # noqa: F401

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
    monkeypatch.setattr(mailer, "send_notify", lambda *a, **k: None)  # keine echten Mails
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


async def test_belege_bereich(user: User, mock_backend, tmp_path, monkeypatch):
    from app import receipts, housekeeping as hk
    monkeypatch.setattr(receipts, "RECEIPTS", str(tmp_path / "receipts.json"))
    monkeypatch.setattr(hk, "MEDIA_DIR", str(tmp_path / "media"))
    await _login(user)
    user.find(marker="nav-belege").click()
    await user.should_see("Neuen Beleg hinzufügen")
    await user.should_see("Beleg scannen")


async def test_uebersicht_admin(user: User, mock_backend, tmp_path, monkeypatch):
    from app import housekeeping as hk, bookings
    for attr in ("CHECKLISTS", "INVENTORY", "CLEANINGS", "DAMAGES", "RESTOCK"):
        monkeypatch.setattr(hk, attr, str(tmp_path / (attr.lower() + ".json")))
    monkeypatch.setattr(hk, "MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setattr(bookings, "ASSIGN", str(tmp_path / "a.json"))
    await _login(user)
    user.find(marker="nav-uebersicht").click()
    await user.should_see("Zusammenfassung")  # neue Auswertung
    await user.should_see("Durchgänge")       # weitere Admin-Tabs
    await user.should_see("Schäden")
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


async def test_putzkraft_bereiche(user: User, mock_backend, tmp_path, monkeypatch):
    monkeypatch.setattr(timetrack, "LOG", str(tmp_path / "worklog.json"))
    monkeypatch.setitem(web.USERS, "putzi", {
        "password_hash": auth.hash_password("putzi"), "role": "putzkraft",
        "totp_secret": "", "name": "putzi"})
    await user.open("/login")
    user.find("Benutzername").type("putzi")
    user.find("Passwort").type("putzi")
    user.find("Anmelden").click()
    await user.open("/")
    await user.should_see("Buchungen")       # Standard-Bereich der Putzkraft
    await user.should_see("Zeiterfassung")   # erlaubter Bereich (Menü)
    await user.should_not_see("Berechnen")   # kein Zugriff auf Beherbergungssteuer
    await user.should_not_see("Zusammenfassung")   # Admin-Auswertung nicht für Putzkraft


async def test_manager_bereiche(user: User, mock_backend, tmp_path, monkeypatch):
    from app import housekeeping as hk
    monkeypatch.setattr(timetrack, "LOG", str(tmp_path / "worklog.json"))
    for attr in ("CHECKLISTS", "INVENTORY", "CLEANINGS", "DAMAGES", "RESTOCK"):
        monkeypatch.setattr(hk, attr, str(tmp_path / (attr.lower() + ".json")))
    monkeypatch.setattr(hk, "MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setattr(bookings, "ASSIGN", str(tmp_path / "a.json"))
    monkeypatch.setitem(web.USERS, "mgr", {
        "password_hash": auth.hash_password("mgr"), "role": "manager",
        "totp_secret": "", "name": "mgr"})
    await user.open("/login")
    user.find("Benutzername").type("mgr")
    user.find("Passwort").type("mgr")
    user.find("Anmelden").click()
    await user.open("/")
    user.find(marker="nav-uebersicht").click()
    await user.should_see("Zusammenfassung")   # Manager sieht Auswertung
    await user.should_see("Konfiguration")     # inkl. Checklisten-Konfiguration
    await user.should_not_see("Berechnen")     # keine Beherbergungssteuer
    await user.should_not_see("Benutzer")      # keine Benutzerverwaltung im Kopf


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
    await user.should_see("Arbeitszeit starten")   # primäre Aktion
    # Detail-Dialog muss sich beim Klick wirklich ÖFFNEN (value=True),
    # nicht nur im Elementbaum existieren.
    from nicegui import ui as _ui
    user.find(marker="booking-details").click()
    await user.should_see("Tauschen / Zuweisen")   # Aktionen-Liste im Dialog
    await user.should_see("Nachrichten")           # Gäste-Nachrichten (Admin/Manager)
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


async def test_satzfelder_ohne_wochenendsatz(user: User, mock_backend):
    """Werktagsfeld und Schalter rendern; das Wochenend-Feld bleibt verborgen,
    solange der Schalter aus ist."""
    await _login(user)
    user.find("Benutzer").click()
    await user.should_see("Stundensatz Werktag")
    await user.should_see("Abweichender Satz an Wochenende/Feiertagen")
    await user.should_not_see("Stundensatz Wochenende/Feiertag")


async def test_satzfelder_mit_aktiviertem_wochenendsatz(user: User, mock_backend, monkeypatch):
    """Ist der Satz beim Mitarbeiter aktiviert, ist das zweite Feld sichtbar."""
    monkeypatch.setitem(web.USERS["test"], "wochenendsatz_aktiv", True)
    await _login(user)
    user.find("Benutzer").click()
    await user.should_see("Stundensatz Werktag")
    await user.should_see("Stundensatz Wochenende/Feiertag")


async def test_vorgabesaetze_in_einstellungen(user: User, mock_backend):
    await _login(user)
    user.find("Einstellungen").click()
    user.find("Steuerberater").click()
    await user.should_see("Stundensätze (Vorgabe)")
    await user.should_see("Wochenende/Feiertag")


async def test_zeiten_kennzeichnen_wochenende_und_feiertag(
        user: User, mock_backend, tmp_path, monkeypatch):
    from datetime import datetime
    monkeypatch.setattr(timetrack, "LOG", str(tmp_path / "worklog.json"))
    timetrack.add_manual("test", datetime(2026, 5, 1, 8), datetime(2026, 5, 1, 12))   # Feiertag
    timetrack.add_manual("test", datetime(2026, 7, 5, 9), datetime(2026, 7, 5, 12))   # Sonntag
    timetrack.add_manual("test", datetime(2026, 7, 1, 9), datetime(2026, 7, 1, 12))   # Mittwoch
    await _login(user)
    user.find(marker="nav-zeiterfassung").click()
    await user.should_see("Tag der Arbeit")
    await user.should_see("Sonntag")


async def test_auswertung_zeigt_split_und_betraege(
        user: User, mock_backend, tmp_path, monkeypatch):
    from datetime import datetime
    monkeypatch.setattr(timetrack, "LOG", str(tmp_path / "worklog.json"))
    monkeypatch.setitem(web.USERS["test"], "stundensatz_werktag", 15)
    monkeypatch.setitem(web.USERS["test"], "stundensatz_wochenende", 20)
    monkeypatch.setitem(web.USERS["test"], "wochenendsatz_aktiv", True)
    timetrack.add_manual("test", datetime(2026, 7, 1, 8), datetime(2026, 7, 1, 12))   # Mi 4h
    timetrack.add_manual("test", datetime(2026, 7, 5, 9), datetime(2026, 7, 5, 12))   # So 3h
    await _login(user)
    user.find(marker="nav-zeiterfassung").click()
    user.find("Auswertung").click()
    await user.should_see("Werktags 4 · Wochenende/Feiertag 3 Std")
    await user.should_see("120,00 €")     # 4h*15 + 3h*20


async def test_oberflaeche_auf_englisch(user: User, mock_backend, monkeypatch, tmp_path):
    """Mit Profilsprache 'en' erscheinen die Mitarbeiterbereiche englisch."""
    from app import housekeeping as hk, bookings as bk
    monkeypatch.setattr(timetrack, "LOG", str(tmp_path / "worklog.json"))
    monkeypatch.setattr(bk, "ASSIGN", str(tmp_path / "a.json"))
    for attr in ("CHECKLISTS", "INVENTORY", "CLEANINGS", "DAMAGES", "RESTOCK"):
        monkeypatch.setattr(hk, attr, str(tmp_path / (attr.lower() + ".json")))
    monkeypatch.setitem(web.USERS["test"], "lang", "en")
    await _login(user)
    await user.should_see("Sections")          # Navigations-Überschrift
    await user.should_see("Bookings")          # Bereichsname
    await user.should_see("My account")
    await user.should_see("Cleanings")         # Tab in Buchungen
    await user.should_not_see("Reinigungen")


async def test_oberflaeche_bleibt_deutsch_ohne_profilsprache(user: User, mock_backend):
    await _login(user)
    await user.should_see("Bereiche")
    await user.should_see("Buchungen")
    await user.should_not_see("Sections")


async def test_sprachwahl_im_konto_dialog(user: User, mock_backend):
    await _login(user)
    user.find("Mein Konto").click()
    await user.should_see("Sprache")
    await user.should_see("Angemeldet als test")


async def test_zeiterfassung_englisch(user: User, mock_backend, monkeypatch, tmp_path):
    from datetime import datetime
    monkeypatch.setattr(timetrack, "LOG", str(tmp_path / "worklog.json"))
    monkeypatch.setitem(web.USERS["test"], "lang", "en")
    timetrack.add_manual("test", datetime(2026, 5, 1, 8), datetime(2026, 5, 1, 12))  # Feiertag
    await _login(user)
    user.find(marker="nav-zeiterfassung").click()
    await user.should_see("Time tracking")
    await user.should_see("Labour Day")        # Feiertagsname uebersetzt


def _mock_booking(monkeypatch):
    """Eine reale Buchung mit Folgebuchung in den Buchungs-Hub schieben."""
    from app import data as _data
    raw = [{"id": 111, "apartment": {"id": 2748963, "name": "Cottaer Straße"},
            "arrival": "2026-07-20", "departure": "2026-07-25",
            "check-in": "15:00", "check-out": "10:00", "adults": 2, "children": 1,
            "guest-name": "Max Mustermann", "type": "reservation",
            "channel": {"name": "Direct"}, "is-blocked-booking": False},
           {"id": 112, "apartment": {"id": 2748963, "name": "Cottaer Straße"},
            "arrival": "2026-07-25", "departure": "2026-07-28",
            "check-in": "15:00", "check-out": "10:00", "adults": 2, "children": 0,
            "guest-name": "Erika Musterfrau", "type": "reservation",
            "channel": {"name": "Airbnb"}, "is-blocked-booking": False}]
    monkeypatch.setattr(_data, "_reservations", lambda *a, **k: raw)


async def test_buchungsaktionen_englisch(user: User, mock_backend, monkeypatch, tmp_path):
    """Die Aktionsliste einer Buchung erscheint vollständig englisch."""
    from app import housekeeping as hk, bookings as bk
    monkeypatch.setattr(timetrack, "LOG", str(tmp_path / "worklog.json"))
    monkeypatch.setattr(bk, "ASSIGN", str(tmp_path / "a.json"))
    for attr in ("CHECKLISTS", "INVENTORY", "CLEANINGS", "DAMAGES", "RESTOCK"):
        monkeypatch.setattr(hk, attr, str(tmp_path / (attr.lower() + ".json")))
    monkeypatch.setattr(hk, "MEDIA_DIR", str(tmp_path / "media"))
    _mock_booking(monkeypatch)
    monkeypatch.setitem(web.USERS["test"], "lang", "en")
    await _login(user)
    user.find(marker="booking-details").click()
    await user.should_see("Actions")
    await user.should_see("I'll take this job")
    await user.should_see("Swap / assign")
    await user.should_see("Add time entry")
    await user.should_see("Add note")
    await user.should_see("Supplies / laundry")
    await user.should_see("Report damage")
    await user.should_see("Checklist & photos")
    await user.should_not_see("Zeit nachtragen")


async def test_buchungsaktionen_deutsch(user: User, mock_backend, monkeypatch, tmp_path):
    from app import housekeeping as hk, bookings as bk
    monkeypatch.setattr(timetrack, "LOG", str(tmp_path / "worklog.json"))
    monkeypatch.setattr(bk, "ASSIGN", str(tmp_path / "a.json"))
    for attr in ("CHECKLISTS", "INVENTORY", "CLEANINGS", "DAMAGES", "RESTOCK"):
        monkeypatch.setattr(hk, attr, str(tmp_path / (attr.lower() + ".json")))
    monkeypatch.setattr(hk, "MEDIA_DIR", str(tmp_path / "media"))
    _mock_booking(monkeypatch)
    await _login(user)
    user.find(marker="booking-details").click()
    await user.should_see("Aktionen")
    await user.should_see("Zeit nachtragen")
    await user.should_not_see("Add time entry")
