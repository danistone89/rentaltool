"""AP-D1: die Leiste unten und das Menü.

Zwei Ebenen werden geprüft. Zuerst der **Plan** – `basis.nav_plan()` ist eine
reine Funktion und entscheidet, was jede Rolle unten sieht und was ins Menü
rutscht; sie lässt sich ohne Oberfläche festnageln. Danach die **Oberfläche**:
dass Leiste und Menü wirklich daraus entstehen und der aktive Platz markiert
ist.

Regel 7 des Konzepts – „eine Quelle für beide Ansichten" – ist der Grund, warum
hier so viel an der reinen Funktion hängt: laufen Leiste und Schublade
auseinander, dann hier.
"""
from datetime import date

import pytest
from nicegui.testing import User

from app import auth, web
from app.ui import basis

# Die Marker der Leiste heißen bar-*, die der Schublade nav-*, die des
# Menü-Blatts menu-*. Der vierte Platz ist immer "menue".
ROLLEN = ["admin", "manager", "putzkraft"]


# ---------------------------------------------------------------- Der Plan
@pytest.mark.parametrize("rolle", ROLLEN)
def test_vier_plaetze_nie_mehr(rolle):
    """Ab fünf Plätzen werden die Ziele schmaler als ein Daumen."""
    leiste, _menue = basis.nav_plan(rolle)
    assert len(leiste) <= basis.BAR_PLAETZE == 3, (
        f"{rolle}: {len(leiste)} Bereiche unten – mit dem Menü wären das "
        f"{len(leiste) + 1} Plätze.")


@pytest.mark.parametrize("rolle", ROLLEN)
def test_nichts_geht_verloren(rolle):
    """Was nicht in die Leiste passt, verschwindet nicht – es steht im Menü."""
    leiste, menue = basis.nav_plan(rolle)
    geplant = {a["key"] for a in leiste + menue}
    assert geplant == basis.ROLE_AREAS[rolle]


@pytest.mark.parametrize("rolle", ROLLEN)
def test_der_plan_schaltet_nichts_frei(rolle):
    """Die Rechte stehen weiterhin allein in ROLE_AREAS."""
    leiste, menue = basis.nav_plan(rolle)
    for eintrag in leiste + menue:
        assert eintrag["key"] in basis.ROLE_AREAS[rolle]


def test_reihenfolge_der_putzkraft():
    """Sie öffnet die App, um zu sehen, was sie heute putzt."""
    leiste, menue = basis.nav_plan("putzkraft")
    assert [a["key"] for a in leiste] == ["buchungen", "zeiterfassung", "belege"]
    assert menue == []                      # sie hat nur diese drei Bereiche


@pytest.mark.parametrize("rolle", ["admin", "manager"])
def test_reihenfolge_der_verwaltung(rolle):
    """Sie öffnet die App, um zu sehen, ob etwas offen ist."""
    leiste, menue = basis.nav_plan(rolle)
    assert [a["key"] for a in leiste] == ["buchungen", "uebersicht", "belege"]
    assert "zeiterfassung" in [a["key"] for a in menue]


def test_putzkraft_liest_reinigungen_nicht_buchungen():
    """Unter „buchungen" findet sie ihre Aufträge – „Buchungen" wäre für sie
    schlicht falsch beschriftet."""
    leiste, _ = basis.nav_plan("putzkraft")
    buchungen_platz = next(a for a in leiste if a["key"] == "buchungen")
    assert buchungen_platz["label"] == "Reinigungen"
    assert buchungen_platz["bar_label"] == "Reinigungen"
    # Für die Verwaltung bleibt es "Buchungen".
    leiste_admin, _ = basis.nav_plan("admin")
    assert next(a for a in leiste_admin if a["key"] == "buchungen")["label"] == "Buchungen"


def test_kurzform_nur_in_der_leiste():
    """Beschriftung immer sichtbar – also muss sie unten in eine Zeile passen.
    Im Menü ist Platz für das ganze Wort."""
    leiste, menue = basis.nav_plan("putzkraft")
    zeiten = next(a for a in leiste if a["key"] == "zeiterfassung")
    assert zeiten["bar_label"] == "Zeiten"
    assert zeiten["label"] == "Zeiterfassung"
    _leiste_admin, menue_admin = basis.nav_plan("admin")
    steuer = next(a for a in menue_admin if a["key"] == "beherbergungssteuer")
    assert steuer["label"] == "Beherbergungssteuer"      # im Menü ausgeschrieben


def test_unbekannte_rolle_bekommt_keine_leiste():
    """Wer keine Rolle hat, sieht keine Bereiche – nicht versehentlich alle."""
    assert basis.nav_plan("") == ([], [])
    assert basis.nav_plan("gaertner") == ([], [])


def test_zwischenschritt_gehoert_zu_den_reinigungen():
    """Der Checklisten-Durchgang ist kein eigener Platz, sondern gehört zu dem,
    aus dem er geöffnet wurde."""
    assert basis.platz_von("reinigung") == "buchungen"
    assert basis.platz_von("belege") == "belege"        # alles andere bleibt es selbst


# ------------------------------------------------------------ Die Oberfläche
@pytest.fixture
def kein_backend(monkeypatch):
    """Nur anmelden können – die Bereiche selbst interessieren hier nicht."""
    from app import data, mailer
    monkeypatch.setattr(data, "get_apartments", lambda: [])
    monkeypatch.setattr(data, "_reservations", lambda *a, **k: [])
    monkeypatch.setattr(mailer, "send_notify", lambda *a, **k: None)
    web._APARTMENTS.clear()


async def _anmelden(user, monkeypatch, rolle):
    monkeypatch.setitem(web.USERS, "nutzer", {
        "password_hash": auth.hash_password("geheim"), "role": rolle,
        "totp_secret": "", "name": "nutzer"})
    await user.open("/login")
    user.find(marker="login-user").type("nutzer")
    user.find(marker="login-pw").type("geheim")
    user.find("Anmelden").click()
    await user.open("/")


def _klassen(user, marker):
    """Die CSS-Klassen des Elements mit diesem Marker."""
    element = next(iter(user.find(marker=marker).elements))
    return element._classes


async def test_putzkraft_sieht_ihre_drei_plaetze(user: User, kein_backend, monkeypatch):
    await _anmelden(user, monkeypatch, "putzkraft")
    for platz in ["bar-buchungen", "bar-zeiterfassung", "bar-belege", "bar-menue"]:
        await user.should_see(marker=platz)
    await user.should_not_see(marker="bar-uebersicht")            # nicht erlaubt
    await user.should_not_see(marker="bar-beherbergungssteuer")   # nicht erlaubt


async def test_verwaltung_sieht_die_uebersicht_unten(user: User, kein_backend, monkeypatch):
    await _anmelden(user, monkeypatch, "admin")
    for platz in ["bar-buchungen", "bar-uebersicht", "bar-belege", "bar-menue"]:
        await user.should_see(marker=platz)
    # Zeiterfassung und Steuer stehen nicht unten, sondern im Menü.
    await user.should_not_see(marker="bar-zeiterfassung")
    await user.should_see(marker="menu-zeiterfassung")
    await user.should_see(marker="menu-beherbergungssteuer")


async def test_kopfzeile_ist_ausgeraeumt(user: User, kein_backend, monkeypatch):
    """Benutzer, Einstellungen, Mein Konto und Abmelden ziehen ins Menü –
    das gibt am Handy eine Zeile Inhalt zurück."""
    await _anmelden(user, monkeypatch, "admin")
    for eintrag in ["konto", "benutzer", "einstellungen", "archiv", "abmelden"]:
        await user.should_see(marker=f"menu-{eintrag}")


async def test_putzkraft_bekommt_keine_verwaltung_ins_menue(user: User, kein_backend,
                                                            monkeypatch):
    await _anmelden(user, monkeypatch, "putzkraft")
    await user.should_see(marker="menu-konto")            # Mein Zugang schon
    await user.should_see(marker="menu-abmelden")
    await user.should_not_see(marker="menu-benutzer")     # Verwaltung nicht
    await user.should_not_see(marker="menu-einstellungen")


async def test_aktiver_platz_ist_doppelt_markiert(user: User, kein_backend, monkeypatch):
    """Farbe UND Strich – Farbe allein trägt nicht in der Sonne. Beides hängt
    an derselben Klasse, geprüft wird also, dass genau ein Platz sie trägt."""
    await _anmelden(user, monkeypatch, "admin")
    with user.client:
        assert "nav-aktiv" in _klassen(user, "bar-buchungen")   # Startbereich
        assert "nav-aktiv" not in _klassen(user, "bar-belege")

    user.find(marker="bar-belege").click()
    await user.should_see("Belege")
    with user.client:
        assert "nav-aktiv" in _klassen(user, "bar-belege")
        assert "nav-aktiv" not in _klassen(user, "bar-buchungen")


async def test_bereich_aus_dem_menue_laesst_das_menue_leuchten(user: User, kein_backend,
                                                               monkeypatch):
    """Sonst wäre in der Leiste nirgends zu sehen, wo man ist – und ohne
    Adressleiste ist das die einzige Orientierung."""
    await _anmelden(user, monkeypatch, "admin")
    user.find(marker="nav-beherbergungssteuer").click()
    await user.should_see("Berechnen")
    with user.client:
        assert "nav-aktiv" in _klassen(user, "bar-menue")
        assert "nav-aktiv" not in _klassen(user, "bar-buchungen")


async def test_leiste_und_schublade_zeigen_dasselbe(user: User, kein_backend, monkeypatch):
    """Eine Quelle für beide Ansichten: jeder Bereich der Rolle ist in der
    Schublade zu finden, und die Leiste zeigt genau die ersten drei davon."""
    await _anmelden(user, monkeypatch, "admin")
    leiste, menue = basis.nav_plan("admin")
    for eintrag in leiste + menue:
        await user.should_see(marker=f"nav-{eintrag['key']}")
    for eintrag in leiste:
        await user.should_see(marker=f"bar-{eintrag['key']}")


# ---------------------------------------------------------------- Der Zähler
# Genau ein Zähler in der ganzen App, und er sitzt auf „Reinigungen". Mehr
# Zähler heißt: keiner wird mehr gelesen.
def _job(nr, tage_voraus=0):
    from datetime import timedelta
    return {"id": nr,
            "departure": (date.today() + timedelta(days=tage_voraus)).isoformat(),
            "checkout_time": "23:59"}     # heute noch nicht überfällig


@pytest.fixture
def jobs(monkeypatch):
    """Die Reinigungsliste ersetzen – hier zählt nur, was der Zähler daraus macht."""
    from app.ui import buchungen as ui_buchungen

    def setzen(*eintraege):
        monkeypatch.setattr(ui_buchungen, "_cleaning_jobs",
                            lambda *a, **k: list(eintraege))
    return setzen


def test_putzkraft_zaehlt_was_heute_ansteht(jobs):
    from app import bookings
    from app.ui.buchungen import nav_zaehler
    jobs(_job(1), _job(2), _job(3, tage_voraus=1))
    bookings.set_assignment(1, "vale", by="chef")
    bookings.set_assignment(2, "olga", by="chef")
    bookings.set_assignment(3, "vale", by="chef")      # morgen – nicht heute
    assert nav_zaehler("vale", verwaltung=False) == 1


def test_erledigtes_zaehlt_nicht_mehr(jobs):
    """Sonst stünde die Zahl bis Mitternacht da, obwohl nichts mehr ansteht."""
    from app import bookings, timetrack
    from app.ui.buchungen import nav_zaehler
    jobs(_job(1))
    bookings.set_assignment(1, "vale", by="chef")
    assert nav_zaehler("vale", verwaltung=False) == 1
    from datetime import datetime, time
    heute = date.today()
    timetrack.add_manual("vale", datetime.combine(heute, time(9, 0)),
                         datetime.combine(heute, time(10, 30)), booking_id=1)
    assert nav_zaehler("vale", verwaltung=False) == 0


def test_verwaltung_zaehlt_was_niemandem_gehoert(jobs):
    from app import bookings
    from app.ui.buchungen import nav_zaehler
    jobs(_job(1), _job(2, tage_voraus=3), _job(3, tage_voraus=6))
    bookings.set_assignment(2, "vale", by="chef")
    assert nav_zaehler("chef", verwaltung=True) == 2


def test_verwaltung_schaut_sieben_tage_weit(jobs):
    """Weiter zu schauen macht die Zahl groß und die Dringlichkeit unklar."""
    from app.ui.buchungen import nav_zaehler
    jobs(_job(1, tage_voraus=6), _job(2, tage_voraus=8))
    assert nav_zaehler("chef", verwaltung=True) == 1


def test_ueberfaelliges_ohne_zuweisung_rutscht_nicht_durch(jobs):
    """„Überfällig" ist ein anderer Status – gehören tut die Reinigung trotzdem
    niemandem, und genau die darf der Zähler nicht verschlucken."""
    from app.ui.buchungen import nav_zaehler
    ueberfaellig = {**_job(1), "checkout_time": "00:01"}   # heute, längst vorbei
    jobs(ueberfaellig)
    assert nav_zaehler("chef", verwaltung=True) == 1


def test_nichts_zu_tun_heisst_kein_zaehler(jobs):
    """0 heißt „kein Zähler". Eine Null anzuschreiben wäre eine Zahl, die nichts
    sagt, und entwertet die anderen."""
    from app.ui.buchungen import nav_zaehler
    jobs()
    assert nav_zaehler("vale", verwaltung=False) == 0
    assert nav_zaehler("chef", verwaltung=True) == 0


async def test_checklisten_durchgang_haelt_reinigungen_aktiv(
        user: User, kein_backend, monkeypatch, tmp_path):
    """Regel 4 am lebenden Objekt: der Checklisten-Durchgang wird aus einer
    Buchung geöffnet und ist kein eigener Platz. Springt die Markierung dabei
    weg, verliert man beim Zurückgehen die Spur."""
    from test_web import _aktion_klicken, _mock_booking
    from app import data, housekeeping as hk

    monkeypatch.setattr(data, "get_apartments", lambda: [
        {"id": 2748963, "name": "Cottaer Straße"}])
    monkeypatch.setattr(hk, "MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setitem(web.CFG, "checklisten_aktiv", True)
    _mock_booking(monkeypatch)

    await _anmelden(user, monkeypatch, "admin")
    user.find(marker="booking-details").click()
    await user.should_see("Aktionen")
    _aktion_klicken(user, "Checkliste & Fotos")
    await user.should_see("Räume & Aufgaben")       # der Durchgang läuft
    with user.client:
        assert "nav-aktiv" in _klassen(user, "bar-buchungen")
        assert "nav-aktiv" not in _klassen(user, "bar-menue")
