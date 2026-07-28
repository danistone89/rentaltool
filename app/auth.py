#!/usr/bin/env python3
"""Login + optionale 2FA (TOTP / Google Authenticator) + Einladungs-Links.

Single-User: ein Passwort (PBKDF2-gehasht) in config.auth. Optional ein
TOTP-Secret für den zweiten Faktor. QR-Code via segno.

config.auth = {
  "password_hash": "pbkdf2_sha256$<iter>$<salt>$<hash>",
  "totp_secret": "" | "<base32>",
  "storage_secret": "<hex>"   # für signierte Session-Cookies (NiceGUI)
}
"""
import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from urllib.parse import quote

import segno

_ITER = 240_000


# ------------------------------------------------------------------ Passwort
def hash_password(password):
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITER)
    return f"pbkdf2_sha256${_ITER}${salt}${dk.hex()}"


def verify_password(password, stored):
    try:
        algo, iters, salt, hexhash = (stored or "").split("$")
        assert algo == "pbkdf2_sha256"
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iters))
        return hmac.compare_digest(dk.hex(), hexhash)
    except (ValueError, AssertionError):
        return False


# ------------------------------------------------------------------ TOTP
def generate_totp_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret_b32, counter):
    pad = "=" * ((8 - len(secret_b32) % 8) % 8)
    key = base64.b32decode(secret_b32.upper() + pad)
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7fffffff) % 1_000_000:06d}"


def totp_now(secret, at=None):
    return _hotp(secret, int((at or time.time()) // 30))


def verify_totp(secret, code, window=1):
    code = (code or "").strip().replace(" ", "")
    if not (secret and code):
        return False
    now = int(time.time() // 30)
    return any(hmac.compare_digest(_hotp(secret, now + e), code)
               for e in range(-window, window + 1))


def provisioning_uri(secret, account, issuer="Beherbergungssteuer"):
    return (f"otpauth://totp/{quote(issuer)}:{quote(account)}"
            f"?secret={secret}&issuer={quote(issuer)}")


def qr_data_uri(uri, scale=5):
    return segno.make(uri).png_data_uri(scale=scale)


# ------------------------------------------------------------------ Einladung
# Einmal-Link, mit dem sich ein Mitarbeiter selbst ein Passwort vergibt
# (Erstzugang oder vom Admin zurückgesetzter Zugang). Gespeichert wird nur der
# SHA-256-Hash des Tokens – wer die config.json liest, kommt damit nicht in die
# App. Der Klartext existiert nur im Moment des Erzeugens (Mail/Link-Dialog).
INVITE_TTL_H = 24 * 7          # 7 Tage


def new_invite(zweck="einladung", ttl_h=INVITE_TTL_H):
    """(token, record) – Record wird am Benutzer gespeichert, Token verschickt."""
    token = secrets.token_urlsafe(32)
    now = time.time()
    return token, {"hash": hashlib.sha256(token.encode()).hexdigest(),
                   "created": now, "expires": now + ttl_h * 3600,
                   "zweck": zweck}


def invite_valid(rec, token):
    """Passt der Token zum Record und ist er noch gültig?"""
    if not (rec and token):
        return False
    if time.time() > float(rec.get("expires") or 0):
        return False
    return hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(),
                               rec.get("hash", ""))


def invite_state(user):
    """'aktiv' (Passwort gesetzt, keine offene Einladung) | 'offen' | 'abgelaufen'."""
    rec = (user or {}).get("invite")
    if not rec:
        return "aktiv"
    return "offen" if time.time() <= float(rec.get("expires") or 0) else "abgelaufen"


# ------------------------------------------------------------------ Helpers
def ensure_storage_secret(auth_cfg):
    """Signier-Secret für Session-Cookies sicherstellen (persistiert)."""
    if not auth_cfg.get("storage_secret"):
        auth_cfg["storage_secret"] = secrets.token_hex(32)
    return auth_cfg["storage_secret"]


def is_configured(auth_cfg):
    return bool((auth_cfg or {}).get("password_hash"))


def totp_enabled(auth_cfg):
    return bool((auth_cfg or {}).get("totp_secret"))
