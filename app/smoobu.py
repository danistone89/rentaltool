#!/usr/bin/env python3
"""Smoobu-API-Client (nur Standardbibliothek).

Zieht Apartments und Reservierungen über die Smoobu-REST-API.
Doku: https://docs.smoobu.com/  – Auth via Header "Api-Key".
"""
import json
import urllib.request
import urllib.error

from app import mode

BASE = "https://login.smoobu.com/api"


class SmoobuError(RuntimeError):
    pass


def _get(path, api_key, params=None):
    url = BASE + path
    if params:
        from urllib.parse import urlencode
        url += "?" + urlencode(params)
    req = urllib.request.Request(url, headers={
        "Api-Key": api_key,
        "Cache-Control": "no-cache",
        "Accept": "application/json",
        # Smoobu sitzt hinter Cloudflare und blockt den Default-urllib-UA
        # (Error 1010). Ein gängiger Browser-UA passiert die Prüfung.
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0 Safari/537.36",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SmoobuError(f"Smoobu HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")
    except urllib.error.URLError as e:
        raise SmoobuError(f"Smoobu nicht erreichbar: {e}")


def get_apartments(api_key):
    """Liste der Apartments: [{id, name}, ...]."""
    return _get("/apartments", api_key).get("apartments", [])


def get_reservations(api_key, date_from, date_to, apartment_ids=None):
    """Alle Reservierungen, deren Zeitraum in [date_from, date_to] fällt.

    date_from/date_to: 'YYYY-MM-DD'. Paginiert automatisch über alle Seiten.
    Liefert die rohen Buchungs-Dicts unverändert zurück.
    """
    out = []
    page = 1
    while True:
        params = {
            "from": date_from,
            "to": date_to,
            "pageSize": 100,
            "page": page,
        }
        # Smoobu erlaubt mehrfach apartmentId[]= ; wir filtern stattdessen
        # clientseitig, um die Query einfach zu halten.
        data = _get("/reservations", api_key, params)
        out.extend(data.get("bookings", []))
        if page >= int(data.get("page_count", 1) or 1):
            break
        page += 1
    if apartment_ids:
        ids = set(apartment_ids)
        out = [b for b in out if (b.get("apartment") or {}).get("id") in ids]
    return out


def get_reservation(api_key, reservation_id):
    """Einzelne Buchung mit allen Details."""
    return _get(f"/reservations/{reservation_id}", api_key)


def get_guest(api_key, guest_id):
    """Gastdaten samt Anschrift: {firstName, lastName, address:{street, postalCode,
    city, country}, emails, telephoneNumbers, ...}.

    Die Buchung selbst kennt keine Adresse – die steht am Gast. Fuer die
    Rechnung ist das der einzige Weg an Strasse und Ort (§ 14 UStG).
    """
    return _get(f"/guests/{guest_id}", api_key)


def get_guests(api_key, page_size=100):
    """Alle Gaeste samt ihrer Buchungen. Paginiert.

    Vier Abrufe reichen fuer den ganzen Bestand – die Einzelabfrage je Buchung
    waere achtzigmal so teuer.
    """
    out, page = [], 1
    while True:
        d = _get("/guests", api_key, {"page": page, "pageSize": page_size})
        out.extend(d.get("guests", []))
        if page >= int(d.get("pageCount", 1) or 1):
            break
        page += 1
    return out


def get_messages(api_key, reservation_id):
    """Nachrichtenverlauf einer Buchung: [{id, subject, message, type, createdAt}]."""
    return _get(f"/reservations/{reservation_id}/messages", api_key).get("messages", [])


def send_message(api_key, reservation_id, body, subject=""):
    """Nachricht an den Gast senden (POST). Nur bei ausdrücklicher Aktion aufrufen."""
    if mode.STAGING:
        # Die Probe-Instanz arbeitet mit echten Buchungen – ein Klick hier ginge
        # an einen echten Gast.
        raise SmoobuError(f"{mode.LABEL}: Es wird keine Gast-Nachricht gesendet.")
    data = {"messageBody": body}
    if subject:
        data["subject"] = subject
    payload = json.dumps(data).encode("utf-8")
    url = f"{BASE}/reservations/{reservation_id}/messages"
    req = urllib.request.Request(url, data=payload, method="POST", headers={
        "Api-Key": api_key, "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SmoobuError(f"Smoobu HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")
    except urllib.error.URLError as e:
        raise SmoobuError(f"Smoobu nicht erreichbar: {e}")
