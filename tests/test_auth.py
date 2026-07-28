"""Tests für Login-Hashing und TOTP."""
from app import auth


def test_passwort_hash_und_verify():
    h = auth.hash_password("geheim123")
    assert h.startswith("pbkdf2_sha256$")
    assert auth.verify_password("geheim123", h)
    assert not auth.verify_password("falsch", h)
    assert not auth.verify_password("geheim123", "kaputt")


def test_totp_roundtrip():
    secret = auth.generate_totp_secret()
    code = auth.totp_now(secret)
    assert len(code) == 6 and code.isdigit()
    assert auth.verify_totp(secret, code)
    assert auth.verify_totp(secret, f" {code} ")   # Leerzeichen tolerant
    assert not auth.verify_totp(secret, "000000") or code == "000000"
    assert not auth.verify_totp(secret, "")


def test_einladung_token_gueltig_und_einmalig():
    token, rec = auth.new_invite("einladung")
    assert rec["zweck"] == "einladung"
    assert token not in str(rec)              # gespeichert wird nur der Hash
    assert auth.invite_valid(rec, token)
    assert not auth.invite_valid(rec, "falscher-token")
    assert not auth.invite_valid(rec, "")
    assert not auth.invite_valid(None, token)
    # Einlösen = Record löschen -> derselbe Link zieht nicht mehr
    user = {"invite": rec}
    user.pop("invite")
    assert not auth.invite_valid(user.get("invite"), token)


def test_einladung_laeuft_ab():
    token, rec = auth.new_invite(ttl_h=-1)    # bereits abgelaufen
    assert not auth.invite_valid(rec, token)
    assert auth.invite_state({"invite": rec}) == "abgelaufen"


def test_invite_state():
    assert auth.invite_state({}) == "aktiv"
    assert auth.invite_state(None) == "aktiv"
    _, rec = auth.new_invite()
    assert auth.invite_state({"invite": rec}) == "offen"


def test_storage_secret_persistiert():
    cfg = {}
    s1 = auth.ensure_storage_secret(cfg)
    s2 = auth.ensure_storage_secret(cfg)
    assert s1 == s2 and len(s1) >= 32
