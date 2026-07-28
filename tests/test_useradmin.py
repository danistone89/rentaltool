"""Tests für die Kommandozeilen-Benutzerverwaltung (tools/useradmin.py)."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import useradmin  # noqa: E402

from app import auth  # noqa: E402


@pytest.fixture(autouse=True)
def keine_echte_config(tmp_path, monkeypatch):
    """Sicherheitsnetz: Selbst wenn ein Test --config vergisst, darf er niemals
    die echte config.json des Repos anfassen."""
    monkeypatch.setattr(useradmin, "CONFIG", str(tmp_path / "nicht-vorhanden.json"))


@pytest.fixture
def konfig(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({
        "app_url": "https://beispiel.test",
        "auth": {"users": {
            "admin": {"password_hash": auth.hash_password("alt"), "role": "admin",
                      "totp_secret": "ABC", "name": "Administrator",
                      "email": "chef@example.com"},
            "anna": {"password_hash": auth.hash_password("anna"), "role": "putzkraft",
                     "totp_secret": "", "name": "Anna"},
        }},
    }, ensure_ascii=False), encoding="utf-8")
    return str(p)


def lauf(konfig, *argv, capsys=None):
    rc = useradmin.main(["--config", konfig, *argv])
    return rc


def gelesen(konfig):
    return json.load(open(konfig, encoding="utf-8"))["auth"]["users"]


def test_liste_zeigt_konten_ohne_geheimnisse(konfig, capsys):
    assert lauf(konfig, "liste") == 0
    out = capsys.readouterr().out
    assert "admin" in out and "anna" in out
    assert "chef@example.com" in out
    assert "pbkdf2" not in out          # keine Hashes ausgeben
    assert "ABC" not in out             # kein TOTP-Secret


def test_passwort_setzen_und_2fa_bleibt(konfig, capsys):
    assert lauf(konfig, "passwort", "admin", "--passwort", "neues-pw") == 0
    u = gelesen(konfig)["admin"]
    assert auth.verify_password("neues-pw", u["password_hash"])
    assert u["totp_secret"] == "ABC"    # 2FA nur über den eigenen Befehl entfernen


def test_neues_konto_braucht_rolle(konfig, capsys):
    assert lauf(konfig, "passwort", "bea", "--passwort", "geheim1") == 1
    assert "rolle" in capsys.readouterr().err.lower()
    assert "bea" not in gelesen(konfig)


def test_neues_konto_anlegen(konfig):
    assert lauf(konfig, "passwort", "bea", "--passwort", "geheim1",
                "--rolle", "manager", "--email", "bea@example.com") == 0
    u = gelesen(konfig)["bea"]
    assert u["role"] == "manager" and u["email"] == "bea@example.com"
    assert auth.verify_password("geheim1", u["password_hash"])


def test_zu_kurzes_passwort_wird_abgelehnt(konfig):
    assert lauf(konfig, "passwort", "anna", "--passwort", "kurz") == 1
    assert auth.verify_password("anna", gelesen(konfig)["anna"]["password_hash"])


def test_link_erzeugt_gueltigen_einmal_token(konfig, capsys):
    assert lauf(konfig, "link", "anna") == 0
    out = capsys.readouterr().out
    assert "https://beispiel.test/invite?token=" in out
    token = out.split("token=")[1].split()[0]
    assert auth.invite_valid(gelesen(konfig)["anna"]["invite"], token)


def test_link_url_ueberschreibbar(konfig, capsys):
    assert lauf(konfig, "link", "anna", "--url", "http://127.0.0.1:3001/") == 0
    assert "http://127.0.0.1:3001/invite?token=" in capsys.readouterr().out


def test_passwort_setzen_entwertet_offenen_link(konfig, capsys):
    lauf(konfig, "link", "anna")
    token = capsys.readouterr().out.split("token=")[1].split()[0]
    lauf(konfig, "passwort", "anna", "--passwort", "neues-pw")
    assert "invite" not in gelesen(konfig)["anna"]
    assert not auth.invite_valid(gelesen(konfig)["anna"].get("invite"), token)


def test_2fa_entfernen(konfig):
    assert lauf(konfig, "2fa-aus", "admin") == 0
    assert gelesen(konfig)["admin"]["totp_secret"] == ""


def test_rolle_aendern(konfig):
    assert lauf(konfig, "rolle", "anna", "manager") == 0
    assert gelesen(konfig)["anna"]["role"] == "manager"


def test_letzten_admin_nicht_loeschen(konfig, capsys):
    assert lauf(konfig, "loeschen", "admin") == 1
    assert "einzige" in capsys.readouterr().err
    assert "admin" in gelesen(konfig)


def test_loeschen(konfig):
    assert lauf(konfig, "loeschen", "anna") == 0
    assert "anna" not in gelesen(konfig)


def test_unbekannter_benutzer(konfig, capsys):
    assert lauf(konfig, "2fa-aus", "niemand") == 1
    assert "gibt es nicht" in capsys.readouterr().err


def test_config_gilt_in_beiden_reihenfolgen(konfig, capsys):
    """--config vor dem Unterbefehl darf nicht vom Unterbefehl-Default
    überschrieben werden (sonst schreibt das Werkzeug in die falsche Datei)."""
    assert useradmin.main(["--config", konfig, "rolle", "anna", "manager"]) == 0
    assert gelesen(konfig)["anna"]["role"] == "manager"
    assert useradmin.main(["rolle", "anna", "putzkraft", "--config", konfig]) == 0
    assert gelesen(konfig)["anna"]["role"] == "putzkraft"


def test_schreiben_legt_sicherung_an(konfig):
    lauf(konfig, "rolle", "anna", "manager")
    ordner = os.path.dirname(konfig)
    assert any(n.startswith("config.json.bak-") for n in os.listdir(ordner))
