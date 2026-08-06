"""Benachrichtigungen: Anmeldungen, Versand, Meldearten, Vorabend-Erinnerung.

Web Push scheitert selten laut. Es scheitert still: die Nachricht geht raus, der
Push-Dienst nimmt sie an, und auf dem Handy passiert nichts – weil die
Verschlüsselung nicht stimmt oder der Schlüssel nicht zum Abo passt. Deshalb
wird hier die Verschlüsselung **wirklich durchgeführt und wieder aufgemacht**,
statt den Versand nur zu attrappieren.
"""
import base64
import json
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import data, db, push  # noqa: E402
from tests.test_web import _login, mock_backend  # noqa: E402,F401
from tools import erinnerung  # noqa: E402


@pytest.fixture(autouse=True)
def _schluessel(monkeypatch):
    """Frische VAPID-Schlüssel je Test, ohne die echte config.json anzufassen."""
    monkeypatch.setitem(data.CONFIG, "push", {})
    monkeypatch.setattr(data, "save_config", lambda: None)
    push.schluessel_erzeugen()
    yield


def _browser_abo():
    """Ein Abo, wie es der Browser liefert – mit echtem Schlüsselpaar."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    priv = ec.generate_private_key(ec.SECP256R1())
    pub = priv.public_key().public_bytes(serialization.Encoding.X962,
                                         serialization.PublicFormat.UncompressedPoint)
    return priv, {
        "endpoint": "https://web.push.apple.com/abc123",
        "keys": {"p256dh": base64.urlsafe_b64encode(pub).rstrip(b"=").decode(),
                 "auth": base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode()},
    }


# ------------------------------------------------------------ Schlüssel
def test_schluessel_werden_nicht_stillschweigend_ausgetauscht():
    """Neue Schlüssel machen JEDE bestehende Anmeldung wertlos – das darf nie
    versehentlich passieren."""
    erster = push.oeffentlicher_schluessel()
    assert push.oeffentlicher_schluessel() == erster
    assert push.schluessel_erzeugen() == erster


def test_neue_schluessel_raeumen_die_anmeldungen_weg():
    """…und wenn sie doch getauscht werden, müssen die alten Anmeldungen weg –
    sonst laufen alle Sendeversuche in Fehler."""
    _priv, abo = _browser_abo()
    push.anmelden("vale", abo)
    assert push.abos("vale")
    push.schluessel_erzeugen(neu=True)
    assert push.abos("vale") == []


# ------------------------------------------------------------ Anmeldungen
def test_anmelden_und_abmelden():
    _priv, abo = _browser_abo()
    push.anmelden("vale", abo, "iPhone")
    gespeichert = push.abos("vale")
    assert len(gespeichert) == 1
    assert gespeichert[0]["geraet"] == "iPhone"
    assert push.abmelden(gespeichert[0]["id"])
    assert push.abos("vale") == []


def test_dasselbe_geraet_zweimal_bleibt_ein_eintrag():
    """Sonst käme jede Meldung doppelt an – der häufigste Ärger mit Push."""
    _priv, abo = _browser_abo()
    push.anmelden("vale", abo, "iPhone")
    push.anmelden("vale", abo, "iPhone")
    assert len(push.abos("vale")) == 1


def test_geraet_wechselt_den_besitzer():
    """Ein Diensthandy, an dem sich jemand anderes anmeldet, darf nicht weiter
    die Meldungen des Vorgängers bekommen."""
    _priv, abo = _browser_abo()
    push.anmelden("vale", abo, "iPhone")
    push.anmelden("gabriel", abo, "iPhone")
    assert push.abos("vale") == []
    assert len(push.abos("gabriel")) == 1


def test_unvollstaendige_anmeldung_wird_abgelehnt():
    with pytest.raises(ValueError):
        push.anmelden("vale", {"endpoint": "https://x", "keys": {}})


# ------------------------------------------------------------ Versand (echte Verschlüsselung)
def test_nachricht_kommt_verschluesselt_und_wieder_lesbar_heraus():
    """Der Kern: verschlüsseln wie im Betrieb, dann mit dem privaten Schlüssel
    des „Geräts" wieder aufmachen. Stimmt hier etwas nicht, kommt im Betrieb
    still nichts an."""
    import http_ece
    from cryptography.hazmat.primitives import serialization
    priv, abo = _browser_abo()
    push.anmelden("vale", abo, "iPhone")

    gesendet = {}

    def fake_post(url, data=None, headers=None, timeout=None, **kw):
        gesendet["url"] = url
        gesendet["daten"] = data
        gesendet["kopf"] = headers
        return mock.Mock(status_code=201, text="")

    with mock.patch("pywebpush.requests.post", side_effect=fake_post):
        assert push.senden("vale", "Neue Reinigung für dich",
                           "Cottaer Straße · 06.08.", "/", "zuweisung") == 1

    assert gesendet["url"] == abo["endpoint"]
    # VAPID: der Push-Dienst muss unseren Server erkennen können.
    assert "vapid" in gesendet["kopf"]["Authorization"].lower()
    assert gesendet["kopf"]["Content-Encoding"] == "aes128gcm"

    klartext = http_ece.decrypt(
        gesendet["daten"],
        private_key=priv,
        auth_secret=base64.urlsafe_b64decode(abo["keys"]["auth"] + "=="),
        version="aes128gcm")
    inhalt = json.loads(klartext)
    assert inhalt["titel"] == "Neue Reinigung für dich"
    assert inhalt["text"] == "Cottaer Straße · 06.08."
    assert inhalt["art"] == "zuweisung"


def test_erloschene_anmeldung_wird_aufgeraeumt():
    """410 heißt: App gelöscht oder Erlaubnis entzogen. Bleibt der Eintrag
    stehen, läuft jeder weitere Versand in Zeitüberschreitungen."""
    from pywebpush import WebPushException
    _priv, abo = _browser_abo()
    push.anmelden("vale", abo)
    antwort = mock.Mock(status_code=410, text="gone")
    with mock.patch("pywebpush.WebPusher.send",
                    side_effect=WebPushException("weg", response=antwort)):
        assert push.senden("vale", "Titel", "Text") == 0
    assert push.abos("vale") == [], "erloschene Anmeldung blieb stehen"


def test_voruebergehender_fehler_behaelt_die_anmeldung():
    """Ein Netzausfall darf die Anmeldung NICHT löschen – sonst müsste sich
    jeder nach jeder Störung neu anmelden."""
    _priv, abo = _browser_abo()
    push.anmelden("vale", abo)
    with mock.patch("pywebpush.WebPusher.send", side_effect=OSError("Netz weg")):
        assert push.senden("vale", "Titel", "Text") == 0
    assert len(push.abos("vale")) == 1


def test_ohne_schluessel_wird_nichts_gesendet(monkeypatch):
    monkeypatch.setitem(data.CONFIG, "push", {})
    assert push.senden("vale", "Titel", "Text") == 0


# ------------------------------------------------------------ Meldearten
def test_vorgabe_ist_alles_an():
    for art in push.ARTEN:
        assert push.will({}, art)


def test_abgeschaltete_art_wird_geachtet():
    u = {"push_arten": {"nachtragen": False}}
    assert not push.will(u, "nachtragen")
    assert push.will(u, "zuweisung")      # die anderen bleiben an


# ------------------------------------------------------------ Vorabend-Erinnerung
def _job(bid, apt):
    return {"id": bid, "apartment_name": apt, "departure": "2026-08-07"}


def test_erinnerung_teilt_nach_zustaendigkeit(monkeypatch):
    from app import bookings
    monkeypatch.setattr(bookings, "assignee_of",
                        lambda bid: {"1": "vale", "2": "vale"}.get(str(bid)))
    je, offen = erinnerung.verteilen([_job("1", "Cottaer Straße"),
                                      _job("2", "Wernerstraße"),
                                      _job("3", "Bergstraße")])
    assert list(je) == ["vale"] and len(je["vale"]) == 2
    assert [j["apartment_name"] for j in offen] == ["Bergstraße"]


def test_erinnerungstext_nennt_die_wohnungen():
    assert erinnerung.text_fuer([_job("1", "Wernerstraße"),
                                 _job("2", "Cottaer Straße")]) \
        == "Cottaer Straße, Wernerstraße"


def test_wer_morgen_nichts_hat_bekommt_nichts(monkeypatch, capsys):
    """Eine Erinnerung, die jeden Abend „nichts zu tun" sagt, wird nach einer
    Woche weggewischt – und dann auch die wichtige."""
    monkeypatch.setattr(erinnerung, "jobs_am", lambda tag: [])
    gesendet = []
    monkeypatch.setattr(push, "senden", lambda *a, **k: gesendet.append(a) or 1)
    erinnerung.main(["--tag", "2026-08-07"])
    assert gesendet == []


def test_offene_reinigung_geht_an_die_verwaltung(monkeypatch):
    """Der Fall, der sonst erst am Morgen auffällt – wenn niemand mehr zu
    organisieren ist."""
    from app import bookings
    from app.ui import basis
    monkeypatch.setattr(erinnerung, "jobs_am",
                        lambda tag: [_job("3", "Bergstraße")])
    monkeypatch.setattr(bookings, "assignee_of", lambda bid: None)
    monkeypatch.setitem(basis.USERS, "chef", {"role": "admin"})
    gesendet = []
    monkeypatch.setattr(push, "senden",
                        lambda benutzer, titel, text, *a, **k:
                        gesendet.append((benutzer, titel)) or 1)
    erinnerung.main(["--tag", "2026-08-07"])
    assert any(b == "chef" and "ohne Zuweisung" in tit for b, tit in gesendet)


# ------------------------------------------------------------ Service Worker
def test_service_worker_zeigt_jede_nachricht_an():
    """userVisibleOnly: zeigt der Service Worker eine Push-Nachricht NICHT an,
    entziehen die Browser nach kurzer Zeit die Erlaubnis."""
    from app.ui import pwa
    assert "showNotification" in pwa.SW_JS
    assert "notificationclick" in pwa.SW_JS
    # Antippen soll ein offenes Fenster nach vorn holen statt ein zweites zu öffnen
    assert "clients.matchAll" in pwa.SW_JS


# ------------------------------------------------------------ Oberfläche
async def test_konto_zeigt_den_abschnitt_und_die_geraete(user, mock_backend):  # noqa: F811
    """„Mein Konto“ ist der Ort, an dem man Benachrichtigungen sucht."""
    _priv, abo = _browser_abo()
    push.anmelden("test", abo, "iPhone")
    await _login(user)
    user.find(marker="nav-konto").click()
    await user.should_see("Benachrichtigungen")
    await user.should_see("Auf diesem Gerät einschalten")
    await user.should_see("iPhone")                     # angemeldetes Gerät
    await user.should_see("Wobei möchtest du Bescheid bekommen?")
    await user.should_see("Erinnerung am Vorabend")


async def test_ohne_geraet_keine_feineinstellung(user, mock_backend):  # noqa: F811
    """Schalter für Meldearten ohne ein einziges Gerät wären Kulisse."""
    await _login(user)
    user.find(marker="nav-konto").click()
    await user.should_see("Auf diesem Gerät einschalten")
    await user.should_not_see("Wobei möchtest du Bescheid bekommen?")
