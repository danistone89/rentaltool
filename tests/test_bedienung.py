"""AP-D2: Bildschirme am Handy – Kopfzeile, Tap-Ziele, die drei Zustände.

Der wichtigste Test hier ist `test_ausfall_sieht_nicht_aus_wie_feierabend`.
Fällt Smoobu aus, kamen bisher null Buchungen zurück, und die Liste meldete
„Keine anstehenden Reinigungen" – eine Putzkraft hätte daraus geschlossen, dass
sie heute frei hat. Ein Ausfall muss als Ausfall dastehen.
"""
import pytest
from nicegui.testing import User

from app import auth, data, mailer, smoobu, web
from app.ui import basis, buchungen as ui_buchungen


@pytest.fixture
def angemeldet(monkeypatch):
    monkeypatch.setattr(data, "get_apartments", lambda: [
        {"id": 2748963, "name": "Cottaer Straße"}])
    monkeypatch.setattr(mailer, "send_notify", lambda *a, **k: None)
    monkeypatch.setitem(web.USERS, "nutzer", {
        "password_hash": auth.hash_password("geheim"), "role": "admin",
        "totp_secret": "", "name": "nutzer"})
    ui_buchungen._ABRUF["fehler"] = None      # Merker ist modulweit
    web._APARTMENTS.clear()


async def _anmelden(user):
    await user.open("/login")
    user.find(marker="login-user").type("nutzer")
    user.find(marker="login-pw").type("geheim")
    user.find("Anmelden").click()
    await user.open("/")


def _kaputt(*_a, **_k):
    raise smoobu.SmoobuError("Zeitüberschreitung beim Abruf")


# ------------------------------------------------------- Die drei Zustände
async def test_ausfall_sieht_nicht_aus_wie_feierabend(user: User, angemeldet, monkeypatch):
    """Der gefährlichste Fall: kein Abruf, aber die Liste meldet Ruhe."""
    monkeypatch.setattr(data, "_reservations", _kaputt)
    await _anmelden(user)
    await user.should_see("Die Buchungen konnten nicht geladen werden.")
    await user.should_see("Nochmal versuchen")
    await user.should_not_see("Keine anstehenden Reinigungen.")
    await user.should_not_see("Dir ist gerade keine Reinigung zugewiesen.")


async def test_wirklich_leer_bleibt_leer(user: User, angemeldet, monkeypatch):
    """Kommt der Abruf durch und bringt nichts, ist das kein Fehler."""
    monkeypatch.setattr(data, "_reservations", lambda *a, **k: [])
    await _anmelden(user)
    await user.should_see("Dir ist gerade keine Reinigung zugewiesen.")
    await user.should_not_see("Die Buchungen konnten nicht geladen werden.")


def test_merker_vergisst_den_fehler_nach_einem_guten_abruf(monkeypatch):
    """Sonst bliebe die Störmeldung stehen, obwohl längst wieder alles geht."""
    monkeypatch.setattr(data, "_reservations", _kaputt)
    ui_buchungen._cleaning_jobs(quiet=True)
    assert ui_buchungen.abruf_fehler()

    monkeypatch.setattr(data, "_reservations", lambda *a, **k: [])
    ui_buchungen._cleaning_jobs(quiet=True)
    assert ui_buchungen.abruf_fehler() is None


def test_stoerung_nennt_den_grund(monkeypatch):
    """Ein „irgendwas ging schief" hilft niemandem beim Weitermelden."""
    monkeypatch.setattr(data, "_reservations", _kaputt)
    ui_buchungen._cleaning_jobs(quiet=True)
    assert "Zeitüberschreitung" in ui_buchungen.abruf_fehler()


# --------------------------------------------------------- Die Kopfzeile
def _eines(user, marker):
    """Das eine Element mit diesem Marker. Über den Text zu suchen wäre
    unzuverlässig: „Buchungen" steht auch in der Leiste und in der Schublade."""
    treffer = list(user.find(marker=marker).elements)
    assert len(treffer) == 1, f"{len(treffer)}× {marker} statt genau einmal"
    return treffer[0]


async def test_unterzeile_tritt_am_handy_zurueck(user: User, angemeldet, monkeypatch):
    """Am Monitor trägt die Kopfzeile die Unterzeile, am Handy kostet sie nur
    Höhe – sie bleibt im Markup, verschwindet aber aus dem Bild."""
    monkeypatch.setattr(data, "_reservations", lambda *a, **k: [])
    await _anmelden(user)
    with user.client:
        unterzeile = _eines(user, "bereich-unterzeile")
        assert unterzeile.text == "Reinigungs-Übersicht & Buchungskalender"
        assert "hidden" in unterzeile._classes
        assert "sm:block" in unterzeile._classes


async def test_titel_waechst_erst_am_rechner(user: User, angemeldet, monkeypatch):
    monkeypatch.setattr(data, "_reservations", lambda *a, **k: [])
    await _anmelden(user)
    with user.client:
        titel = _eines(user, "bereich-titel")
        assert titel.text == "Buchungen"
        assert "text-lg" in titel._classes          # Handy
        assert "sm:text-2xl" in titel._classes      # ab Tablet


def test_kopfzeile_gibt_es_nur_einmal():
    """Vier Bereiche hatten die Kopfzeile Zeile für Zeile nachgebaut. Wer eine
    davon ändert, ändert sonst nur eine – deshalb steht sie jetzt allein in
    `basis.bereichskopf`, und das Erkennungsmerkmal darf nirgends sonst stehen.
    """
    import inspect
    from app.ui import belege, buchungen, reinigung
    merkmal = "text-3xl text-primary"        # das grosse Symbol der Kopfzeile
    assert merkmal in inspect.getsource(basis.bereichskopf)
    for modul in (belege, buchungen, reinigung, web):
        assert merkmal not in inspect.getsource(modul), (
            f"{modul.__name__} baut die Kopfzeile wieder selbst nach")


# ------------------------------------------------------------ Tap-Ziele
async def test_aufgabe_ist_auf_ganzer_zeile_antippbar(user: User, angemeldet,
                                                      monkeypatch, tmp_path):
    """Der Text gehört ins Kästchen, nicht daneben – sonst muss der Daumen ein
    Ziel von 20 Punkten treffen."""
    from test_web import _aktion_klicken, _mock_booking
    from app import housekeeping as hk
    from nicegui import ui as _ui

    monkeypatch.setattr(hk, "MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setitem(web.CFG, "checklisten_aktiv", True)
    _mock_booking(monkeypatch)

    await _anmelden(user)
    user.find(marker="booking-details").click()
    await user.should_see("Aktionen")
    _aktion_klicken(user, "Checkliste & Fotos")
    await user.should_see("Räume & Aufgaben")

    with user.client:
        kaesten = [e for e in user.find(_ui.checkbox).elements
                   if "aufgabe" in e._classes]
        assert kaesten, "keine Aufgaben-Kästchen gefunden"
        for k in kaesten:
            assert k.text, "Aufgabe ohne Text – der Text säße wieder daneben"
            assert "min-h-[44px]" in k._classes
