"""Probe-Instanz und Wächter.

Zwei Dinge, bei denen ein Denkfehler teuer wird: die Probe-Instanz, die aus
Versehen an echte Empfänger schreibt, und ein Wächter, der so oft meldet, dass
man seine Mails nicht mehr liest.
"""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import mailer, mode, smoobu  # noqa: E402
from tools import staging_refresh, watchdog  # noqa: E402


# ------------------------------------------------------------ Konfiguration entschärfen
def _echte_config():
    return {
        "smoobu_api_key": "geheim",
        "app_url": "https://app.ds-apartments.de",
        "port": 3001,
        "backup_ziel": "nextcloud:03 Immobilien/Backups/rentaltool",
        "archiv_spiegel": "/mnt/nextcloud/03 Immobilien/Buchhaltung/2026",
        "belege_ordner": "/mnt/nextcloud/03 Immobilien/Belege",
        "reinigung_ordner": "/mnt/nextcloud/03 Immobilien/Reinigung",
        "archiv_webdav": {"url": "https://cloud", "user": "d", "password": "geheim"},
        "email": {"absender": "ich@example.com", "app_password": "abcd efgh"},
        "notify_email": {"absender": "ich@example.com", "app_password": "ijkl mnop"},
        "auth": {"users": {"admin": {"password_hash": "x"}}},
    }


def test_probe_kann_keine_mails_versenden():
    c = staging_refresh.entschaerfen(_echte_config())
    assert c["email"]["app_password"] == ""
    assert c["notify_email"]["app_password"] == ""


def test_probe_spiegelt_nicht_in_die_echte_nextcloud():
    c = staging_refresh.entschaerfen(_echte_config())
    assert c["archiv_spiegel"] == ""
    assert c["belege_ordner"] == ""
    assert c["reinigung_ordner"] == ""
    assert c["archiv_webdav"] == {}


def test_probe_hat_kein_sicherungsziel():
    """Sonst überschriebe eine Sicherung der Probe die echten Sicherungen."""
    assert staging_refresh.entschaerfen(_echte_config())["backup_ziel"] == ""


def test_probe_zeigt_auf_sich_selbst():
    c = staging_refresh.entschaerfen(_echte_config())
    assert c["app_url"] == staging_refresh.PROBE_URL
    assert c["port"] == 3002


def test_probe_behaelt_die_konten_zum_anmelden():
    c = staging_refresh.entschaerfen(_echte_config())
    assert "admin" in c["auth"]["users"]
    ohne = staging_refresh.entschaerfen(_echte_config(), konten=False)
    assert ohne["auth"]["users"] == {}


def test_entschaerfen_laesst_das_original_unberuehrt():
    """Sonst hinge die Entschärfung davon ab, wer die Konfiguration vorher hielt."""
    original = _echte_config()
    staging_refresh.entschaerfen(original)
    assert original["email"]["app_password"] == "abcd efgh"
    assert original["backup_ziel"].startswith("nextcloud:")


# ------------------------------------------------------------ Sperren im Code
def test_mailversand_ist_auf_der_probe_gesperrt(monkeypatch):
    """Zweite Ebene: auch mit von Hand wieder eingetragenem Passwort geht nichts raus."""
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["To"] = "putzkraft@example.com"
    monkeypatch.setattr(mode, "STAGING", True)
    with pytest.raises(mailer.MailError) as ex:
        mailer.send({"absender": "ich@example.com", "app_password": "echt"}, msg)
    assert "putzkraft@example.com" in str(ex.value)      # sagt, was es verhindert hat


def test_gastnachricht_ist_auf_der_probe_gesperrt(monkeypatch):
    monkeypatch.setattr(mode, "STAGING", True)
    with pytest.raises(smoobu.SmoobuError):
        smoobu.send_message("key", 501, "Hallo")


def test_archivspiegel_ist_auf_der_probe_aus(monkeypatch):
    from app import archive
    cfg = _echte_config()
    assert archive.has_mirror(cfg)
    monkeypatch.setattr(mode, "STAGING", True)
    assert not archive.has_mirror(cfg)
    assert archive.mirror_entry({"file": "x.pdf"}, cfg) is None
    assert archive.mirror_all(cfg) == 0


# ------------------------------------------------------------ Wächter: Melde-Bremse
def test_erster_lauf_meldet_nur_probleme():
    assert watchdog.faellig(None, ok=False, jetzt=1000)
    assert not watchdog.faellig(None, ok=True, jetzt=1000)


def test_wechsel_wird_gemeldet():
    heil = {"ok": True, "gemeldet": 0}
    kaputt = {"ok": False, "gemeldet": 1000}
    assert watchdog.faellig(heil, ok=False, jetzt=1000)      # kaputtgegangen
    assert watchdog.faellig(kaputt, ok=True, jetzt=1000)     # wieder da


def test_dauerhafter_fehler_meldet_nicht_alle_zehn_minuten():
    """Alle 10 Minuten dieselbe Mail – und man liest keine davon mehr."""
    kaputt = {"ok": False, "gemeldet": 1000}
    assert not watchdog.faellig(kaputt, ok=False, jetzt=1000 + 600)
    assert not watchdog.faellig(kaputt, ok=False, jetzt=1000 + watchdog.WIEDERVORLAGE_S - 1)
    assert watchdog.faellig(kaputt, ok=False, jetzt=1000 + watchdog.WIEDERVORLAGE_S)


def test_heiler_zustand_meldet_gar_nicht():
    heil = {"ok": True, "gemeldet": 0}
    assert not watchdog.faellig(heil, ok=True, jetzt=time.time())


# ------------------------------------------------------------ Wächter: Prüfungen
def test_sicherungspruefung_schlaegt_bei_alter_sicherung_an(tmp_path, monkeypatch):
    from datetime import datetime, timedelta
    monkeypatch.setattr(watchdog.paths, "p", lambda *t: os.path.join(str(tmp_path), *t))
    (tmp_path / "backup-status.json").write_text(json.dumps({
        "ok": True, "datei": "alt.tar.gz",
        "zeit": (datetime.now() - timedelta(hours=48)).isoformat(timespec="seconds"),
    }), encoding="utf-8")
    ok, info = watchdog._pruefe_sicherung()
    assert not ok and "48 h" in info


def test_sicherungspruefung_ist_zufrieden_mit_heute(tmp_path, monkeypatch):
    from datetime import datetime
    monkeypatch.setattr(watchdog.paths, "p", lambda *t: os.path.join(str(tmp_path), *t))
    (tmp_path / "backup-status.json").write_text(json.dumps({
        "ok": True, "datei": "heute.tar.gz",
        "zeit": datetime.now().isoformat(timespec="seconds"),
    }), encoding="utf-8")
    ok, _info = watchdog._pruefe_sicherung()
    assert ok


def test_sicherungspruefung_meldet_fehlgeschlagene_sicherung(tmp_path, monkeypatch):
    from datetime import datetime
    monkeypatch.setattr(watchdog.paths, "p", lambda *t: os.path.join(str(tmp_path), *t))
    (tmp_path / "backup-status.json").write_text(json.dumps({
        "ok": False, "fehler": ["keine Benutzerkonten im Paket"],
        "zeit": datetime.now().isoformat(timespec="seconds"),
    }), encoding="utf-8")
    ok, info = watchdog._pruefe_sicherung()
    assert not ok and "Benutzerkonten" in info


def test_nie_gelaufene_sicherung_ist_ein_fehler(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog.paths, "p", lambda *t: os.path.join(str(tmp_path), *t))
    ok, info = watchdog._pruefe_sicherung()
    assert not ok and "nie" in info


def test_oberflaechenpruefung_erkennt_seite_ohne_anmeldeformular(monkeypatch):
    """Ein Prozess, der laeuft, aber beim Rendern abstuerzt, sieht von aussen
    gesund aus – genau den Fall soll die Pruefung fangen."""
    class Antwort:
        status = 200

        def read(self):
            return b"<html><body>Interner Fehler</body></html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(watchdog.urllib.request, "urlopen", lambda *a, **k: Antwort())
    ok, info = watchdog._pruefe_oberflaeche("http://egal/login")
    assert not ok and "Anmeldeformular" in info
