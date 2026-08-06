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
    user.find(marker="login-user").type("test")
    user.find(marker="login-pw").type("test")
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


async def test_summen_tabelle_zeigt_die_kette(user: User, mock_backend):
    """Nach 'Berechnen' muss ablesbar sein, WELCHE Summe die Bemessungsgrundlage
    ist – die Summe der Rechnungsbeträge ist es gerade NICHT, aus ihr muss erst
    die vom Gast mitbezahlte Beherbergungssteuer heraus."""
    await _login(user)
    user.find(marker="nav-beherbergungssteuer").click()
    user.find("Berechnen").click()
    await user.should_see(marker="summen")
    # Dez 2025, gegen das eingereichte Formular validiert:
    await user.should_see("5.991,89")   # Summe Rechnungsbeträge (was die Gäste zahlten)
    await user.should_see("293,61")     # darin enthaltene Beherbergungssteuer
    await user.should_see("5.698,28")   # = Bemessungsgrundlage / steuerpfl. Umsatz
    await user.should_see("341,90")     # x 6 % = Steuer
    # Die Beschriftungen, die die Verwechslung verhindern:
    await user.should_see("Summe Rechnungsbeträge (was die Gäste insgesamt gezahlt haben)")
    await user.should_see("− darin enthaltene Beherbergungssteuer (Durchlaufposten)")
    await user.should_see("= steuerpflichtige Umsätze")


async def test_einstellungen_dialog(user: User, mock_backend):
    await _login(user)
    user.find(marker="nav-einstellungen").click()
    await user.should_see("Ablage-Ordner")   # Ordner-Ablage
    await user.should_see("Betreiberdaten")
    await user.should_see("Standorte")        # GPS-Standorte-Tab


async def test_belege_bereich(user: User, mock_backend, tmp_path, monkeypatch):
    from app import receipts, housekeeping as hk
    monkeypatch.setattr(hk, "MEDIA_DIR", str(tmp_path / "media"))
    await _login(user)
    user.find(marker="nav-belege").click()
    await user.should_see("Neuen Beleg hinzufügen")
    await user.should_see("Beleg scannen")


async def test_uebersicht_admin(user: User, mock_backend, tmp_path, monkeypatch):
    from app import housekeeping as hk, bookings
    monkeypatch.setattr(hk, "MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setitem(web.CFG, "checklisten_aktiv", True)
    await _login(user)
    user.find(marker="nav-uebersicht").click()
    await user.should_see("Zusammenfassung")  # neue Auswertung
    await user.should_see("Durchgänge")       # nur bei aktiven Checklisten
    await user.should_see("Schäden")
    await user.should_see("Konfiguration")


async def test_benutzerverwaltung_admin(user: User, mock_backend):
    await _login(user)
    user.find(marker="nav-benutzer").click()
    await user.should_see("Benutzer verwalten")
    await user.should_see("Neuen Benutzer einladen")


async def test_mein_konto(user: User, mock_backend):
    await _login(user)
    user.find(marker="nav-konto").click()
    await user.should_see("Angemeldet als test")
    await user.should_see("2FA aktivieren")


async def test_putzkraft_bereiche(user: User, mock_backend, tmp_path, monkeypatch):
    monkeypatch.setitem(web.USERS, "putzi", {
        "password_hash": auth.hash_password("putzi"), "role": "putzkraft",
        "totp_secret": "", "name": "putzi"})
    await user.open("/login")
    user.find(marker="login-user").type("putzi")
    user.find(marker="login-pw").type("putzi")
    user.find("Anmelden").click()
    await user.open("/")
    await user.should_see("Buchungen")       # Standard-Bereich der Putzkraft
    await user.should_see("Zeiterfassung")   # erlaubter Bereich (Menü)
    await user.should_not_see("Berechnen")   # kein Zugriff auf Beherbergungssteuer
    await user.should_not_see("Zusammenfassung")   # Admin-Auswertung nicht für Putzkraft


async def test_manager_bereiche(user: User, mock_backend, tmp_path, monkeypatch):
    from app import housekeeping as hk
    monkeypatch.setattr(hk, "MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setitem(web.USERS, "mgr", {
        "password_hash": auth.hash_password("mgr"), "role": "manager",
        "totp_secret": "", "name": "mgr"})
    await user.open("/login")
    user.find(marker="login-user").type("mgr")
    user.find(marker="login-pw").type("mgr")
    user.find("Anmelden").click()
    await user.open("/")
    user.find(marker="nav-uebersicht").click()
    await user.should_see("Zusammenfassung")   # Manager sieht Auswertung
    await user.should_see("Konfiguration")     # inkl. Checklisten-Konfiguration
    await user.should_not_see("Berechnen")     # keine Beherbergungssteuer
    await user.should_not_see("Benutzer")      # keine Benutzerverwaltung im Kopf


async def test_buchungen_hub(user: User, mock_backend, tmp_path, monkeypatch):
    """Buchungs-Hub rendert eine Buchung mit Zuweisungs-Aktion."""
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
    user.find(marker="steuer-archiv").click()
    await user.should_see("revisionssicher abgelegte")


async def test_satzfelder_ohne_wochenendsatz(user: User, mock_backend):
    """Werktagsfeld und Schalter rendern; das Wochenend-Feld bleibt verborgen,
    solange der Schalter aus ist."""
    await _login(user)
    user.find(marker="nav-benutzer").click()
    await user.should_see("Stundensatz Werktag")
    await user.should_see("Abweichender Satz an Wochenende/Feiertagen")
    await user.should_not_see("Stundensatz Wochenende/Feiertag")


async def test_satzfelder_mit_aktiviertem_wochenendsatz(user: User, mock_backend, monkeypatch):
    """Ist der Satz beim Mitarbeiter aktiviert, ist das zweite Feld sichtbar."""
    monkeypatch.setitem(web.USERS["test"], "wochenendsatz_aktiv", True)
    await _login(user)
    user.find(marker="nav-benutzer").click()
    await user.should_see("Stundensatz Werktag")
    await user.should_see("Stundensatz Wochenende/Feiertag")


async def test_vorgabesaetze_in_einstellungen(user: User, mock_backend):
    await _login(user)
    user.find(marker="nav-einstellungen").click()
    user.find("Steuerberater").click()
    await user.should_see("Stundensätze (Vorgabe)")
    await user.should_see("Wochenende/Feiertag")


async def test_zeiten_kennzeichnen_wochenende_und_feiertag(
        user: User, mock_backend, tmp_path, monkeypatch):
    from datetime import datetime
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
    monkeypatch.setitem(web.USERS["test"], "lang", "en")
    await _login(user)
    await user.should_see("Sections")          # Navigations-Überschrift
    await user.should_see("Bookings")          # Bereichsname
    await user.should_see("My account")
    await user.should_see("All cleanings")     # Tab in Buchungen
    await user.should_see("My cleanings")      # eigener Startbildschirm
    await user.should_not_see("Reinigungen")


async def test_oberflaeche_bleibt_deutsch_ohne_profilsprache(user: User, mock_backend):
    await _login(user)
    await user.should_see("Bereiche")
    await user.should_see("Buchungen")
    await user.should_not_see("Sections")


async def test_sprachwahl_im_konto_dialog(user: User, mock_backend):
    await _login(user)
    user.find(marker="nav-konto").click()
    await user.should_see("Sprache")
    await user.should_see("Angemeldet als test")


async def test_zeiterfassung_englisch(user: User, mock_backend, monkeypatch, tmp_path):
    from datetime import datetime
    monkeypatch.setitem(web.USERS["test"], "lang", "en")
    timetrack.add_manual("test", datetime(2026, 5, 1, 8), datetime(2026, 5, 1, 12))  # Feiertag
    await _login(user)
    user.find(marker="nav-zeiterfassung").click()
    await user.should_see("Time tracking")
    await user.should_see("Labour Day")        # Feiertagsname uebersetzt


def _mock_booking(monkeypatch, abreise_pers=(2, 1), anreise_pers=(2, 0)):
    """Eine reale Buchung mit Folgebuchung in den Buchungs-Hub schieben.

    Die Daten sind relativ zu heute – mit festen Daten fällt die Buchung nach
    ein paar Wochen aus dem Fenster von `_cleaning_jobs` und der Hub ist leer.
    Abreise ist heute, die Folgebuchung reist am selben Tag an (Wechseltag).
    """
    from app import data as _data
    from datetime import timedelta
    heute = date.today()
    raw = [{"id": 111, "apartment": {"id": 2748963, "name": "Cottaer Straße"},
            "arrival": (heute - timedelta(days=5)).isoformat(),
            "departure": heute.isoformat(),
            "check-in": "15:00", "check-out": "10:00",
            "adults": abreise_pers[0], "children": abreise_pers[1],
            "guest-name": "Max Mustermann", "type": "reservation",
            "channel": {"name": "Direct"}, "is-blocked-booking": False},
           {"id": 112, "apartment": {"id": 2748963, "name": "Cottaer Straße"},
            "arrival": heute.isoformat(),
            "departure": (heute + timedelta(days=3)).isoformat(),
            "check-in": "15:00", "check-out": "10:00",
            "adults": anreise_pers[0], "children": anreise_pers[1],
            "guest-name": "Erika Musterfrau", "type": "reservation",
            "channel": {"name": "Airbnb"}, "is-blocked-booking": False}]
    monkeypatch.setattr(_data, "_reservations", lambda *a, **k: raw)


async def test_buchungsaktionen_englisch(user: User, mock_backend, monkeypatch, tmp_path):
    """Die Aktionsliste einer Buchung erscheint vollständig englisch."""
    from app import housekeeping as hk, bookings as bk
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
    await user.should_not_see("Zeit nachtragen")


async def test_buchungsaktionen_deutsch(user: User, mock_backend, monkeypatch, tmp_path):
    from app import housekeeping as hk, bookings as bk
    monkeypatch.setattr(hk, "MEDIA_DIR", str(tmp_path / "media"))
    _mock_booking(monkeypatch)
    await _login(user)
    user.find(marker="booking-details").click()
    await user.should_see("Aktionen")
    await user.should_see("Zeit nachtragen")
    await user.should_not_see("Add time entry")


async def test_abreise_und_anreise_getrennt(user: User, mock_backend, monkeypatch, tmp_path):
    """Die grosse Personenzahl in der Reinigungskarte ist IMMER die der Anreise.

    Es reisen 3 Erwachsene ab, es kommen 2 – wer hier die Abreise-Zahl liest,
    deckt für einen zu viel ein. Darum steht die Abreise in einem eigenen Tab
    und nur die Anreise-Zahl gross im 'Vorbereiten'-Block.
    """
    from app import housekeeping as hk, bookings as bk
    monkeypatch.setattr(hk, "MEDIA_DIR", str(tmp_path / "media"))
    _mock_booking(monkeypatch, abreise_pers=(3, 0), anreise_pers=(2, 0))
    await _login(user)
    await user.should_see("Vorbereiten")
    await user.should_see("Abreise")
    counts = [e.text for e in user.find(marker="prep-count").elements]
    assert counts == ["2"], f"grosse Zahl muss die Anreise sein, war {counts}"
    # Beide Blöcke existieren, aber getrennt – die Abreise-Angaben stehen im
    # eigenen Tab und sind ausdrücklich als "nicht zum Vorbereiten" markiert.
    assert user.find(marker="depart-block").elements
    await user.should_see("Nur zur Info – nicht die Zahl für die Vorbereitung.")


async def test_scanner_dialog_zeigt_neue_bedienung(user: User, mock_backend, tmp_path, monkeypatch):
    """Der Dialog selbst (Python-Seite). Das Scanner-JS laeuft im Headless-
    Harness nicht, daher wird run_javascript stillgelegt."""
    from app import receipts, housekeeping as hk
    monkeypatch.setattr(hk, "MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setattr(web.ui, "run_javascript", lambda *a, **k: None)
    await _login(user)
    user.find(marker="nav-belege").click()
    await user.should_see(marker="scan-open")
    user.find(marker="scan-open").click()
    await user.should_see(marker="scan-dialog")
    await user.should_see("Foto aufnehmen")              # Schritt 1
    await user.should_see("Zuschneiden & speichern")     # Schritt 2
    await user.should_see("Neu aufnehmen")
    await user.should_see("Ecken zurücksetzen")


async def test_standorterfassung_schalter_in_einstellungen(user: User, mock_backend):
    await _login(user)
    user.find(marker="nav-einstellungen").click()
    user.find("Standorte").click()
    await user.should_see("Standort bei der Zeiterfassung erfassen")
    await user.should_see("Wirkt erst, wenn die Standorterfassung oben eingeschaltet ist.")


# ----------------------------------------------------------------- Einladung
@pytest.fixture
def eingeladen(monkeypatch):
    """Benutzer 'anna' mit offener Einladung; Config wird nicht auf Platte geschrieben."""
    monkeypatch.setattr(data, "save_config", lambda: None)
    token, rec = auth.new_invite("einladung")
    monkeypatch.setitem(web.USERS, "anna", {
        "password_hash": "", "role": "putzkraft", "totp_secret": "",
        "name": "Anna", "email": "anna@example.com", "lang": "de", "invite": rec})
    return token


async def test_invite_ohne_token_zeigt_hinweis(user: User, mock_backend):
    await user.open("/invite")
    await user.should_see("Link ungültig oder abgelaufen.")
    await user.should_see("Zur Anmeldung")


async def test_invite_setzt_passwort_und_meldet_an(user: User, mock_backend, eingeladen,
                                                   tmp_path, monkeypatch):
    await user.open(f"/invite?token={eingeladen}")
    await user.should_see("Zugang einrichten")
    await user.should_see("Konto: anna")
    user.find(marker="invite-pw1").type("geheim123")
    user.find(marker="invite-pw2").type("geheim123")
    user.find(marker="invite-save").click()
    await user.should_see("Buchungen")            # direkt angemeldet
    assert auth.verify_password("geheim123", web.USERS["anna"]["password_hash"])
    assert "invite" not in web.USERS["anna"]      # Link verbraucht


async def test_invite_link_nur_einmal(user: User, mock_backend, eingeladen):
    web.USERS["anna"].pop("invite")               # bereits eingelöst
    await user.open(f"/invite?token={eingeladen}")
    await user.should_see("Link ungültig oder abgelaufen.")


async def test_invite_abgelaufen(user: User, mock_backend, monkeypatch):
    monkeypatch.setattr(data, "save_config", lambda: None)
    token, rec = auth.new_invite(ttl_h=-1)
    monkeypatch.setitem(web.USERS, "alt", {
        "password_hash": "", "role": "putzkraft", "totp_secret": "", "invite": rec})
    await user.open(f"/invite?token={token}")
    await user.should_see("Link ungültig oder abgelaufen.")


async def test_login_eines_eingeladenen_verweist_auf_die_mail(user: User, mock_backend,
                                                              eingeladen):
    await user.open("/login")
    user.find(marker="login-user").type("anna")
    user.find(marker="login-pw").type("irgendwas")
    user.find("Anmelden").click()
    await user.should_see("Einladungs-E-Mail")


async def test_einladen_verschickt_mail(user: User, mock_backend, monkeypatch):
    """Anlegen legt den Benutzer ohne Passwort an und schickt den Link."""
    monkeypatch.setattr(data, "save_config", lambda: None)
    gesendet = []
    monkeypatch.setattr(mailer, "send_notify",
                        lambda cfg, to, subj, body: gesendet.append((to, subj, body)))
    await _login(user)
    user.find(marker="nav-benutzer").click()
    await user.should_see("Neuen Benutzer einladen")
    user.find(marker="new-user").type("bea")
    user.find(marker="new-user-mail").type("bea@example.com")
    user.find(marker="new-user-invite").click()
    await user.should_see("Einladung an bea@example.com gesendet")
    try:
        assert web.USERS["bea"]["password_hash"] == ""
        assert auth.invite_state(web.USERS["bea"]) == "offen"
        to, subj, body = gesendet[-1]
        assert to == "bea@example.com"
        assert "/invite?token=" in body
        assert "bea" in body
    finally:
        web.USERS.pop("bea", None)


# --------------------------------------------------- Passwort vergessen
@pytest.fixture
def reset_bereit(monkeypatch):
    """Konto mit E-Mail + gesetztem Passwort; Mailversand wird mitgeschrieben."""
    monkeypatch.setattr(data, "save_config", lambda: None)
    monkeypatch.setitem(web.USERS, "carl", {
        "password_hash": auth.hash_password("altes-pw"), "role": "putzkraft",
        "totp_secret": "", "name": "Carl", "email": "carl@example.com", "lang": "de"})
    web._RESET_THROTTLE.pop("carl", None)
    gesendet = []
    monkeypatch.setattr(mailer, "send_notify",
                        lambda cfg, to, subj, body: gesendet.append((to, subj, body)))
    return gesendet


async def _forgot(user, kennung):
    await user.open("/login")
    user.find(marker="forgot-open").click()
    await user.should_see("Passwort zurücksetzen")
    user.find(marker="forgot-input").type(kennung)
    user.find(marker="forgot-send").click()


async def test_passwort_vergessen_schickt_link(user: User, mock_backend, reset_bereit):
    await _forgot(user, "carl")
    await user.should_see("ist gleich eine E-Mail mit einem Link unterwegs")
    to, subj, body = reset_bereit[-1]
    assert to == "carl@example.com"
    assert "/invite?token=" in body
    assert web.auth.invite_state(web.USERS["carl"]) == "offen"
    # Altes Passwort gilt weiter, bis der Link benutzt wird
    assert auth.verify_password("altes-pw", web.USERS["carl"]["password_hash"])


async def test_passwort_vergessen_auch_per_email(user: User, mock_backend, reset_bereit):
    await _forgot(user, "CARL@example.com")     # Groß/klein egal
    assert reset_bereit and reset_bereit[-1][0] == "carl@example.com"


async def test_passwort_vergessen_verraet_keine_konten(user: User, mock_backend,
                                                       reset_bereit):
    await _forgot(user, "gibtesnicht")
    await user.should_see("ist gleich eine E-Mail mit einem Link unterwegs")
    assert reset_bereit == []      # keine Mail, aber dieselbe Meldung


async def test_passwort_vergessen_bremst_wiederholung(user: User, mock_backend,
                                                      reset_bereit):
    await _forgot(user, "carl")
    await _forgot(user, "carl")
    assert len(reset_bereit) == 1   # zweite Anfrage innerhalb der Sperrzeit: keine Mail


async def _login_as(user, name, rolle):
    from app import auth as _auth
    await user.open("/login")
    user.find(marker="login-user").type(name)
    user.find(marker="login-pw").type(name)
    user.find("Anmelden").click()
    await user.open("/")


async def test_putzkraft_sieht_eigene_kennzahlen(user: User, mock_backend, tmp_path, monkeypatch):
    """Die Putzkraft bekommt in der Zeiterfassung eine Übersicht ihrer Stunden."""
    from datetime import datetime
    monkeypatch.setitem(web.USERS, "putzi", {
        "password_hash": auth.hash_password("putzi"), "role": "putzkraft",
        "totp_secret": "", "name": "putzi"})
    heute = date.today()
    timetrack.add_manual("putzi", datetime(heute.year, heute.month, heute.day, 9),
                         datetime(heute.year, heute.month, heute.day, 11),
                         apartment="Cottaer Straße")
    await _login_as(user, "putzi", "putzkraft")
    user.find(marker="nav-zeiterfassung").click()
    await user.should_see("Meine Übersicht")
    await user.should_see("Stunden dieser Monat")
    await user.should_see("Abrechnungsstand")
    await user.should_see("noch offen")


async def test_abgerechnete_zeit_ist_fuer_putzkraft_gesperrt(user: User, mock_backend,
                                                             tmp_path, monkeypatch):
    """Ist eine Zeit ans Steuerbüro gemeldet, darf die Putzkraft sie nicht mehr
    bearbeiten oder löschen – sonst weicht der Bestand von der Meldung ab."""
    from datetime import datetime
    from nicegui import ui as _ui
    monkeypatch.setitem(web.USERS, "putzi", {
        "password_hash": auth.hash_password("putzi"), "role": "putzkraft",
        "totp_secret": "", "name": "putzi"})
    heute = date.today()
    e = timetrack.add_manual("putzi", datetime(heute.year, heute.month, heute.day, 9),
                             datetime(heute.year, heute.month, heute.day, 11))
    timetrack.mark_billed([e["id"]], "admin")

    await _login_as(user, "putzi", "putzkraft")
    user.find(marker="nav-zeiterfassung").click()
    await user.should_see("abgerechnet")
    # kein Lösch-Button mehr in der Liste
    icons = [getattr(b, "props", {}).get("icon") for b in user.find(_ui.button).elements]
    assert "delete" not in icons, f"Löschen trotz Abrechnung möglich: {icons}"


async def test_admin_kann_abrechnen_und_zuruecknehmen(user: User, mock_backend,
                                                      tmp_path, monkeypatch):
    from datetime import datetime
    heute = date.today()
    timetrack.add_manual("test", datetime(heute.year, heute.month, heute.day, 9),
                         datetime(heute.year, heute.month, heute.day, 12))
    await _login(user)
    user.find(marker="nav-zeiterfassung").click()
    await user.should_see("Abrechnungsstatus")
    await user.should_see("Als abgerechnet markieren (1)")
    user.find("Als abgerechnet markieren (1)").click()
    await user.should_see("Als abgerechnet markieren?")
    await user.should_see("Die Mitarbeiter können diese Zeiten danach nicht mehr "
                          "ändern oder löschen.")
    user.find("Markieren").click()
    assert all(timetrack.is_billed(x) for x in timetrack.entries("test"))

    # Der Neuaufbau aus einem Klick-Handler heraus setzt den Harness auf den
    # Standard-Bereich zurueck (dasselbe passiert beim bestehenden Loeschen-Knopf).
    # Der Zustand wird deshalb nach frischem Aufruf des Bereichs geprueft.
    user.find(marker="nav-zeiterfassung").click()
    await user.should_see("Markierung aufheben (1)")
    await user.should_not_see("Als abgerechnet markieren (1)")

    user.find("Markierung aufheben (1)").click()
    await user.should_see("Markierung aufheben?")
    user.find("Aufheben").click()
    assert not any(timetrack.is_billed(x) for x in timetrack.entries("test"))


async def test_tagesgruppe_zeigt_frei_und_vergeben_ohne_aufklappen(
        user: User, mock_backend, tmp_path, monkeypatch):
    """Der Kopf einer Tagesgruppe muss ohne Aufklappen zeigen, wie viele
    Reinigungen des Tages noch frei sind. Genau der kritische Fall: zwei
    Buchungen an einem Tag, davon nur EINE zu vergeben."""
    from datetime import timedelta
    from app import housekeeping as hk, bookings as bk
    monkeypatch.setattr(hk, "MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setitem(web.USERS, "vale", {
        "password_hash": auth.hash_password("vale"), "role": "putzkraft",
        "totp_secret": "", "name": "Valeriya"})

    tag = (date.today() + timedelta(days=4)).isoformat()
    from app import data as _data

    def _b(bid, apt_id, apt_name):
        return {"id": bid, "type": "reservation", "is-blocked-booking": False,
                "apartment": {"id": apt_id, "name": apt_name},
                "arrival": (date.today() + timedelta(days=1)).isoformat(),
                "departure": tag, "check-in": "15:00", "check-out": "10:00",
                "adults": 2, "children": 0, "guest-name": f"Gast {bid}",
                "channel": {"name": "Direct booking"}, "notice": ""}
    monkeypatch.setattr(_data, "_reservations", lambda *a, **k: [
        _b(501, 2748963, "Cottaer Straße"), _b(502, 2960031, "Wernerstraße")])
    bk.set_assignment(501, "vale", "test")          # eine von zweien vergeben

    await _login(user)
    await user.should_see("KOMMENDE TAGE")
    # Kopf der Tagesgruppe – ohne Klick auf die Aufklapp-Fläche
    await user.should_see("2 Reinigungen")
    await user.should_see("1 frei")                 # genau eine ist noch offen
    await user.should_see("Valeriya")               # die andere hat einen Namen
    await user.should_see("1 Reinigung noch niemandem zugewiesen")   # Banner oben


async def test_tagesgruppe_zeigt_je_reinigung_den_mitarbeiter(
        user: User, mock_backend, tmp_path, monkeypatch):
    """Aufgeklappt muss an JEDER Reinigung stehen, wer sie übernimmt – sonst
    sagt der Kopf zwar „2 vergeben", die Zuordnung Buchung → Mitarbeiter fehlt
    aber. Eine dritte, freie Reinigung bleibt als solche erkennbar."""
    from datetime import timedelta
    from nicegui import ui as _ui
    from app import housekeeping as hk, bookings as bk
    monkeypatch.setattr(hk, "MEDIA_DIR", str(tmp_path / "media"))
    for u, n in (("vale", "Valeriya"), ("mira", "Mira")):
        monkeypatch.setitem(web.USERS, u, {
            "password_hash": auth.hash_password(u), "role": "putzkraft",
            "totp_secret": "", "name": n})
    monkeypatch.setattr(web, "_APARTMENTS", {})
    monkeypatch.setattr(data, "get_apartments", lambda: [
        {"id": 2748963, "name": "Cottaer Straße"},
        {"id": 2960031, "name": "Wernerstraße"},
        {"id": 3000001, "name": "Bergstraße"},
    ])

    tag = (date.today() + timedelta(days=4)).isoformat()
    from app import data as _data

    def _b(bid, apt_id, apt_name):
        return {"id": bid, "type": "reservation", "is-blocked-booking": False,
                "apartment": {"id": apt_id, "name": apt_name},
                "arrival": (date.today() + timedelta(days=1)).isoformat(),
                "departure": tag, "check-in": "15:00", "check-out": "10:00",
                "adults": 2, "children": 0, "guest-name": f"Gast {bid}",
                "channel": {"name": "Direct booking"}, "notice": ""}
    monkeypatch.setattr(_data, "_reservations", lambda *a, **k: [
        _b(501, 2748963, "Cottaer Straße"), _b(502, 2960031, "Wernerstraße"),
        _b(503, 3000001, "Bergstraße")])
    bk.set_assignment(501, "vale", "test")
    bk.set_assignment(502, "mira", "test")

    await _login(user)
    await user.should_see("KOMMENDE TAGE")

    # Texte je Kompakt-Karte einsammeln: die Zuordnung zählt, nicht das blosse
    # Vorkommen beider Namen irgendwo auf der Seite.
    def texte(el):
        for kid in el:
            if getattr(kid, "text", None):
                yield kid.text
            yield from texte(kid)

    karten = [" | ".join(texte(c)) for c in user.find(_ui.card).elements]

    def karte(wohnung):
        treffer = [k for k in karten if wohnung in k]
        assert treffer, f"keine Karte für {wohnung}: {karten}"
        return treffer[0]

    assert "Valeriya" in karte("Cottaer Straße"), karte("Cottaer Straße")
    assert "Mira" not in karte("Cottaer Straße"), karte("Cottaer Straße")
    assert "Mira" in karte("Wernerstraße"), karte("Wernerstraße")
    assert "noch frei" in karte("Bergstraße"), karte("Bergstraße")


def _texte_unter(user, marker):
    """Alle Texte unterhalb eines markierten Elements.

    Noetig, weil NiceGUI auch die INAKTIVEN Tab-Panels in den Elementbaum legt –
    should_not_see() koennte "Meine" und "Alle" sonst nicht unterscheiden.
    """
    treffer = []

    def sammle(el):
        for kid in el:
            if getattr(kid, "text", None):
                treffer.append(kid.text)
            sammle(kid)

    for el in user.find(marker=marker).elements:
        sammle(el)
    return " | ".join(treffer)


def _aktion_klicken(user, text):
    """Die Aktions-Buttons im Buchungs-Dialog tragen ihren Text als Kind-Label,
    nicht als Button-Text – ein Klick auf das Label liefe ins Leere."""
    from nicegui import ui as _ui

    def texte(el):
        for kid in el:
            if getattr(kid, "text", None):
                yield kid.text
            yield from texte(kid)

    for b in user.find(_ui.button).elements:
        if text in list(texte(b)):
            for lis in b._event_listeners.values():
                if lis.type == "click":
                    lis.handler(None)
                    return
    raise AssertionError(f"Aktion {text!r} nicht gefunden")


def _hk_mocks(monkeypatch, tmp_path):
    """Fotos in einen Wegwerf-Ordner. Die Daten selbst liegen ohnehin in einer
    eigenen Datenbank je Test (siehe tests/conftest.py)."""
    from app import housekeeping as hk
    monkeypatch.setattr(hk, "MEDIA_DIR", str(tmp_path / "media"))


async def test_bereich_wird_in_der_sitzung_gemerkt(user: User, mock_backend,
                                                   tmp_path, monkeypatch):
    """Aktionen aus einem Buchungs-Dialog sprangen immer nach „Buchungen“ –
    auch wenn man aus der „Übersicht“ kam. Dafür merkt sich die Sitzung den
    aktuellen Bereich."""
    _hk_mocks(monkeypatch, tmp_path)
    await _login(user)
    with user.client:
        assert web._cur_area() == "buchungen"          # Landeseite

    user.find(marker="nav-uebersicht").click()
    await user.should_see("Zusammenfassung")
    with user.client:
        assert web._cur_area() == "uebersicht"

    user.find(marker="nav-zeiterfassung").click()
    await user.should_see("Meine Übersicht")
    with user.client:
        assert web._cur_area() == "zeiterfassung"


async def test_checkliste_kehrt_in_den_ausgangsbereich_zurueck(
        user: User, mock_backend, tmp_path, monkeypatch):
    """Der Sprung in die Checkliste merkt sich den Bereich, aus dem er kam –
    „Checkliste abschließen“ führt dann dorthin zurück, nicht nach Buchungen."""
    _hk_mocks(monkeypatch, tmp_path)
    job = {"id": 701, "apartment_id": 2748963, "apartment_name": "Cottaer Straße",
           "departure": date.today().isoformat(), "checkout_time": "10:00", "next": None}
    await _login(user)

    user.find(marker="nav-uebersicht").click()
    await user.should_see("Zusammenfassung")
    with user.client:
        web._PENDING_REINIGUNG.clear()
        web._open_checkliste(job, lambda key: None)
        assert web._PENDING_REINIGUNG["return"] == "uebersicht"

    user.find(marker="nav-buchungen").click()
    await user.should_see("Reinigungen")
    with user.client:
        web._PENDING_REINIGUNG.clear()
        web._open_checkliste(job, lambda key: None)
        assert web._PENDING_REINIGUNG["return"] == "buchungen"


async def test_checkliste_aus_buchung_stuerzt_nicht_ab(user: User, mock_backend,
                                                       tmp_path, monkeypatch):
    """Checkliste aus einer Buchung heraus oeffnen – der Normalweg der Putzkraft.

    In `render()` gab es `for t in all_tasks:`; damit wurde `t` zur lokalen
    Variable und die Uebersetzungsfunktion `t("Check-out")` weiter oben knallte
    mit UnboundLocalError. Betroffen war genau dieser Weg, weil nur dort die
    Check-out-/Check-in-Zeiten gesetzt sind.
    """
    from app import housekeeping as hk, bookings as bk
    monkeypatch.setattr(hk, "MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setitem(web.CFG, "checklisten_aktiv", True)   # Funktion ist sonst aus
    _mock_booking(monkeypatch)

    await _login(user)
    user.find(marker="booking-details").click()
    await user.should_see("Aktionen")
    # Ruft _open_checkliste + activate("reinigung") -> rendert die Checkliste.
    # Vor dem Fix flog hier UnboundLocalError: local variable 't'.
    _aktion_klicken(user, "Checkliste & Fotos")
    await user.should_see("Räume & Aufgaben")
    await user.should_see("Check-out")
    await user.should_see("Fortschritt")


async def test_neuladen_bleibt_im_bereich(user: User, mock_backend, tmp_path, monkeypatch):
    """Nach einem Neuladen dort weitermachen, wo man war.

    Aktionen wie „Schaden erledigt" laden die Seite neu (ui.navigate.to("/")) –
    vorher landete man dabei jedes Mal wieder in den Buchungen.
    """
    _hk_mocks(monkeypatch, tmp_path)
    await _login(user)
    user.find(marker="nav-zeiterfassung").click()
    await user.should_see("Meine Übersicht")

    await user.open("/")                       # Neuladen
    await user.should_see("Meine Übersicht")   # weiterhin Zeiterfassung
    await user.should_not_see("Reinigungs-Übersicht & Buchungskalender")


async def test_neuladen_faellt_zurueck_wenn_bereich_gesperrt(
        user: User, mock_backend, tmp_path, monkeypatch):
    """Ist der gemerkte Bereich für die Rolle nicht freigegeben, greift der
    erste erlaubte Bereich – sonst sähe eine Putzkraft eine leere Seite."""
    _hk_mocks(monkeypatch, tmp_path)
    monkeypatch.setitem(web.USERS, "putzi2", {
        "password_hash": auth.hash_password("putzi2"), "role": "putzkraft",
        "totp_secret": "", "name": "putzi2"})
    await user.open("/login")
    user.find(marker="login-user").type("putzi2")
    user.find(marker="login-pw").type("putzi2")
    user.find("Anmelden").click()
    await user.open("/")

    with user.client:                       # Bereich setzen, den die Rolle nicht hat
        web.app.storage.user["area"] = "beherbergungssteuer"

    await user.open("/")
    await user.should_not_see("Berechnen")  # kein Zugriff -> Rückfall
    await user.should_see("Buchungen")


async def test_meine_reinigungen_zeigt_nur_die_eigenen(user: User, mock_backend,
                                                       tmp_path, monkeypatch):
    """Zwei Reinigungen heute – eine für Gabriel, eine für Valeriya.

    Valeriya muss auf einen Blick sehen, welche Wohnung ihre ist. „Meine
    Reinigungen" ist deshalb der Startbildschirm und zeigt ausschließlich die
    eigenen; zugewiesen wird unter „Alle Reinigungen".
    """
    from app import bookings as bk
    _hk_mocks(monkeypatch, tmp_path)
    for name in ("vale", "gabi"):
        monkeypatch.setitem(web.USERS, name, {
            "password_hash": auth.hash_password(name), "role": "putzkraft",
            "totp_secret": "", "name": {"vale": "Valeriya", "gabi": "Gabriel"}[name]})

    heute = date.today().isoformat()
    from app import data as _data

    def _b(bid, apt_id, apt_name):
        return {"id": bid, "type": "reservation", "is-blocked-booking": False,
                "apartment": {"id": apt_id, "name": apt_name},
                "arrival": "2026-07-01", "departure": heute,
                "check-in": "15:00", "check-out": "10:00", "adults": 2, "children": 0,
                "guest-name": f"Gast {bid}", "channel": {"name": "Direct booking"},
                "notice": ""}
    monkeypatch.setattr(_data, "_reservations", lambda *a, **k: [
        _b(801, 2748963, "Cottaer Straße"), _b(802, 2960031, "Wernerstraße")])
    bk.set_assignment(801, "vale", "admin")      # Cottaer Straße -> Valeriya
    bk.set_assignment(802, "gabi", "admin")      # Wernerstraße   -> Gabriel

    await user.open("/login")
    user.find(marker="login-user").type("vale")
    user.find(marker="login-pw").type("vale")
    user.find("Anmelden").click()
    await user.open("/")

    await user.should_see("Meine Reinigungen")
    await user.should_see("Alle Reinigungen")
    # Startbildschirm ist "Meine" – dort steht NUR Valeriyas Wohnung.
    meine = _texte_unter(user, "panel-meine")
    assert "Cottaer Straße" in meine, meine
    assert "Wernerstraße" not in meine, f"Gabriels Wohnung in 'Meine': {meine}"
    # Unter "Alle" stehen beide – dort wird zugewiesen.
    alle = _texte_unter(user, "panel-alle")
    assert "Cottaer Straße" in alle and "Wernerstraße" in alle, alle


async def test_ohne_zuweisung_startet_alle_reinigungen(user: User, mock_backend,
                                                       tmp_path, monkeypatch):
    """Wer nichts zugewiesen hat, landet dort, wo es etwas zu holen gibt."""
    _hk_mocks(monkeypatch, tmp_path)
    _mock_booking(monkeypatch)
    monkeypatch.setitem(web.USERS, "neu", {
        "password_hash": auth.hash_password("neu"), "role": "putzkraft",
        "totp_secret": "", "name": "Neu"})
    await user.open("/login")
    user.find(marker="login-user").type("neu")
    user.find(marker="login-pw").type("neu")
    user.find("Anmelden").click()
    await user.open("/")
    # "Alle Reinigungen" ist aktiv -> die Buchung ist sichtbar
    await user.should_see("Cottaer Straße")


async def test_startseite_ist_meine_reinigungen(user: User, mock_backend,
                                                tmp_path, monkeypatch):
    """Nach dem Anmelden ist „Meine Reinigungen" die erste Seite – auch wenn in
    einer früheren Sitzung ein anderer Bereich offen war."""
    _hk_mocks(monkeypatch, tmp_path)
    await _login(user)
    user.find(marker="nav-zeiterfassung").click()
    await user.should_see("Meine Übersicht")
    with user.client:
        assert web._cur_area() == "zeiterfassung"

    with user.client:                              # Sitzung beenden
        web.app.storage.user["authenticated"] = False
    await _login(user)                             # frische Anmeldung
    with user.client:
        assert web._cur_area() == "buchungen", "Start nicht auf der Buchungsseite"
    await user.should_see("Meine Reinigungen")


async def test_kalender_knopf_auf_der_reinigungskarte(user: User, mock_backend,
                                                      tmp_path, monkeypatch):
    """Aus einem Putzevent heraus lässt sich der Termin als .ics laden."""
    from app import bookings as bk
    _hk_mocks(monkeypatch, tmp_path)
    _mock_booking(monkeypatch)
    bk.set_assignment(111, "test", "test")        # damit die Karte unter "Meine" steht
    await _login(user)
    await user.should_see(marker="ical")
    knopf = list(user.find(marker="ical").elements)[0]
    assert "Kalender" in (knopf.text or "")


def test_ics_der_gemockten_buchung_ist_gueltig():
    """Fachlicher Gegencheck ohne Oberfläche: Wechseltag-Fenster stimmt."""
    from app import ical
    job = {"id": 111, "apartment_name": "Cottaer Straße", "departure": "2026-08-05",
           "checkout_time": "10:00", "guest": "Max Mustermann",
           "next": {"arrival": "2026-08-05", "checkin_time": "15:00",
                    "adults": 2, "children": 0, "guest": "Erika Musterfrau"}}
    text = ical.cleaning_event(job).decode("utf-8")
    assert "DTSTART;TZID=Europe/Berlin:20260805T100000" in text
    assert "DTEND;TZID=Europe/Berlin:20260805T150000" in text
    assert "Wechseltag" in text


async def test_checklisten_aus_blendet_alles_aus(user: User, mock_backend,
                                                 tmp_path, monkeypatch):
    """Vorgabe: Checklisten aus. Dann darf nirgends mehr etwas davon auftauchen."""
    _hk_mocks(monkeypatch, tmp_path)
    _mock_booking(monkeypatch)
    assert not web._checklisten_an(), "Checklisten müssen per Vorgabe aus sein"

    await _login(user)
    await user.should_not_see("Weiter zur Checkliste")
    await user.should_not_see("Checkliste")

    user.find(marker="booking-details").click()
    await user.should_see("Aktionen")
    await user.should_not_see("Checkliste & Fotos")

    user.find(marker="nav-uebersicht").click()
    await user.should_see("Zusammenfassung")
    await user.should_not_see("Durchgänge")
    await user.should_not_see("Räume & Aufgaben")      # Konfiguration ohne Checkliste
    await user.should_see("Bestandsliste (Verbrauch/Wäsche)")   # bleibt


async def test_fertig_haengt_ohne_checkliste_nur_an_der_zeit(
        user: User, mock_backend, tmp_path, monkeypatch):
    """Ohne Checkliste käme sonst NIE ein „Fertig" zustande."""
    from datetime import datetime
    from app import bookings as bk
    _hk_mocks(monkeypatch, tmp_path)
    _mock_booking(monkeypatch)
    heute = date.today()
    timetrack.add_manual("test", datetime(heute.year, heute.month, heute.day, 9),
                         datetime(heute.year, heute.month, heute.day, 11),
                         booking_id=111, apartment="Cottaer Straße")
    bk.set_assignment(111, "test", "test")

    job = {"id": 111, "apartment_id": 2748963, "departure": heute.isoformat()}
    assert web._booking_status(job) == "abgeschlossen"

    monkeypatch.setitem(web.CFG, "checklisten_aktiv", True)
    assert web._booking_status(job) != "abgeschlossen", \
        "Mit Checklisten muss die Checkliste zusätzlich zählen"
