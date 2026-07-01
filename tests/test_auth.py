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


def test_storage_secret_persistiert():
    cfg = {}
    s1 = auth.ensure_storage_secret(cfg)
    s2 = auth.ensure_storage_secret(cfg)
    assert s1 == s2 and len(s1) >= 32
