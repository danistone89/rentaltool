"""Standort fuer die Zeiterfassung: GPS, IP, Geofence.

Abschaltbar (Einstellungen -> Standorte, Vorgabe aus). Ist die Erfassung aus,
wird weder GPS noch IP abgefragt und die Mitarbeiter werden nicht nach einer
Ortungsfreigabe gefragt.
"""

from nicegui import ui
from app.ui.basis import (CFG)

# ---- Zeiterfassung: Standort + Anzeige-Helfer ------------------------------
_GEO_JS = (
    "return await new Promise((res)=>{"
    "if(!navigator.geolocation){res({error:'nicht unterstützt',code:0});return;}"
    "navigator.geolocation.getCurrentPosition("
    "p=>res({lat:p.coords.latitude,lon:p.coords.longitude,acc:p.coords.accuracy}),"
    "e=>res({error:e.message||'verweigert',code:e.code}),"
    "{enableHighAccuracy:true,timeout:12000,maximumAge:0});});"
)


def _geo_enabled():
    """Standorterfassung der Zeiterfassung aktiv? Standard: aus.

    Steuerbar unter Einstellungen -> Standorte. Ist sie aus, wird beim Ein-/
    Auschecken weder GPS noch IP abgefragt und nichts davon gespeichert.
    """
    return bool(CFG.get("standort_erfassung", False))


async def get_location():
    if not _geo_enabled():
        return {"error": "deaktiviert"}
    try:
        r = await ui.run_javascript(_GEO_JS, timeout=15.0)
    except Exception as ex:
        r = {"error": str(ex)}
    return r if isinstance(r, dict) else {"error": "unbekannt"}


async def get_ip():
    """Öffentliche IP des Clients (Router) über /api/whoami."""
    if not _geo_enabled():
        return ""
    try:
        r = await ui.run_javascript("return await (await fetch('/api/whoami')).json();",
                                    timeout=8.0)
        return (r or {}).get("ip", "") if isinstance(r, dict) else ""
    except Exception:
        return ""


def _haversine_m(lat1, lon1, lat2, lon2):
    import math
    r = 6371000
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return int(2 * r * math.asin(math.sqrt(a)))


def _match_geofence(loc):
    """(ort_name, dist_m) wenn innerhalb Radius; sonst (None, nächste_distanz)."""
    if not _geo_enabled() or not loc or loc.get("error"):
        return None, None
    best_name, best_dist = None, None
    inside_name, inside_dist = None, None
    for o in CFG.get("arbeitsorte", []):
        if o.get("lat") in (None, "") or o.get("lon") in (None, ""):
            continue
        d = _haversine_m(loc["lat"], loc["lon"], float(o["lat"]), float(o["lon"]))
        if best_dist is None or d < best_dist:
            best_dist, best_name = d, o.get("name")
        radius = int(o.get("radius_m", 150) or 150)
        if d <= radius and (inside_dist is None or d < inside_dist):
            inside_dist, inside_name = d, o.get("name")
    if inside_name is not None:
        return inside_name, inside_dist
    return None, best_dist


def geocode(address):
    """Adresse -> (lat, lon) via OpenStreetMap Nominatim. None bei Fehler."""
    import json as _json
    import urllib.parse
    import urllib.request
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": address, "format": "json", "limit": 1})
    req = urllib.request.Request(url, headers={"User-Agent": "LIVARO-Suites/1.0 (zeiterfassung)"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            res = _json.load(r)
        if res:
            return float(res[0]["lat"]), float(res[0]["lon"])
    except Exception:
        pass
    return None


def _presence(ort, dist, loc, ip):
    """Kurztext für den Anwesenheits-Nachweis. Leer, wenn die Erfassung aus ist."""
    if not _geo_enabled():
        return ""
    if ort:
        return f"✓ {ort}" + (f" ({dist} m)" if dist is not None else "")
    if loc and not loc.get("error"):
        return "⚠️ nicht am Objekt" + (f" (nächstes {dist} m)" if dist else "")
    if ip:
        return f"⚠️ kein GPS · IP {ip}"
    return "⚠️ kein Standort"
