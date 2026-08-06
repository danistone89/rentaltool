#!/usr/bin/env python3
"""Benachrichtigungen, die ankommen: Web Push an die Handys der Mitarbeiter.

Bisher ging jede Meldung per E-Mail. Eine neue Zuweisung landete damit in einem
Postfach, das am Arbeitstag niemand aufmacht. Web Push erscheint dagegen auf dem
Sperrbildschirm – wie eine Nachricht.

**Auf iOS geht das nur, wenn die App auf dem Home-Bildschirm liegt** (AP6). Im
Safari-Tab kommt nichts an, und die Erlaubnis muss aus einem echten Fingertipp
heraus abgefragt werden. Beides steuert die Oberfläche (`app/ui/konto_push.py`).

Verschlüsselung und VAPID übernimmt `pywebpush`. Das ist bewusst keine
Eigenbau-Stelle: Web Push verlangt ECDH-Schlüsselaustausch, HKDF und AES-GCM
nach RFC 8291, und ein Fehler darin zeigt sich nicht als Absturz, sondern als
„kommt bei manchen Geräten still nicht an".

Schlüssel (VAPID) liegen in `config.json` unter `push` und werden beim ersten
Bedarf erzeugt. Sie identifizieren **unseren Server** gegenüber Apple und
Google; werden sie ausgetauscht, sind alle bestehenden Anmeldungen wertlos –
deshalb werden sie nie stillschweigend neu erzeugt, wenn schon welche da sind.
"""
import base64
import json
import threading

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app import data, db

TABELLE = "push_abos"

# Meldearten. Schlüssel landen im Benutzerprofil, der Text steht in der
# Oberfläche – hier nur, was es gibt und was die Vorgabe ist.
ARTEN = {
    "zuweisung": True,      # dir wurde eine Reinigung zugewiesen
    "erinnerung": True,     # am Vorabend: was morgen ansteht
    "nachtragen": True,     # Arbeitszeit fehlt noch
    "schaden": True,        # Schaden gemeldet (Admin/Manager)
}


# ------------------------------------------------------------------ Schlüssel
def _cfg():
    return data.CONFIG.setdefault("push", {})


def schluessel_vorhanden():
    p = _cfg()
    return bool(p.get("privat") and p.get("oeffentlich"))


def schluessel_erzeugen(neu=False):
    """VAPID-Schlüsselpaar sicherstellen. Gibt den öffentlichen Schlüssel zurück.

    `neu=True` erzwingt ein frisches Paar – **alle bestehenden Anmeldungen
    werden dadurch ungültig**, die Geräte müssen sich neu anmelden.
    """
    p = _cfg()
    if schluessel_vorhanden() and not neu:
        return p["oeffentlich"]
    priv = ec.generate_private_key(ec.SECP256R1())
    roh = priv.private_numbers().private_value.to_bytes(32, "big")
    pub = priv.public_key().public_bytes(serialization.Encoding.X962,
                                         serialization.PublicFormat.UncompressedPoint)
    p["privat"] = base64.urlsafe_b64encode(roh).rstrip(b"=").decode()
    p["oeffentlich"] = base64.urlsafe_b64encode(pub).rstrip(b"=").decode()
    data.save_config()
    if neu:
        db.leeren(TABELLE)
    return p["oeffentlich"]


def oeffentlicher_schluessel():
    """Der Schlüssel, den der Browser beim Anmelden braucht."""
    return schluessel_erzeugen()


def _kontakt():
    """`sub`-Angabe im VAPID-Token: wen der Push-Dienst bei Problemen erreicht."""
    adresse = ((data.CONFIG.get("notify_email") or {}).get("absender")
               or (data.CONFIG.get("email") or {}).get("absender") or "")
    return f"mailto:{adresse}" if adresse else "mailto:admin@localhost"


# ------------------------------------------------------------------ Anmeldungen
def _jetzt():
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


def _kennung(endpunkt):
    """Stabile Kennung je Gerät: derselbe Endpunkt darf nur einmal drinstehen."""
    return base64.urlsafe_b64encode(endpunkt.encode()).decode()[-40:]


def anmelden(benutzer, abo, geraet=""):
    """Geräte-Anmeldung speichern (oder auffrischen). `abo` kommt aus dem Browser."""
    endpunkt = abo.get("endpoint") or ""
    schluessel = abo.get("keys") or {}
    if not (endpunkt and schluessel.get("p256dh") and schluessel.get("auth")):
        raise ValueError("Unvollständige Anmeldung aus dem Browser.")
    sid = _kennung(endpunkt)
    satz = {"id": sid, "user": benutzer, "endpoint": endpunkt, "keys": schluessel,
            "geraet": geraet or "Gerät", "erstellt": _jetzt(), "fehler": 0}
    with db.transaktion():
        vorher = db.holen(TABELLE, sid)
        if vorher:
            # Dasselbe Gerät noch einmal: Besitzer und Schlüssel auffrischen,
            # statt einen zweiten Eintrag anzulegen (sonst doppelte Meldungen).
            satz["erstellt"] = vorher.get("erstellt", satz["erstellt"])
        db.speichern(TABELLE, sid, satz)
    return satz


def abos(benutzer=None):
    return db.finden(TABELLE, benutzer=benutzer) if benutzer else db.alle(TABELLE)


def abmelden(sid):
    return db.loeschen(TABELLE, sid)


def abmelden_alle(benutzer):
    n = 0
    with db.transaktion():
        for a in db.finden(TABELLE, benutzer=benutzer):
            db.loeschen(TABELLE, a["id"])
            n += 1
    return n


# ------------------------------------------------------------------ Senden
def will(benutzer_cfg, art):
    """Möchte dieser Mitarbeiter diese Meldeart? Vorgabe: ja."""
    eigene = (benutzer_cfg or {}).get("push_arten") or {}
    return bool(eigene.get(art, ARTEN.get(art, True)))


def _senden_an(abo, nachricht, ttl):
    """Ein Gerät. Gibt (ok, tot) zurück – `tot` heißt: Anmeldung ist erloschen."""
    from pywebpush import WebPushException, webpush
    try:
        webpush(
            subscription_info={"endpoint": abo["endpoint"], "keys": abo["keys"]},
            data=json.dumps(nachricht, ensure_ascii=False),
            vapid_private_key=_cfg().get("privat"),
            vapid_claims={"sub": _kontakt()},
            ttl=ttl, timeout=15)
        return True, False
    except WebPushException as ex:
        code = getattr(getattr(ex, "response", None), "status_code", None)
        # 404/410: das Gerät hat die App gelöscht oder die Erlaubnis entzogen.
        # Solche Anmeldungen müssen weg, sonst wächst die Liste ewig und jeder
        # Versand läuft in Zeitüberschreitungen.
        return False, code in (404, 410)
    except Exception:
        return False, False


def senden(benutzer, titel, text, url="/", art="", ttl=86400):
    """An alle Geräte eines Mitarbeiters. Gibt die Anzahl zugestellter Geräte zurück.

    Tote Anmeldungen werden dabei aufgeräumt.
    """
    if not schluessel_vorhanden():
        return 0
    nachricht = {"titel": titel, "text": text, "url": url, "art": art}
    zugestellt = 0
    for abo in abos(benutzer):
        ok, tot = _senden_an(abo, nachricht, ttl)
        if ok:
            zugestellt += 1
        elif tot:
            abmelden(abo["id"])
    return zugestellt


def senden_im_hintergrund(*args, **kwargs):
    """Versand nebenher – die Oberfläche soll nicht auf den Push-Dienst warten."""
    t = threading.Thread(target=senden, args=args, kwargs=kwargs, daemon=True)
    t.start()
    return t
