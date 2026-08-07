"""AP12: benannte Rechte, Login-Bremse, Protokoll.

Der Kern ist die Linie zwischen Manager und Betreiber: **der Manager führt den
Tag, der Betreiber verantwortet Nachweis und Geld.** Vorher gab es dazwischen
nichts – wer Zeiten korrigieren sollte, brauchte Administratorrechte und damit
auch Benutzerverwaltung, Einstellungen und Steuer.
"""
import time

import pytest
from nicegui.testing import User

from app import auth, data, mailer, protokoll, rechte, web


# ------------------------------------------------------------------ Rechte
def test_putzkraft_darf_nichts_verwalten():
    """Sie erfasst ihre eigene Arbeit – mehr braucht sie nicht."""
    assert rechte.rechte_von("putzkraft") == set()


def test_betreiber_darf_alles():
    assert rechte.rechte_von("admin") == set(rechte.ALLE)


@pytest.mark.parametrize("recht", [
    rechte.ZUWEISEN, rechte.ZEITEN_FREMDE, rechte.AUFTRAG_ZURUECK,
    rechte.BELEGE_BUCHEN,
])
def test_manager_fuehrt_den_tag(recht):
    assert rechte.darf("manager", recht)


@pytest.mark.parametrize("recht", [
    rechte.BELEGE_LOESCHEN, rechte.ZEITEN_ABGERECHNET, rechte.BENUTZER,
    rechte.EINSTELLUNGEN, rechte.STEUER,
])
def test_was_nachweis_oder_geld_beruehrt_bleibt_beim_betreiber(recht):
    """Ein gelöschter Beleg ist ein verlorenes Beweismittel; eine geänderte
    abgerechnete Zeit weicht von dem ab, was beim Steuerbüro liegt."""
    assert not rechte.darf("manager", recht)


def test_unbekannte_rolle_darf_nichts():
    """Nicht versehentlich alles – der Fehlerfall muss die enge Seite sein."""
    assert rechte.rechte_von("") == set()
    assert rechte.rechte_von("gaertner") == set()
    assert not rechte.darf(None, rechte.ZUWEISEN)


def test_jedes_recht_hat_eine_beschriftung():
    """Der Schlüssel taugt nicht als Text in der Oberfläche."""
    for r in rechte.ALLE:
        assert rechte.LABELS.get(r), r


def test_die_liste_ist_vollstaendig():
    """ALLE ist die Wahrheit – wer ein Recht ergänzt und es hier vergisst,
    gibt es dem Betreiber nicht."""
    vergeben = set()
    for satz in rechte.ROLLE_RECHTE.values():
        vergeben |= satz
    assert vergeben <= set(rechte.ALLE)
    assert set(rechte.ROLLE_RECHTE["admin"]) == set(rechte.ALLE)


# ------------------------------------------------------------ Login-Bremse
@pytest.fixture(autouse=True)
def frische_bremse():
    auth.bremse_zuruecksetzen()
    yield
    auth.bremse_zuruecksetzen()


def test_die_ersten_versuche_sind_frei():
    """Wer sich vertippt, soll nicht sofort ausgesperrt sein."""
    for _ in range(auth.SPERRE_AB - 1):
        assert auth.fehlversuch("wer", jetzt=1000.0) == 0
    assert auth.sperre_rest("wer", jetzt=1000.0) == 0


def test_danach_wird_gewartet_und_die_wartezeit_verdoppelt_sich():
    for _ in range(auth.SPERRE_AB):
        auth.fehlversuch("wer", jetzt=1000.0)
    erste = auth.sperre_rest("wer", jetzt=1000.0)
    assert erste == auth.SPERRE_BASIS
    auth.fehlversuch("wer", jetzt=1000.0)
    assert auth.sperre_rest("wer", jetzt=1000.0) == auth.SPERRE_BASIS * 2


def test_die_wartezeit_hat_einen_deckel():
    """Sonst wäre ein Konto nach genug Versuchen praktisch für immer zu –
    das ist dann der Angriff, nicht der Schutz."""
    for _ in range(40):
        auth.fehlversuch("wer", jetzt=1000.0)
    assert auth.sperre_rest("wer", jetzt=1000.0) == auth.SPERRE_MAX


def test_die_sperre_laeuft_ab():
    for _ in range(auth.SPERRE_AB):
        auth.fehlversuch("wer", jetzt=1000.0)
    assert auth.sperre_rest("wer", jetzt=1000.0 + auth.SPERRE_BASIS + 1) == 0


def test_eine_richtige_anmeldung_loest_die_bremse():
    for _ in range(auth.SPERRE_AB):
        auth.fehlversuch("wer", jetzt=1000.0)
    assert auth.sperre_rest("wer", jetzt=1000.0) > 0
    auth.anmeldung_geglueckt("wer")
    assert auth.sperre_rest("wer", jetzt=1000.0) == 0


def test_unbekannte_namen_werden_genauso_gebremst():
    """Sonst verrät schon das Ausbleiben der Sperre, welche Konten es gibt."""
    for _ in range(auth.SPERRE_AB):
        auth.fehlversuch("gibtesnicht", jetzt=1000.0)
    assert auth.sperre_rest("gibtesnicht", jetzt=1000.0) > 0


def test_konten_bremsen_sich_nicht_gegenseitig():
    for _ in range(auth.SPERRE_AB):
        auth.fehlversuch("eine", jetzt=1000.0)
    assert auth.sperre_rest("andere", jetzt=1000.0) == 0


# ---------------------------------------------------------------- Protokoll
def test_protokoll_haelt_fest_wer_wann_was():
    protokoll.notieren("daniel", protokoll.ROLLE_GEAENDERT, "vale",
                       "Putzkraft → Manager")
    e = protokoll.eintraege()[0]
    assert e["wer"] == "daniel" and e["ziel"] == "vale"
    assert e["was"] == protokoll.ROLLE_GEAENDERT
    assert e["ts"]


def test_neueste_zuerst():
    protokoll.notieren("a", protokoll.BELEG_GELOESCHT, "1")
    time.sleep(1.01)          # die Zeitstempel sind sekundengenau
    protokoll.notieren("b", protokoll.BELEG_GELOESCHT, "2")
    assert [e["ziel"] for e in protokoll.eintraege()][:2] == ["2", "1"]


def test_jeder_vorgang_hat_einen_klartext():
    """„rolle_geaendert" liest sich niemand freiwillig durch."""
    for was in [protokoll.BENUTZER_ANGELEGT, protokoll.BENUTZER_GELOESCHT,
                protokoll.ROLLE_GEAENDERT, protokoll.ZUGANG_ZURUECKGESETZT,
                protokoll.BELEG_GELOESCHT, protokoll.ZEIT_ABGERECHNET_GEAENDERT,
                protokoll.MONAT_GEOEFFNET, protokoll.MELDUNG_ZURUECKGESETZT]:
        assert protokoll.text_von(was) != was


def test_es_gibt_keinen_weg_einen_eintrag_zu_loeschen():
    """Ein Protokoll, das sich aufräumen lässt, beweist nichts. Geprüft werden
    Funktionen – die Konstanten heißen absichtlich „…_GELOESCHT"."""
    funktionen = [n for n in dir(protokoll) if callable(getattr(protokoll, n))]
    assert not [n for n in funktionen
                if "loesch" in n.lower() or "delete" in n.lower()]


# --------------------------------------------------------------- Oberfläche
@pytest.fixture
def app_bereit(monkeypatch):
    monkeypatch.setattr(data, "get_apartments", lambda: [])
    monkeypatch.setattr(data, "_reservations", lambda *a, **k: [])
    monkeypatch.setattr(mailer, "send_notify", lambda *a, **k: None)
    web._APARTMENTS.clear()


async def _anmelden(user, monkeypatch, rolle="admin", zweiter_faktor=""):
    monkeypatch.setitem(web.USERS, "nutzer", {
        "password_hash": auth.hash_password("geheim"), "role": rolle,
        "totp_secret": zweiter_faktor, "name": "nutzer"})
    await user.open("/login")
    user.find(marker="login-user").type("nutzer")
    user.find(marker="login-pw").type("geheim")
    user.find("Anmelden").click()
    await user.open("/")


async def test_betreiber_ohne_zweiten_faktor_wird_erinnert(user: User, app_bereit,
                                                           monkeypatch):
    await _anmelden(user, monkeypatch, "admin")
    await user.should_see(marker="2fa-hinweis")
    await user.should_see("Jetzt einrichten")


async def test_mit_zweitem_faktor_kein_hinweis(user: User, app_bereit, monkeypatch):
    await _anmelden(user, monkeypatch, "admin", zweiter_faktor="JBSWY3DPEHPK3PXP")
    await user.should_not_see(marker="2fa-hinweis")


async def test_managerin_wird_nicht_erinnert(user: User, app_bereit, monkeypatch):
    """Der Hinweis begründet sich mit „kann alles ändern und löschen" – das
    trifft auf die Managerin nicht zu."""
    await _anmelden(user, monkeypatch, "manager")
    await user.should_not_see(marker="2fa-hinweis")


async def test_managerin_darf_belege_buchen_aber_nicht_loeschen(
        user: User, app_bereit, monkeypatch):
    from app import receipts
    r = receipts.add_receipt("vale", photo=None, amount="9,90", merchant="dm")
    await _anmelden(user, monkeypatch, "manager")
    user.find(marker="nav-belege").click()
    await user.should_see(marker=f"beleg-kategorie-{r['id']}")   # buchen: ja
    await user.should_see(marker="panel-abschluss")
    with user.client:
        from nicegui import ui as _ui
        knoepfe = [b for b in user.find(_ui.button).elements
                   if "delete" in str(b._props.get("icon", ""))]
        assert not knoepfe, "Managerin sieht den Löschen-Knopf"


async def test_managerin_kommt_nicht_in_die_benutzerverwaltung(
        user: User, app_bereit, monkeypatch):
    await _anmelden(user, monkeypatch, "manager")
    await user.should_not_see(marker="nav-benutzer")
