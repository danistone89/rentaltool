#!/usr/bin/env python3
"""NiceGUI-Oberfläche für die Beherbergungssteuer-App.

Start:  python3 app/web.py   (Port aus config.json, Default 3001)
Öffnen: http://localhost:3001/

Reines Python-Frontend (NiceGUI). Fachlogik unverändert in
smoobu.py / steuer.py / pdf_form.py; Glue in data.py.
"""
import base64
import os
import sys
import time as _time
from datetime import date

# Prozess-Zeitzone auf Berlin (Server läuft sonst in UTC → erfasste Zeiten falsch)
os.environ["TZ"] = "Europe/Berlin"
try:
    _time.tzset()
except AttributeError:   # Windows kennt kein tzset
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nicegui import app, ui  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import RedirectResponse  # noqa: E402

from app import data, smoobu, archive, mailer, auth, timetrack, housekeeping, bookings, receipts  # noqa: E402
try:
    from app import pdf_form
except Exception:  # PyMuPDF optional
    pdf_form = None

os.makedirs(housekeeping.MEDIA_DIR, exist_ok=True)
app.add_static_files("/media", housekeeping.MEDIA_DIR)

CFG = data.CONFIG
AUTH = CFG.setdefault("auth", {})
_new_secret = not AUTH.get("storage_secret")
STORAGE_SECRET = auth.ensure_storage_secret(AUTH)

# ---- Mehrbenutzer + Rollen -------------------------------------------------
USERS = AUTH.setdefault("users", {})
_migrated = False
if not USERS and AUTH.get("password_hash"):   # Migration Single-User -> users
    USERS["admin"] = {"password_hash": AUTH.pop("password_hash"), "role": "admin",
                      "totp_secret": AUTH.pop("totp_secret", ""), "name": "Administrator"}
    _migrated = True

if _new_secret or _migrated:
    data.save_config()

ROLES = {"admin": "Administrator", "putzkraft": "Putzkraft"}

# Bereiche (Features). Welche Rolle was sieht, wird über ROLE_AREAS gesteuert –
# die feinen Rechte definieren wir später, hier nur das Grundgerüst.
AREAS = [
    {"key": "buchungen", "label": "Buchungen", "icon": "calendar_month"},
    {"key": "reinigung", "label": "Reinigung", "icon": "cleaning_services"},
    {"key": "belege", "label": "Belege", "icon": "receipt"},
    {"key": "zeiterfassung", "label": "Zeiterfassung", "icon": "schedule"},
    {"key": "beherbergungssteuer", "label": "Beherbergungssteuer", "icon": "receipt_long"},
]
ROLE_AREAS = {
    "admin": {a["key"] for a in AREAS},          # Admin sieht alles
    "putzkraft": {"buchungen", "reinigung", "belege", "zeiterfassung"},  # Putzkräfte
}


def _cur_user():
    return app.storage.user.get("user", "")


def _cur_role():
    return app.storage.user.get("role", "")


def _is_admin():
    return _cur_role() == "admin"


def _role_areas(role):
    return ROLE_AREAS.get(role, set())


# ---- Zeiterfassung: Anzeige-Helfer -----------------------------------------
def _t(iso):
    return iso[11:16] if iso and len(iso) >= 16 else ""


def _d(iso):
    return iso[:10] if iso else ""


# ---- Zeiterfassung: Standort + Anzeige-Helfer ------------------------------
_GEO_JS = (
    "return await new Promise((res)=>{"
    "if(!navigator.geolocation){res({error:'nicht unterstützt',code:0});return;}"
    "navigator.geolocation.getCurrentPosition("
    "p=>res({lat:p.coords.latitude,lon:p.coords.longitude,acc:p.coords.accuracy}),"
    "e=>res({error:e.message||'verweigert',code:e.code}),"
    "{enableHighAccuracy:true,timeout:12000,maximumAge:0});});"
)


async def get_location():
    try:
        r = await ui.run_javascript(_GEO_JS, timeout=15.0)
    except Exception as ex:
        r = {"error": str(ex)}
    return r if isinstance(r, dict) else {"error": "unbekannt"}


async def get_ip():
    """Öffentliche IP des Clients (Router) über /api/whoami."""
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
    if not loc or loc.get("error"):
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
    """Kurztext für den Anwesenheits-Nachweis."""
    if ort:
        return f"✓ {ort}" + (f" ({dist} m)" if dist is not None else "")
    if loc and not loc.get("error"):
        return "⚠️ nicht am Objekt" + (f" (nächstes {dist} m)" if dist else "")
    if ip:
        return f"⚠️ kein GPS · IP {ip}"
    return "⚠️ kein Standort"


def _export_csv(rows, show_user):
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow((["Mitarbeiter"] if show_user else []) +
               ["Datum", "Check-in", "Ort ein", "Check-out", "Ort aus", "Dauer"])
    for e in rows:
        w.writerow((([e["user"]] if show_user else []) + [
            _d(e["checkin"]), _t(e["checkin"]),
            _presence(e.get("checkin_ort"), e.get("checkin_dist"), e.get("checkin_loc"), e.get("checkin_ip")),
            _t(e["checkout"]) if e.get("checkout") else "",
            _presence(e.get("checkout_ort"), e.get("checkout_dist"), e.get("checkout_loc"), e.get("checkout_ip"))
            if e.get("checkout") else "",
            timetrack.fmt_dur(timetrack.duration_minutes(e))]))
    ui.download.content(buf.getvalue().encode("utf-8-sig"), "arbeitszeiten.csv",
                        media_type="text/csv")


def _zeit_table(container, rows, show_user, title, export=False):
    container.clear()
    cols = ([{"name": "user", "label": "Mitarbeiter", "field": "user", "align": "left"}]
            if show_user else []) + [
        {"name": "date", "label": "Datum", "field": "date", "align": "left"},
        {"name": "cin", "label": "Check-in", "field": "cin", "align": "left"},
        {"name": "lin", "label": "Ort ein", "field": "lin", "align": "left"},
        {"name": "cout", "label": "Check-out", "field": "cout", "align": "left"},
        {"name": "lout", "label": "Ort aus", "field": "lout", "align": "left"},
        {"name": "dur", "label": "Dauer", "field": "dur", "align": "right"},
    ]
    trows = [{
        "id": e["id"], "user": e["user"], "date": _d(e["checkin"]), "cin": _t(e["checkin"]),
        "lin": _presence(e.get("checkin_ort"), e.get("checkin_dist"), e.get("checkin_loc"), e.get("checkin_ip")),
        "cout": _t(e["checkout"]) if e.get("checkout") else "—",
        "lout": _presence(e.get("checkout_ort"), e.get("checkout_dist"), e.get("checkout_loc"), e.get("checkout_ip"))
                if e.get("checkout") else "—",
        "dur": timetrack.fmt_dur(timetrack.duration_minutes(e)),
    } for e in rows]
    with container:
        with ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100"):
            with ui.row().classes("w-full items-center"):
                ui.label(title).classes("font-medium")
                ui.space()
                if export and rows:
                    ui.button("CSV", icon="download",
                              on_click=lambda: _export_csv(rows, show_user)).props("flat dense no-caps")
            if trows:
                ui.table(columns=cols, rows=trows, row_key="id").props("dense flat").classes("w-full")
            else:
                ui.label("Noch keine Einträge.").classes("text-sm text-gray-400")

# Pfade ohne Login-Zwang: Login-Seite, Smoobu-Webhook, NiceGUI-Interna.
_UNRESTRICTED = {"/login"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if not app.storage.user.get("authenticated", False):
            path = request.url.path
            # /media = in der UI eingebettete Fotos (zufällige UUID-Dateinamen);
            # app.storage.user ist bei Static-Requests nicht verlässlich verfügbar,
            # daher hier durchlassen statt auf /login umzuleiten.
            if not (path in _UNRESTRICTED or path.startswith("/_nicegui")
                    or path.startswith("/api/") or path.startswith("/media/")):
                app.storage.user["referrer"] = path
                return RedirectResponse("/login")
        return await call_next(request)


app.add_middleware(AuthMiddleware)

DEFAULT_BETREFF = "Beherbergungssteuer-Anmeldung {monat} {jahr}"
DEFAULT_TEXT = (
    "Sehr geehrte Damen und Herren,\n\n"
    "anbei übersende ich die Steueranmeldung zur Beherbergungssteuer für "
    "{monat} {jahr} (Kassenzeichen {kassenzeichen}).\n\n"
    "Festgesetzte Beherbergungssteuer: {steuer} €.\n\n"
    "Mit freundlichen Grüßen\n{name}")


PURPLE, GOLD = "#5E2A84", "#C8A96E"

# LIVARO-Suites-Wortbildmarke als komplettes SVG (Gold-Turm-Icon + Schriftzug).
_LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 70">'
    '<g fill="none" stroke="' + GOLD + '" stroke-width="2.6" '
    'stroke-linejoin="round" stroke-linecap="round">'
    '<path d="M8 60 L8 23 L26 12 L26 60"/>'
    '<path d="M22 60 L22 33 L38 24 L38 60"/>'
    '<path d="M34 60 L34 44 L50 35 L50 60"/>'
    '</g>'
    '<text x="70" y="40" font-family="Georgia,\'Times New Roman\',serif" font-size="30" '
    'letter-spacing="7" font-weight="600" fill="' + PURPLE + '">LIVARO</text>'
    '<text x="72" y="58" font-family="Georgia,serif" font-size="13" '
    'letter-spacing="10" fill="' + GOLD + '">SUITES</text>'
    '</svg>')
_LOGO_URI = "data:image/svg+xml;base64," + base64.b64encode(_LOGO_SVG.encode()).decode()


def logo(height=44):
    """Logo als ui.image (SVG data-URI), Breite proportional (Ratio 300:70)."""
    return ui.image(_LOGO_URI).props("no-spinner fit=contain") \
        .style(f"height:{height}px;width:{round(height * 300 / 70)}px")


def _mail_context(r):
    """Platzhalter-Werte für die E-Mail-Vorlagen."""
    betr = CFG.get("betreiber", {})
    return {
        "periode": f"{r['year']}-{r['month']:02d}",
        "jahr": r["year"],
        "monat": data.MONATE[r["month"]],
        "steuer": data.euro(r["beherbergungssteuer"]),
        "umsatz": data.euro(r["umsatz_steuerpflichtig"]),
        "kassenzeichen": betr.get("kassenzeichen", ""),
        "name": (betr.get("name", "") + " " + betr.get("zusatz", "")).strip(),
    }

# Apartments einmalig laden (selten geändert)
_APARTMENTS = {}


def _load_apartments():
    if not _APARTMENTS:
        try:
            for a in data.get_apartments():
                _APARTMENTS[a["id"]] = a["name"]
        except smoobu.SmoobuError as ex:
            ui.notify(f"Smoobu: {ex}", type="negative", timeout=8000)
    return _APARTMENTS


# ---------------------------------------------------------------- Webhook
@app.post("/api/smoobu/webhook")
async def smoobu_webhook():
    data.clear_cache()
    return {"ok": True}


@app.get("/api/whoami")
def whoami(request: Request):
    """Öffentliche IP des Aufrufers (hinter nginx via X-Forwarded-For)."""
    xff = request.headers.get("x-forwarded-for", "")
    ip = xff.split(",")[0].strip() if xff else (request.client.host if request.client else "")
    return {"ip": ip}


# ---------------------------------------------------------------- Login
@ui.page("/login")
def login_page():
    ui.colors(primary="#5E2A84", secondary="#8A5CC2", accent="#C8A96E",
              positive="#16a34a", negative="#dc2626")
    ui.query("body").classes("bg-[#F5F2EB]")
    if app.storage.user.get("authenticated"):
        ui.navigate.to("/")
        return

    def finish2(username, role):
        app.storage.user["authenticated"] = True
        app.storage.user["user"] = username
        app.storage.user["role"] = role
        ui.navigate.to(app.storage.user.get("referrer") or "/")

    with ui.column().classes("absolute-center items-center gap-4"):
        logo(60)
        with ui.card().classes("w-[360px] max-w-full gap-2 rounded-xl shadow-md"):
            if not USERS:
                ui.label("Erst-Einrichtung – Administrator anlegen").classes("font-semibold")
                un = ui.input("Benutzername", value="admin").classes("w-full")
                p1 = ui.input("Passwort", password=True,
                              password_toggle_button=True).classes("w-full")
                p2 = ui.input("Passwort wiederholen", password=True).classes("w-full")

                def setup():
                    name = (un.value or "").strip()
                    if not name:
                        ui.notify("Benutzername fehlt.", type="warning"); return
                    if len(p1.value or "") < 6:
                        ui.notify("Passwort mindestens 6 Zeichen.", type="warning"); return
                    if p1.value != p2.value:
                        ui.notify("Passwörter stimmen nicht überein.", type="negative"); return
                    USERS[name] = {"password_hash": auth.hash_password(p1.value),
                                   "role": "admin", "totp_secret": "", "name": name}
                    data.save_config()
                    finish2(name, "admin")
                ui.button("Anlegen & anmelden", on_click=setup) \
                    .props("unelevated").classes("w-full")
            else:
                ui.label("Anmelden").classes("font-semibold")
                un = ui.input("Benutzername").classes("w-full")
                pw = ui.input("Passwort", password=True,
                              password_toggle_button=True).classes("w-full")
                code = ui.input("6-stelliger Code (falls 2FA aktiv)").classes("w-full")

                def do_login():
                    u = USERS.get((un.value or "").strip())
                    if not u or not auth.verify_password(pw.value or "", u.get("password_hash", "")):
                        ui.notify("Benutzername oder Passwort falsch.", type="negative"); return
                    if u.get("totp_secret") and not auth.verify_totp(u["totp_secret"], code.value or ""):
                        ui.notify("Code fehlt oder ist falsch.", type="negative"); return
                    finish2((un.value or "").strip(), u.get("role", "putzkraft"))
                for f in (un, pw, code):
                    f.on("keydown.enter", lambda: do_login())
                ui.button("Anmelden", on_click=do_login).props("unelevated").classes("w-full")


def logout():
    app.storage.user["authenticated"] = False
    ui.navigate.to("/login")


# ---------------------------------------------------------------- 2FA-Einrichtung
def open_2fa_setup(on_done=None):
    username = _cur_user()
    u = USERS.get(username)
    if not u:
        ui.notify("Kein angemeldeter Benutzer.", type="negative"); return
    secret = auth.generate_totp_secret()
    uri = auth.provisioning_uri(secret, username or "LIVARO", issuer="LIVARO Suites")
    with ui.dialog() as dlg, ui.card().classes("w-[420px] max-w-full items-center gap-2"):
        ui.label("🔐 Google Authenticator einrichten").classes("text-lg font-bold")
        ui.label("1. QR-Code in der Authenticator-App scannen:").classes("text-sm")
        ui.image(auth.qr_data_uri(uri)).classes("w-48 h-48")
        ui.label("oder Secret manuell eintippen:").classes("text-xs text-gray-500")
        ui.label(secret).classes("text-xs font-mono break-all")
        ui.label("2. Zur Bestätigung den aktuellen 6-stelligen Code eingeben:").classes("text-sm")
        code = ui.input("Code").classes("w-full")

        def confirm():
            if not auth.verify_totp(secret, code.value or ""):
                ui.notify("Code stimmt nicht – bitte erneut versuchen.", type="negative"); return
            u["totp_secret"] = secret
            data.save_config()
            ui.notify("2FA aktiviert.", type="positive")
            dlg.close()
            if on_done:
                on_done()
        with ui.row().classes("w-full justify-end"):
            ui.button("Abbrechen", on_click=dlg.close).props("flat")
            ui.button("Aktivieren", on_click=confirm).props("unelevated")
    dlg.open()


# ---------------------------------------------------------------- Mein Konto
def open_account():
    username = _cur_user()
    u = USERS.get(username, {})
    with ui.dialog() as dlg, ui.card().classes("w-[420px] max-w-full gap-2"):
        ui.label("Mein Konto").classes("text-xl font-bold")
        ui.label(f"Angemeldet als {username} · {ROLES.get(u.get('role'), u.get('role', ''))}") \
            .classes("text-sm text-gray-500")
        email_in = ui.input("E-Mail (für Benachrichtigungen)",
                            value=u.get("email", "")).classes("w-full")
        new_pw = ui.input("Neues Passwort (leer = unverändert)", password=True,
                          password_toggle_button=True).classes("w-full")
        with ui.row().classes("items-center gap-2 mt-1"):
            if u.get("totp_secret"):
                def disable_2fa():
                    u["totp_secret"] = ""
                    data.save_config()
                    ui.notify("2FA deaktiviert.", type="warning"); dlg.close()
                ui.label("🔐 2FA aktiv").classes("text-sm text-green-700")
                ui.button("2FA deaktivieren", on_click=disable_2fa).props("flat no-caps")
            else:
                ui.button("2FA aktivieren", icon="qr_code_2",
                          on_click=lambda: (dlg.close(), open_2fa_setup())).props("outline no-caps")

        def save():
            u["email"] = (email_in.value or "").strip()
            if (new_pw.value or "").strip():
                if len(new_pw.value.strip()) < 6:
                    ui.notify("Passwort zu kurz (min. 6).", type="warning"); return
                u["password_hash"] = auth.hash_password(new_pw.value.strip())
            data.save_config()
            ui.notify("Gespeichert.", type="positive")
            dlg.close()
        with ui.row().classes("w-full justify-end"):
            ui.button("Schließen", on_click=dlg.close).props("flat")
            ui.button("Speichern", on_click=save).props("unelevated")
    dlg.open()


def open_reset_pw(username):
    with ui.dialog() as dlg, ui.card().classes("w-[360px] gap-2"):
        ui.label(f"Passwort für {username} setzen").classes("font-bold")
        p = ui.input("Neues Passwort", password=True,
                     password_toggle_button=True).classes("w-full")

        def save():
            if len(p.value or "") < 6:
                ui.notify("Passwort zu kurz (min. 6).", type="warning"); return
            USERS[username]["password_hash"] = auth.hash_password(p.value)
            data.save_config()
            ui.notify(f"Passwort für {username} gesetzt.", type="positive"); dlg.close()
        with ui.row().classes("w-full justify-end"):
            ui.button("Abbrechen", on_click=dlg.close).props("flat")
            ui.button("Setzen", on_click=save).props("unelevated")
    dlg.open()


# ---------------------------------------------------------------- Benutzer (Admin)
def open_users():
    if not _is_admin():
        ui.notify("Nur für Administratoren.", type="negative"); return
    with ui.dialog() as dlg, ui.card().classes("w-[640px] max-w-full gap-2"):
        ui.label("Benutzer verwalten").classes("text-xl font-bold")
        listing = ui.column().classes("w-full gap-2")

        def render():
            listing.clear()
            with listing:
                for uname in sorted(USERS):
                    u = USERS[uname]
                    with ui.card().classes("w-full p-2"):
                        with ui.row().classes("w-full items-center gap-2 no-wrap"):
                            ui.icon("shield_person" if u.get("role") == "admin" else "person") \
                                .classes("text-primary")
                            ui.label(uname).classes("font-semibold")
                            if u.get("totp_secret"):
                                ui.label("2FA").classes("text-xs text-green-700")
                            ui.space()
                            sel = ui.select(ROLES, value=u.get("role", "putzkraft")) \
                                .props("dense outlined").classes("w-40")

                            def _role_handler(un):
                                def h(e):
                                    if un == _cur_user() and e.value != "admin":
                                        ui.notify("Eigene Admin-Rolle nicht entfernbar.",
                                                  type="warning")
                                        USERS[un]["role"] = "admin"; render(); return
                                    USERS[un]["role"] = e.value
                                    data.save_config()
                                    ui.notify(f"Rolle von {un}: {ROLES.get(e.value)}",
                                              type="positive")
                                return h
                            sel.on_value_change(_role_handler(uname))

                            ui.button("Passwort", icon="key",
                                      on_click=lambda un=uname: open_reset_pw(un)) \
                                .props("flat dense no-caps")
                            if uname != _cur_user():
                                def _del(un=uname):
                                    USERS.pop(un, None); data.save_config()
                                    ui.notify(f"{un} gelöscht.", type="warning"); render()
                                ui.button(icon="delete", on_click=_del) \
                                    .props("flat dense round color=negative").tooltip("Löschen")
                        with ui.row().classes("w-full items-center gap-2 no-wrap"):
                            em = ui.input("E-Mail (für Benachrichtigungen)",
                                          value=u.get("email", "")).props("dense outlined") \
                                .classes("flex-grow")

                            def _email_handler(un, field):
                                def h(e):
                                    USERS[un]["email"] = (field.value or "").strip()
                                    data.save_config()
                                return h
                            em.on("blur", _email_handler(uname, em))
        render()

        ui.separator()
        ui.label("Neuen Benutzer anlegen").classes("font-medium")
        with ui.row().classes("w-full items-end gap-2 flex-wrap"):
            nu = ui.input("Benutzername").props("dense outlined")
            npw = ui.input("Passwort", password=True).props("dense outlined")
            nem = ui.input("E-Mail").props("dense outlined").classes("min-w-[200px]")
            nrole = ui.select(ROLES, value="putzkraft", label="Rolle") \
                .props("dense outlined").classes("w-40")

            def add():
                name = (nu.value or "").strip()
                if not name:
                    ui.notify("Benutzername fehlt.", type="warning"); return
                if name in USERS:
                    ui.notify("Benutzername existiert bereits.", type="negative"); return
                if len(npw.value or "") < 6:
                    ui.notify("Passwort zu kurz (min. 6).", type="warning"); return
                USERS[name] = {"password_hash": auth.hash_password(npw.value),
                               "role": nrole.value, "totp_secret": "", "name": name,
                               "email": (nem.value or "").strip()}
                data.save_config()
                ui.notify(f"Benutzer {name} angelegt.", type="positive")
                nu.value = ""; npw.value = ""; nem.value = ""; render()
            ui.button("Anlegen", icon="person_add", on_click=add).props("unelevated no-caps")

        with ui.row().classes("w-full justify-end"):
            ui.button("Schließen", on_click=dlg.close).props("flat")
    dlg.open()


# ---------------------------------------------------------------- Ordner-Browser
def open_folder_picker(start, on_pick):
    state = {"dir": start if (start and os.path.isdir(start)) else os.path.expanduser("~")}
    with ui.dialog() as dlg, ui.card().classes("w-[680px] max-w-full"):
        ui.label("📁 Ordner wählen").classes("text-lg font-bold")
        path_lbl = ui.label().classes("text-xs font-mono text-gray-600 break-all")
        listing = ui.column().classes("w-full gap-1").style("max-height:60vh;overflow:auto")

        def go(p):
            state["dir"] = p
            render()

        def render():
            path_lbl.text = state["dir"]
            listing.clear()
            with listing:
                parent = os.path.dirname(state["dir"].rstrip("/"))
                if parent and parent != state["dir"]:
                    ui.button("⬆  übergeordneter Ordner", on_click=lambda: go(parent)) \
                        .props("flat dense align=left").classes("w-full")
                try:
                    subs = sorted(d for d in os.listdir(state["dir"])
                                  if not d.startswith(".")
                                  and os.path.isdir(os.path.join(state["dir"], d)))
                except OSError as ex:
                    ui.label(f"Nicht lesbar: {ex}").classes("text-red-700 text-xs")
                    subs = []
                for d in subs:
                    full = os.path.join(state["dir"], d)
                    ui.button("📁  " + d, on_click=lambda f=full: go(f)) \
                        .props("flat dense align=left no-caps").classes("w-full")

        render()
        with ui.row().classes("w-full justify-end items-center"):
            ui.button("Abbrechen", on_click=dlg.close).props("flat")
            ui.button("Diesen Ordner verwenden",
                      on_click=lambda: (on_pick(state["dir"]), dlg.close())).props("unelevated")
    dlg.open()


# ---------------------------------------------------------------- Einstellungen
def open_settings():
    if not _is_admin():
        ui.notify("Nur für Administratoren.", type="negative"); return
    betr = CFG.setdefault("betreiber", {})
    ec = CFG.setdefault("email", {})
    with ui.dialog() as dialog, ui.card().classes("w-[760px] max-w-full"):
        with ui.row().classes("w-full items-center"):
            ui.icon("settings").classes("text-xl text-primary")
            ui.label("Einstellungen").classes("text-xl font-bold")

        with ui.tabs().props("dense no-caps align=left").classes("w-full") as tabs:
            t_betr = ui.tab("Betreiber", icon="person")
            t_pdf = ui.tab("PDF & Steuer", icon="description")
            t_arch = ui.tab("Archiv", icon="cloud_upload")
            t_orte = ui.tab("Standorte", icon="place")
            t_smoobu = ui.tab("Smoobu", icon="sync")
            t_mail = ui.tab("E-Mail", icon="mail")

        with ui.tab_panels(tabs, value=t_betr).classes("w-full"):
            with ui.tab_panel(t_betr):
                ui.label("Betreiberdaten (erscheinen im PDF)").classes("text-sm text-gray-500")
                inputs = {}
                with ui.grid(columns=2).classes("w-full gap-3"):
                    for key, lbl in data.BETREIBER_FIELDS:
                        inputs[key] = ui.input(lbl, value=betr.get(key, "")).props("outlined dense").classes("w-full")

            with ui.tab_panel(t_pdf):
                with ui.grid(columns=2).classes("w-full gap-3"):
                    sig_x = ui.number("Unterschrift X (pt, größer = rechts)",
                                      value=float(CFG.get("unterschrift_x", 210)), step=5).props("outlined dense")
                    steuer_pct = ui.number("Steuersatz (%)",
                                           value=CFG.get("steuersatz", 0.06) * 100, step=0.1,
                                           format="%.1f").props("outlined dense")

            with ui.tab_panel(t_arch):
                ui.label("Jede Festschreibung wird revisionssicher abgelegt und zusätzlich "
                         "in diesen Ordner auf dem Computer kopiert.").classes("text-sm text-gray-500")
                cur = CFG.get("archiv_spiegel", "")
                with ui.row().classes("w-full items-end gap-2 mt-1"):
                    spiegel = ui.input("Ablage-Ordner", value=cur) \
                        .props("outlined dense").classes("flex-grow") \
                        .tooltip("Ordner auf dem Computer, in den die PDFs kopiert werden "
                                 "(z. B. dein Nextcloud-Sync-Ordner oder ein Buchhaltungs-Ordner).")

                    def browse():
                        detected = data.detect_cloud_folders()
                        start = spiegel.value or (detected[0] if detected else "")
                        open_folder_picker(start, lambda p: spiegel.set_value(p))
                    ui.button("Durchsuchen", icon="folder_open", on_click=browse).props("outline no-caps")

                    def check_folder():
                        p = spiegel.value
                        if not p:
                            ui.notify("Kein Ordner gewählt.", type="warning"); return
                        if not os.path.isdir(p):
                            ui.notify(f"Ordner existiert nicht: {p}", type="negative"); return
                        if not os.access(p, os.W_OK):
                            ui.notify("Ordner ist nicht beschreibbar.", type="negative"); return
                        ui.notify("Ordner OK und beschreibbar ✓", type="positive")
                    ui.button("Prüfen", on_click=check_folder).props("flat no-caps dense")

                ui.separator().classes("my-2")
                ui.label("Reinigungs-Fotos (Soll/Ist) und Belege werden zusätzlich in diesen "
                         "Ordner gespiegelt.").classes("text-sm text-gray-500")
                with ui.row().classes("w-full items-end gap-2 mt-1"):
                    reinigung_ordner = ui.input("Foto-Ordner (Reinigung)",
                                                value=CFG.get("reinigung_ordner", "")) \
                        .props("outlined dense").classes("flex-grow") \
                        .tooltip("Ordner auf dem Computer/Server (z. B. Nextcloud-Mount), in den "
                                 "Reinigungsfotos kopiert werden. Leer = nur lokal in media/.")

                    def browse_reinigung():
                        detected = data.detect_cloud_folders()
                        start = reinigung_ordner.value or (detected[0] if detected else "")
                        open_folder_picker(start, lambda p: reinigung_ordner.set_value(p))
                    ui.button("Durchsuchen", icon="folder_open",
                              on_click=browse_reinigung).props("outline no-caps")

                ui.label("Belege/Rechnungen werden zusätzlich in diesen Ordner gespiegelt.") \
                    .classes("text-sm text-gray-500 mt-2")
                with ui.row().classes("w-full items-end gap-2 mt-1"):
                    belege_ordner = ui.input("Beleg-Ordner",
                                             value=CFG.get("belege_ordner", "")) \
                        .props("outlined dense").classes("flex-grow") \
                        .tooltip("Ordner (z. B. Nextcloud-Mount), in den hochgeladene Belege "
                                 "kopiert werden. Leer = nur lokal in media/.")

                    def browse_belege():
                        detected = data.detect_cloud_folders()
                        start = belege_ordner.value or (detected[0] if detected else "")
                        open_folder_picker(start, lambda p: belege_ordner.set_value(p))
                    ui.button("Durchsuchen", icon="folder_open",
                              on_click=browse_belege).props("outline no-caps")

            with ui.tab_panel(t_orte):
                ui.label("Objekte für die GPS-Standortprüfung der Zeiterfassung. Adresse "
                         "eintragen und Lupe antippen (Koordinaten), Radius in Metern "
                         "(z. B. 150). Check-in außerhalb wird markiert.") \
                    .classes("text-sm text-gray-500")
                orte = CFG.setdefault("arbeitsorte", [])
                orte_box = ui.column().classes("w-full gap-2")

                def render_orte():
                    orte_box.clear()
                    with orte_box:
                        for i, o in enumerate(orte):
                            with ui.card().classes("w-full p-2 gap-2"):
                                with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                                    nm = ui.input("Name", value=o.get("name", "")) \
                                        .props("dense outlined").classes("w-40")
                                    addr = ui.input("Adresse", value=o.get("address", "")) \
                                        .props("dense outlined").classes("flex-grow min-w-[200px]")
                                    lat = ui.number("Breite", value=o.get("lat"), format="%.6f") \
                                        .props("dense outlined").classes("w-32")
                                    lon = ui.number("Länge", value=o.get("lon"), format="%.6f") \
                                        .props("dense outlined").classes("w-32")
                                    rad = ui.number("Radius m", value=o.get("radius_m", 150),
                                                    step=10).props("dense outlined").classes("w-24")

                                    def _upd(idx=i, nmf=nm, af=addr, laf=lat, lof=lon, raf=rad):
                                        orte[idx].update({
                                            "name": (nmf.value or "").strip(), "address": af.value or "",
                                            "lat": laf.value, "lon": lof.value,
                                            "radius_m": int(raf.value or 150)})
                                        data.save_config()
                                    for f in (nm, addr, lat, lon, rad):
                                        f.on("blur", lambda e, fn=_upd: fn())

                                    def _geo(idx=i, af=addr, laf=lat, lof=lon):
                                        r = geocode(af.value or "")
                                        if not r:
                                            ui.notify("Adresse nicht gefunden.", type="negative"); return
                                        laf.value, lof.value = r
                                        orte[idx]["lat"], orte[idx]["lon"] = r
                                        orte[idx]["address"] = af.value or ""
                                        data.save_config()
                                        ui.notify(f"Koordinaten: {r[0]:.5f}, {r[1]:.5f}", type="positive")
                                    ui.button(icon="search", on_click=_geo) \
                                        .props("flat dense round").tooltip("Koordinaten suchen")

                                    def _del(idx=i):
                                        orte.pop(idx); data.save_config(); render_orte()
                                    ui.button(icon="delete", on_click=_del) \
                                        .props("flat dense round color=negative")
                render_orte()
                ui.button("Objekt hinzufügen", icon="add_location",
                          on_click=lambda: (orte.append({"name": "Neues Objekt", "address": "",
                                                         "lat": None, "lon": None, "radius_m": 150}),
                                            data.save_config(), render_orte())) \
                    .props("outline no-caps mt-1")

            with ui.tab_panel(t_smoobu):
                with ui.grid(columns=2).classes("w-full gap-3"):
                    api = ui.input("API-Key (leer = unverändert)", password=True,
                                   placeholder="•••• unverändert").props("outlined dense").classes("w-full")
                    channel = ui.input("Airbnb-Kanalname (steuerfrei)",
                                       value=CFG.get("airbnb_channel_name", "Airbnb")).props("outlined dense").classes("w-full")

            with ui.tab_panel(t_mail):
                with ui.grid(columns=2).classes("w-full gap-3"):
                    m_from = ui.input("Absender (Gmail-Adresse)", value=ec.get("absender", "")).props("outlined dense").classes("w-full")
                    m_pw = ui.input("Gmail App-Passwort (leer = unverändert)", password=True,
                                    placeholder="•••• unverändert").props("outlined dense").classes("w-full")
                    m_to = ui.input("Empfänger (fest)", value=ec.get("empfaenger", "")).props("outlined dense").classes("w-full")
                    m_cc = ui.input("Cc (optional)", value=ec.get("cc", "")).props("outlined dense").classes("w-full")
                ui.label("Vorlage – Platzhalter: {monat} {jahr} {periode} {steuer} {umsatz} "
                         "{kassenzeichen} {name}").classes("text-xs text-gray-400 mt-2")
                m_subj = ui.input("Betreff-Vorlage",
                                  value=ec.get("betreff_vorlage") or DEFAULT_BETREFF).props("outlined dense").classes("w-full")
                m_body = ui.textarea("Text-Vorlage", value=ec.get("text_vorlage") or DEFAULT_TEXT) \
                    .classes("w-full").props("autogrow outlined")

                def test_email():
                    test_cfg = {
                        "smtp_host": ec.get("smtp_host", "smtp.gmail.com"),
                        "smtp_port": ec.get("smtp_port", 587),
                        "absender": (m_from.value or "").strip(),
                        "empfaenger": (m_to.value or "").strip(),
                        "cc": (m_cc.value or "").strip(),
                        "app_password": (m_pw.value or "").strip() or ec.get("app_password", ""),
                    }
                    try:
                        to = mailer.send_test(test_cfg)
                        ui.notify(f"Test-E-Mail an {to} gesendet ✓", type="positive", timeout=8000)
                    except mailer.MailError as ex:
                        ui.notify(f"Test fehlgeschlagen: {ex}", type="negative", timeout=12000)
                with ui.row().classes("items-center gap-2 mt-1"):
                    ui.button("Test-E-Mail senden", icon="send", on_click=test_email).props("outline no-caps")
                    ui.label("kurze Test-Mail an den Empfänger (ohne Anhang, ohne Ablage)") \
                        .classes("text-xs text-gray-400")

                ui.separator().classes("my-2")
                nb = CFG.setdefault("notify_email", {})
                ui.label("Benachrichtigungen an Mitarbeiter (Reinigungs-Tausch, Schäden). "
                         "Eigenes Gmail-Konto als Absender, z. B. d.steinhauss@gmail.com "
                         "(Gmail: 2FA + App-Passwort nötig). Leer = Absender oben nutzen.") \
                    .classes("text-sm text-gray-500")
                with ui.grid(columns=2).classes("w-full gap-3"):
                    n_from = ui.input("Absender Benachrichtigungen (Gmail)",
                                      value=nb.get("absender", "")).props("outlined dense").classes("w-full")
                    n_pw = ui.input("App-Passwort (leer = unverändert)", password=True,
                                    placeholder="•••• unverändert").props("outlined dense").classes("w-full")

                def test_notify():
                    to = _user_email(_cur_user()) or (n_from.value or "").strip()
                    tc = dict(CFG)
                    tc["notify_email"] = {"absender": (n_from.value or "").strip(),
                                          "app_password": (n_pw.value or "").strip() or nb.get("app_password", "")}
                    try:
                        mailer.send_notify(tc, to, "LIVARO – Test Benachrichtigung",
                                           "Dies ist eine Test-Benachrichtigung der LIVARO-App.")
                        ui.notify(f"Test-Benachrichtigung an {to} gesendet ✓", type="positive", timeout=8000)
                    except mailer.MailError as ex:
                        ui.notify(f"Test fehlgeschlagen: {ex}", type="negative", timeout=12000)
                with ui.row().classes("items-center gap-2 mt-1"):
                    ui.button("Test-Benachrichtigung", icon="send", on_click=test_notify).props("outline no-caps")
                    ui.label("Test-Mail an deine eigene E-Mail-Adresse").classes("text-xs text-gray-400")

        def save():
            for key in inputs:
                betr[key] = inputs[key].value or ""
            v = sig_x.value
            CFG["unterschrift_x"] = int(v) if v == int(v) else v
            CFG["steuersatz"] = round((steuer_pct.value or 6) / 100, 4)
            CFG["archiv_spiegel"] = spiegel.value or ""
            CFG["reinigung_ordner"] = reinigung_ordner.value or ""
            CFG["belege_ordner"] = belege_ordner.value or ""
            CFG["archiv_webdav"] = {}   # Ablage über Ordner, nicht Nextcloud/WebDAV
            if (channel.value or "").strip():
                CFG["airbnb_channel_name"] = channel.value.strip()
            if (api.value or "").strip():
                CFG["smoobu_api_key"] = api.value.strip()
                data.clear_cache()
            # E-Mail
            ec.setdefault("smtp_host", "smtp.gmail.com")
            ec.setdefault("smtp_port", 587)
            ec["absender"] = (m_from.value or "").strip()
            ec["empfaenger"] = (m_to.value or "").strip()
            ec["cc"] = (m_cc.value or "").strip()
            ec["betreff_vorlage"] = m_subj.value or ""
            ec["text_vorlage"] = m_body.value or ""
            if (m_pw.value or "").strip():
                ec["app_password"] = m_pw.value.strip()
            CFG["email"] = ec
            # Benachrichtigungs-Absender
            nb.setdefault("smtp_host", "smtp.gmail.com")
            nb.setdefault("smtp_port", 587)
            nb["absender"] = (n_from.value or "").strip()
            if (n_pw.value or "").strip():
                nb["app_password"] = n_pw.value.strip()
            CFG["notify_email"] = nb
            data.save_config()
            ui.notify("Einstellungen gespeichert", type="positive")
            dialog.close()

        with ui.row().classes("w-full justify-end mt-3"):
            ui.button("Abbrechen", on_click=dialog.close).props("flat")
            ui.button("Speichern", on_click=save).props("unelevated")
    dialog.open()


# ---------------------------------------------------------------- Archiv
def open_archive():
    all_ok, results = archive.verify()
    status_by_seq = {res["seq"]: res for res in results}
    entries = list(reversed(archive.list_entries()))  # neueste zuerst
    with ui.dialog() as dialog, ui.card().classes("w-[820px] max-w-full"):
        with ui.row().classes("w-full items-center"):
            ui.label("📚 Archiv – revisionssicher abgelegte Anmeldungen").classes("text-xl font-bold")
            ui.space()
            badge = "✓ Integrität geprüft" if all_ok else "⚠️ Integrität verletzt!"
            ui.label(badge).classes("text-sm " + ("text-green-700" if all_ok else "text-red-700"))
        if not entries:
            ui.label("Noch keine Dokumente abgelegt.").classes("text-gray-500")
        for e in entries:
            res = status_by_seq.get(e["seq"], {"ok": True, "issues": []})
            with ui.card().classes("w-full p-3"):
                with ui.row().classes("w-full items-center gap-3"):
                    ok_icon = "✅" if res["ok"] else "❌"
                    ui.label(f"{ok_icon} {e['period']} · Revision {e['revision']}").classes("font-semibold")
                    ui.label(e["ts"].replace("T", " ")).classes("text-xs text-gray-500")
                    ui.label(f"Steuer {data.euro(e['values'].get('beherbergungssteuer', 0))} €") \
                        .classes("text-xs")
                    ui.space()

                    def _dl(entry=e):
                        try:
                            ui.download.content(archive.read_pdf(entry["file"]),
                                                os.path.basename(entry["file"]),
                                                media_type="application/pdf")
                        except FileNotFoundError:
                            ui.notify("Datei fehlt im Archiv!", type="negative")
                    ui.button("PDF", on_click=_dl).props("flat dense")
                ui.label(f"SHA-256: {e['sha256']}").classes("text-xs text-gray-400 font-mono")
                if not res["ok"]:
                    ui.label("⚠️ " + "; ".join(res["issues"])).classes("text-xs text-red-700")
        with ui.row().classes("w-full justify-between items-center"):
            def do_mirror_all():
                if not archive.has_mirror(CFG):
                    ui.notify("Kein Spiegel gesetzt (Einstellungen).", type="warning")
                    return
                try:
                    n = archive.mirror_all(CFG)
                    ui.notify(f"{n} Dokument(e) nach {archive.mirror_label(CFG)} gespiegelt.",
                              type="positive")
                except Exception as ex:
                    ui.notify(f"Spiegelung fehlgeschlagen: {ex}", type="negative", timeout=9000)
            if archive.has_mirror(CFG):
                ui.button(f"🔁 Alles nach {archive.mirror_label(CFG)} spiegeln",
                          on_click=do_mirror_all).props("flat")
            else:
                ui.label("Kein externer Spiegel gesetzt (→ Einstellungen)").classes("text-xs text-gray-400")
            ui.button("Schließen", on_click=dialog.close).props("flat")
    dialog.open()


# ---------------------------------------------------------------- Ergebnis
def _kpi(container, label, value, icon="analytics", accent=False):
    with container:
        cls = "p-4 rounded-xl shadow-sm border " + \
            ("border-[#C8A96E]/40 bg-[#faf7f0]" if accent else "border-slate-100")
        with ui.card().classes(cls):
            with ui.row().classes("items-center gap-2 no-wrap"):
                ui.icon(icon).classes("text-xl " + ("text-[#C8A96E]" if accent else "text-primary"))
                ui.label(label).classes("text-xs text-gray-500")
            ui.label(value).classes("text-2xl font-bold mt-1 text-primary")


def render_result(container, result):
    container.clear()
    r = result
    with container:
        grid = ui.grid(columns=4).classes("w-full gap-4 max-md:grid-cols-2")
        _kpi(grid, "ÜN insgesamt", str(r["uebernachtungen_insgesamt"]), icon="hotel")
        _kpi(grid, "verbleibende ÜN", str(r["uebernachtungen_verbleibend"]), icon="nights_stay")
        _kpi(grid, "steuerpfl. Umsatz", data.euro(r["umsatz_steuerpflichtig"]) + " €", icon="payments")
        _kpi(grid, "Beherbergungssteuer", data.euro(r["beherbergungssteuer"]) + " €",
             icon="account_balance", accent=True)

        ui.label(f"Airbnb-ÜN (berechnet): {r['uebernachtungen_airbnb']} – fließen nicht in die "
                 f"Steuer ein (Airbnb meldet selbst). Basis = Preis ohne durchlaufende "
                 f"Übernachtungssteuer.").classes("text-xs text-gray-500")

        # Buchungstabelle
        cols = [
            {"name": "departure", "label": "Abreise", "field": "departure", "sortable": True, "align": "left"},
            {"name": "guest", "label": "Gast", "field": "guest", "align": "left"},
            {"name": "apartment", "label": "Apartment", "field": "apartment", "align": "left"},
            {"name": "channel", "label": "Kanal", "field": "channel", "align": "left"},
            {"name": "arrival", "label": "Anreise", "field": "arrival", "align": "left"},
            {"name": "nights", "label": "Nächte", "field": "nights", "align": "right"},
            {"name": "persons", "label": "Pers.", "field": "persons", "align": "right"},
            {"name": "overnights", "label": "ÜN", "field": "overnights", "align": "right"},
            {"name": "price", "label": "Gesamtpreis €", "field": "price", "align": "right"},
            {"name": "steuer", "label": "Steuer €", "field": "steuer", "align": "right"},
        ]
        rows = []
        for x in r["rows"]:
            rows.append({
                "departure": x["departure"], "guest": x["guest"],
                "apartment": x["apartment"], "channel": x["channel"],
                "arrival": x["arrival"], "nights": x["nights"],
                "persons": x["persons"], "overnights": x["overnights"],
                "price": data.euro(x["price"]),
                "steuer": "—" if x["is_airbnb"] else data.euro(round(x["base"] * r["steuersatz"], 2)),
            })
        with ui.card().classes("w-full"):
            ui.label(f"Buchungen ({len(rows)}) – Abreise im Monat, bereits stattgefunden").classes("font-medium")
            ui.table(columns=cols, rows=rows, row_key="departure").classes("w-full").props("dense flat")
            with ui.row().classes("gap-6 text-sm mt-1"):
                ui.label(f"Steuerpflichtig (Booking/Website/Direkt): "
                         f"{r['uebernachtungen_verbleibend']} ÜN · {data.euro(r['umsatz_verbleibend'])} € · "
                         f"Steuer {data.euro(r['beherbergungssteuer'])} €").classes("font-semibold")
                ui.label(f"Airbnb: {r['uebernachtungen_airbnb']} ÜN (keine Steuer)").classes("text-gray-500")

        # PDF erzeugen (gemeinsame Logik)
        def build_pdf():
            if pdf_form is None:
                ui.notify("PDF benötigt PyMuPDF (pip install -r requirements.txt)", type="negative")
                return None
            if not os.path.exists(pdf_form.TEMPLATE):
                ui.notify("Blanko-Vorlage fehlt – siehe templates/README.md", type="negative")
                return None
            return pdf_form.render_pdf(r, CFG, datum=date.today().strftime("%d.%m.%Y"))

        def _values():
            return {k: r[k] for k in (
                "uebernachtungen_insgesamt", "uebernachtungen_airbnb",
                "uebernachtungen_verbleibend", "umsatz_verbleibend",
                "umsatz_steuerbefreit", "umsatz_steuerpflichtig", "beherbergungssteuer")}

        period = f"{r['year']}-{r['month']:02d}"
        fname = f"Beherbergungssteuer_{period}.pdf"

        def _archive_and_mirror(pdf):
            """PDF ablegen + (falls konfiguriert) spiegeln. Gibt (entry, zusatz_text)."""
            entry = archive.archive_pdf(pdf, period, _values())
            extra = ""
            if archive.has_mirror(CFG):
                try:
                    archive.mirror_entry(entry, CFG)
                    extra = f" · in {archive.mirror_label(CFG)} gesichert"
                except Exception as ex:  # Spiegel-Fehler darf lokale Ablage nicht kippen
                    ui.notify(f"Lokal abgelegt, aber Spiegelung fehlgeschlagen: {ex}",
                              type="warning", timeout=9000)
            return entry, extra

        def festschreiben():
            pdf = build_pdf()
            if pdf is None:
                return
            entry, extra = _archive_and_mirror(pdf)
            ui.download.content(pdf, f"Beherbergungssteuer_{period}_v{entry['revision']}.pdf",
                                media_type="application/pdf")
            ui.notify(f"Revisionssicher abgelegt: Revision {entry['revision']} · "
                      f"SHA-256 {entry['sha256'][:12]}…{extra}", type="positive", timeout=7000)

        def vorschau():
            pdf = build_pdf()
            if pdf is not None:
                ui.download.content(pdf, fname, media_type="application/pdf")

        def open_send():
            ec = CFG.get("email", {})
            if not (ec.get("empfaenger") and ec.get("absender") and ec.get("app_password")):
                ui.notify("E-Mail noch nicht eingerichtet – Absender, App-Passwort und "
                          "Empfänger in den Einstellungen setzen.", type="warning", timeout=9000)
                return
            ctx = _mail_context(r)
            with ui.dialog() as dlg, ui.card().classes("w-[720px] max-w-full"):
                ui.label("✉️ Anmeldung per E-Mail senden").classes("text-xl font-bold")
                cc = f" · Cc: {ec['cc']}" if ec.get("cc") else ""
                ui.label(f"An: {ec['empfaenger']}{cc}   (Absender: {ec['absender']})") \
                    .classes("text-sm text-gray-600")
                subj = ui.input("Betreff", value=mailer.render(ec.get("betreff_vorlage") or DEFAULT_BETREFF, ctx)) \
                    .classes("w-full")
                body = ui.textarea("Text", value=mailer.render(ec.get("text_vorlage") or DEFAULT_TEXT, ctx)) \
                    .classes("w-full").props("autogrow outlined")
                ui.label(f"📎 Anhang: Beherbergungssteuer_{period}_v(neu).pdf") \
                    .classes("text-xs text-gray-500")

                def do_send():
                    pdf = build_pdf()
                    if pdf is None:
                        return
                    entry, extra = _archive_and_mirror(pdf)
                    try:
                        mailer.send_form(
                            CFG, pdf,
                            f"Beherbergungssteuer_{period}_v{entry['revision']}.pdf",
                            ctx, subject=subj.value, body=body.value)
                    except mailer.MailError as ex:
                        ui.notify(f"Abgelegt (Rev. {entry['revision']}), aber Versand "
                                  f"fehlgeschlagen: {ex}", type="negative", timeout=11000)
                        dlg.close()
                        return
                    ui.notify(f"✅ Gesendet an {ec['empfaenger']} · abgelegt als "
                              f"Revision {entry['revision']}{extra}", type="positive", timeout=8000)
                    dlg.close()

                with ui.row().classes("w-full justify-end"):
                    ui.button("Abbrechen", on_click=dlg.close).props("flat")
                    ui.button("Senden", on_click=do_send).props("unelevated")
            dlg.open()

        with ui.row().classes("gap-2 items-center flex-wrap"):
            ui.button("📥 Erzeugen & ablegen", on_click=festschreiben).props("unelevated")
            ui.button("✉️ Ablegen & per E-Mail senden", on_click=open_send).props("unelevated")
            ui.button("👁 Nur Vorschau", on_click=vorschau).props("flat")
            existing = sum(1 for e in archive.list_entries() if e["period"] == period)
            if existing:
                ui.label(f"⚠️ Für {period} bereits {existing} Ablage(n) – Erzeugen legt "
                         "eine neue Revision an.").classes("text-xs text-amber-700")


# ---------------------------------------------------------------- Reinigung
def _apts():
    return dict(_load_apartments())


def _photo_mirror():
    return CFG.get("reinigung_ordner") or None


def _due_today():
    from datetime import date, timedelta
    today = date.today().isoformat()
    d_from = (date.today() - timedelta(days=92)).isoformat()
    try:
        bookings = data._reservations(d_from, today)
    except Exception:
        return []
    out = {}
    for b in bookings:
        if b.get("is-blocked-booking") or b.get("type") == "cancellation":
            continue
        if b.get("departure") == today:
            ap = b.get("apartment") or {}
            if ap.get("id"):
                out[ap["id"]] = ap.get("name")
    return list(out.items())


async def _read_upload(e):
    """Upload-Bytes + Dateiname lesen – kompatibel zu NiceGUI 3.14 (e.file, async
    read()) und der älteren API (e.content.read(), e.name)."""
    f = getattr(e, "file", None)
    if f is not None:                       # NiceGUI 3.14+
        data = await f.read()
        name = getattr(f, "name", None) or "foto.jpg"
    else:                                   # NiceGUI 3.6.x
        data = e.content.read()
        name = getattr(e, "name", None) or "foto.jpg"
    return data, name


def _save_bytes(data, name, kind):
    ext = (name.rsplit(".", 1)[-1] if "." in name else "jpg").lower()[:4] or "jpg"
    return housekeeping.save_photo(kind, data, ext=ext, mirror_dir=_photo_mirror())


def _photo_button(label, kind, on_saved, icon="photo_camera"):
    """Sauberer Foto-Button auf Basis des ECHTEN Uploaders (nativer Tap öffnet den
    Datei-/Kameradialog – wichtig für iOS Safari, das Server-getriggerte pickFiles()
    blockt). Die Quasar-Chrome (Byte/Prozent, Dateiliste) wird per CSS (.hk-upload)
    ausgeblendet. on_saved(rel) nach dem Hochladen."""
    async def handle(e):
        try:
            data, name = await _read_upload(e)
            rel = _save_bytes(data, name, kind)
        except Exception as ex:
            ui.notify(f"Foto konnte nicht gespeichert werden: {ex}", type="negative")
            return
        ui.notify("Foto gespeichert ✓", type="positive")
        on_saved(rel)
    ui.upload(auto_upload=True, on_upload=handle, label=label) \
        .props('accept="image/*"').classes("hk-upload w-[135px]")


def _open_photo(src):
    """Foto im Vollbild-Dialog anzeigen (Klick/Tap schließt)."""
    with ui.dialog() as dlg:
        with ui.card().classes("p-1 bg-white").style("width:90vw; max-width:820px"):
            ui.image(src).classes("w-full cursor-zoom-out").style("max-height:82vh") \
                .props("fit=contain").on("click", dlg.close)
    dlg.open()


def _photo_thumb(src, size="w-16 h-16"):
    """Anklickbares Vorschaubild (öffnet Vollbild)."""
    ui.image(src).classes(
        f"{size} object-cover rounded-lg cursor-pointer ring-1 ring-slate-200 "
        "hover:ring-primary transition") \
        .on("click", lambda s=src: _open_photo(s))


def _run_ist(run_id, task_id):
    for r in housekeeping._read(housekeeping.CLEANINGS, []):
        if r["id"] == run_id:
            return r["tasks"].get(task_id, {}).get("ist_photo")
    return None


def _notify_damage(d):
    ec = CFG.get("email", {})
    if not (ec.get("absender") and ec.get("app_password")):
        return
    to = CFG.get("benachrichtigung_email") or ec.get("absender")
    body = (f"Neue Schadensmeldung\n\nApartment: {d['apartment_name']}\n"
            f"Raum: {d['room']}\nDringlichkeit: {d['urgency']}\n"
            f"Gemeldet von: {d['reporter']}\nZeit: {d['ts']}\n\n"
            f"Beschreibung:\n{d['desc']}\n")
    try:
        mailer.send_plain(CFG, to,
                          f"[LIVARO] Schaden {d['apartment_name']} ({d['urgency']})", body)
    except mailer.MailError:
        pass


def open_damage_dialog(apt_id, apt_name, reporter, on_saved=None):
    photo = {"rel": None}
    with ui.dialog() as dlg, ui.card().classes("w-[460px] max-w-full gap-2"):
        ui.label(f"Schaden melden – {apt_name}").classes("text-lg font-bold")
        room = ui.input("Raum/Bereich").props("dense outlined").classes("w-full")
        desc = ui.textarea("Was ist beschädigt?").props("outlined").classes("w-full")
        urg = ui.select(["niedrig", "mittel", "hoch"], value="mittel",
                        label="Dringlichkeit").props("dense outlined").classes("w-full")
        thumb = ui.row()

        def saved(rel):
            photo["rel"] = rel
            thumb.clear()
            with thumb:
                _photo_thumb(f"/media/{rel}", "w-24 h-24")
        with ui.row().classes("items-center gap-2"):
            _photo_button("Foto (optional)", "damage", saved)

        def save():
            if not (desc.value or "").strip():
                ui.notify("Bitte Beschreibung angeben.", type="warning"); return
            d = housekeeping.add_damage(apt_id, apt_name, (room.value or "").strip(),
                                        desc.value.strip(), urg.value, photo["rel"], reporter)
            _notify_damage(d)
            ui.notify("Schaden gemeldet – Danke!", type="positive")
            dlg.close()
            if on_saved:
                on_saved()
        with ui.row().classes("w-full justify-end"):
            ui.button("Abbrechen", on_click=dlg.close).props("flat")
            ui.button("Melden", on_click=save).props("unelevated")
    dlg.open()


def _hk_header(title, subtitle):
    with ui.row().classes("w-full items-center gap-3"):
        ui.icon("cleaning_services").classes("text-3xl text-primary")
        with ui.column().classes("gap-0"):
            ui.label(title).classes("text-2xl font-bold text-slate-800 leading-tight")
            ui.label(subtitle).classes("text-sm text-gray-500")


def render_reinigung(activate=None):
    if _is_admin():
        reinigung_admin()
    else:
        reinigung_putzkraft(activate)


def reinigung_putzkraft(activate=None):
    user = _cur_user()
    _hk_header("Reinigung", "Checkliste, Fotonachweis, Schäden & Bestand")
    apts = _apts()
    # Aus einer Buchung vorausgewähltes Apartment (Workflow-Sprung) übernehmen
    pre = _PENDING_REINIGUNG.pop("apt", None)
    ret = _PENDING_REINIGUNG.pop("return", None)
    bkid = _PENDING_REINIGUNG.pop("booking", None)
    state = {"apt": pre, "return": ret, "booking": bkid}
    body = ui.column().classes("w-full gap-4")

    def open_apt(aid, anm):
        state["apt"] = (aid, anm); render()

    def _task_row(run, t):
        st = run["tasks"].get(t["id"], {})
        with ui.column().classes("w-full gap-2 py-2 border-b border-slate-100"):
            cb = ui.checkbox(t["text"], value=st.get("done", False)).classes("text-base")
            cb.on_value_change(lambda e, tid=t["id"]: housekeeping.update_task(run["id"], tid, done=e.value))
            with ui.row().classes("w-full items-end gap-4 pl-9 flex-wrap"):
                if t.get("ref_photo"):
                    with ui.column().classes("items-center gap-0"):
                        _photo_thumb(f"/media/{t['ref_photo']}", "w-20 h-20")
                        ui.label("Soll").classes("text-xs text-gray-400")
                istc = ui.column().classes("items-center gap-1")

                def refresh_ist(col=istc, tid=t["id"], run_id=run["id"]):
                    col.clear()
                    with col:
                        p = _run_ist(run_id, tid)
                        if p:
                            _photo_thumb(f"/media/{p}", "w-20 h-20")
                            with ui.row().classes("items-center gap-1"):
                                ui.icon("check_circle").classes("text-green-600 text-sm")
                                ui.button("ändern", on_click=lambda c=col, td=tid, r=run_id:
                                          (housekeeping.update_task(r, td, ist_photo=""),
                                           refresh_ist(c, td, r))).props("flat dense no-caps size=sm")
                        else:
                            def saved(rel, c=col, td=tid, r=run_id):
                                housekeeping.update_task(r, td, ist_photo=rel)
                                refresh_ist(c, td, r)
                            _photo_button("Ist-Foto", "ist", saved)
                            ui.label("Ist").classes("text-xs text-gray-400")
                refresh_ist()

    def _restock_card(aid, anm):
        with ui.card().classes("w-full"):
            with ui.expansion("Verbrauch / Wäsche nachbestellen", icon="inventory_2").classes("w-full"):
                for it in housekeeping.get_inventory(aid):
                    with ui.row().classes("w-full items-center gap-2 no-wrap"):
                        ui.label(it["name"]).classes("flex-grow")
                        qty = ui.input("Menge", value="1").props("dense outlined").classes("w-24")

                        def melden(name=it["name"], kat=it["kategorie"], q=qty):
                            housekeeping.add_restock(aid, anm, name, (q.value or "1").strip(), kat, user)
                            ui.notify(f"{name} zum Nachkauf gemeldet.", type="positive")
                        ui.button("melden", icon="add_shopping_cart",
                                  on_click=melden).props("flat dense no-caps")

    def render():
        body.clear()
        with body:
            if state["apt"] is None:
                with ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100 gap-2"):
                    due = _due_today()
                    if due:
                        ui.label("Heute fällig (nach Abreise):").classes("font-medium")
                        with ui.row().classes("gap-2 flex-wrap"):
                            for aid, anm in due:
                                ui.button(anm, icon="event_available",
                                          on_click=lambda a=aid, n=anm: open_apt(a, n)) \
                                    .props("unelevated no-caps")
                    ui.label("Apartment wählen:").classes("text-sm text-gray-500 mt-1")
                    with ui.row().classes("items-end gap-2"):
                        s = ui.select(apts, label="Apartment").props("outlined dense").classes("min-w-[240px]")
                        ui.button("Reinigung starten", icon="play_arrow",
                                  on_click=lambda: (open_apt(s.value, apts.get(s.value)) if s.value
                                                    else ui.notify("Bitte Apartment wählen.", type="warning"))) \
                            .props("unelevated no-caps")
                return
            aid, anm = state["apt"]
            run = housekeeping.start_run(aid, anm, user)
            cl = housekeeping.get_checklist(aid)
            with ui.row().classes("w-full items-center gap-2"):
                ui.button(icon="arrow_back", on_click=lambda: (state.update(apt=None), render())).props("flat round")
                ui.label(anm).classes("text-xl font-bold")
                ui.space()
                ui.button("Schaden melden", icon="report_problem",
                          on_click=lambda: open_damage_dialog(aid, anm, user)) \
                    .props("outline no-caps color=negative")
            for room in cl["rooms"]:
                with ui.card().classes("w-full"):
                    ui.label(room["name"]).classes("font-medium")
                    for t in room["tasks"]:
                        _task_row(run, t)
            _restock_card(aid, anm)

            def finish():
                housekeeping.finish_run(run["id"])
                if state.get("booking"):
                    bookings.mark_checklist_done(state["booking"], user)
                ui.notify("Durchgang abgeschlossen ✓", type="positive")
                # Kam man aus einer Buchung: zurück zu Buchungen (dort Arbeitszeit stoppen)
                if state.get("return") == "buchungen" and activate:
                    activate("buchungen")
                else:
                    state.update(apt=None); render()
            ui.button("Durchgang abschließen", icon="check_circle", on_click=finish) \
                .props("unelevated no-caps")
    render()


def reinigung_admin():
    _hk_header("Reinigung", "Durchgänge, Schäden, Einkaufsliste & Konfiguration")
    apts = _apts()
    with ui.tabs().props("dense no-caps align=left").classes("w-full") as tabs:
        t_runs = ui.tab("Durchgänge", icon="fact_check")
        t_dmg = ui.tab("Schäden", icon="report_problem")
        t_shop = ui.tab("Einkaufsliste", icon="shopping_cart")
        t_cfg = ui.tab("Konfiguration", icon="tune")
    with ui.tab_panels(tabs, value=t_runs).classes("w-full"):
        with ui.tab_panel(t_runs):
            _admin_runs()
        with ui.tab_panel(t_dmg):
            _admin_damages()
        with ui.tab_panel(t_shop):
            _admin_shopping()
        with ui.tab_panel(t_cfg):
            _admin_config(apts)


def _admin_runs():
    runs = housekeeping.list_runs()
    if not runs:
        ui.label("Noch keine Durchgänge.").classes("text-gray-500"); return
    for r in runs:
        cl = housekeeping.get_checklist(r["apartment_id"])
        total = sum(len(room["tasks"]) for room in cl["rooms"])
        done = sum(1 for v in r["tasks"].values() if v.get("done"))
        status = "abgeschlossen" if r.get("finished") else "läuft"
        head = f"{r['apartment_name']} · {r['user']} · {_d(r['started'])} · {done}/{total} Aufgaben · {status}"
        with ui.expansion(head, icon="cleaning_services").classes("w-full"):
            for room in cl["rooms"]:
                ui.label(room["name"]).classes("font-medium text-sm mt-1")
                for t in room["tasks"]:
                    st = r["tasks"].get(t["id"], {})
                    with ui.row().classes("w-full items-center gap-3 no-wrap"):
                        ui.icon("check_circle" if st.get("done") else "radio_button_unchecked") \
                            .classes("text-green-600" if st.get("done") else "text-gray-300")
                        ui.label(t["text"]).classes("flex-grow text-sm")
                        if t.get("ref_photo"):
                            _photo_thumb(f"/media/{t['ref_photo']}", "w-14 h-14")
                        if st.get("ist_photo"):
                            _photo_thumb(f"/media/{st['ist_photo']}", "w-14 h-14")


def _admin_damages():
    dmg = housekeeping.list_damages()
    if not dmg:
        ui.label("Keine Schadensmeldungen.").classes("text-gray-500"); return
    for d in dmg:
        color = {"hoch": "text-red-700", "mittel": "text-amber-700"}.get(d["urgency"], "text-gray-600")
        with ui.card().classes("w-full"):
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.icon("report_problem").classes(color)
                ui.label(f"{d['apartment_name']} · {d['room']}").classes("font-semibold")
                ui.label(d["urgency"]).classes(f"text-xs {color}")
                ui.label(f"{_d(d['ts'])} · {d['reporter']}").classes("text-xs text-gray-500")
                ui.space()
                if d["status"] == "offen":
                    ui.button("erledigt", icon="check",
                              on_click=lambda i=d["id"]: (housekeeping.set_damage_status(i, "erledigt"),
                                                          render_reinigung_refresh())) \
                        .props("flat dense no-caps")
                else:
                    ui.label("erledigt").classes("text-xs text-green-700")
            ui.label(d["desc"]).classes("text-sm")
            if d.get("photo"):
                _photo_thumb(f"/media/{d['photo']}", "w-40 h-40")


def _admin_shopping():
    items = housekeeping.list_restock(only_open=True)
    if not items:
        ui.label("Einkaufsliste ist leer.").classes("text-gray-500"); return
    for r in items:
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            ui.icon("shopping_cart").classes("text-primary")
            ui.label(f"{r['menge']}× {r['item']}").classes("font-medium")
            ui.label(f"({r['apartment_name']}, {r['kategorie']})").classes("text-xs text-gray-500")
            ui.label(f"{_d(r['ts'])} · {r['reporter']}").classes("text-xs text-gray-400")
            ui.space()
            ui.button("gekauft", icon="check",
                      on_click=lambda i=r["id"]: (housekeeping.set_restock_status(i, "erledigt"),
                                                  render_reinigung_refresh())) \
                .props("flat dense no-caps")


def render_reinigung_refresh():
    ui.navigate.to("/")   # einfacher Refresh nach Statusänderung


def _admin_config(apts):
    ui.label("Checkliste & Bestand je Apartment. Soll-Foto pro Aufgabe hochladen.") \
        .classes("text-sm text-gray-500")
    sel = ui.select(apts, label="Apartment",
                    value=(next(iter(apts), None))).props("outlined dense").classes("min-w-[240px]")
    box = ui.column().classes("w-full gap-2")

    def render_cfg():
        box.clear()
        aid = sel.value
        if not aid:
            return
        cl = housekeeping.get_checklist(aid)
        inv = housekeeping.get_inventory(aid)
        room_inputs = []   # (room_dict, input)
        task_inputs = []   # (task_dict, input)
        inv_inputs = []    # (item_dict, name_input, kat_select)

        def collect():
            """Aktuelle Feldwerte in die Datenstrukturen übernehmen."""
            for room, f in room_inputs:
                room["name"] = f.value
            for t, f in task_inputs:
                t["text"] = f.value
            for it, nf, kf in inv_inputs:
                it["name"] = nf.value
                it["kategorie"] = kf.value

        def persist(notify=True):
            collect()
            housekeeping.save_checklist(aid, cl)
            housekeeping.save_inventory(aid, inv)
            if notify:
                ui.notify("Konfiguration gespeichert ✓", type="positive")

        with box:
            with ui.row().classes("w-full items-center gap-2"):
                ui.label("Räume & Aufgaben").classes("font-medium")
                ui.space()
                ui.button("Speichern", icon="save", on_click=lambda: persist()) \
                    .props("unelevated no-caps")
            for ri, room in enumerate(cl["rooms"]):
                with ui.card().classes("w-full gap-1"):
                    with ui.row().classes("w-full items-center gap-2"):
                        rn = ui.input("Raum", value=room["name"]).props("dense outlined").classes("w-56")
                        room_inputs.append((room, rn))
                        ui.space()
                        ui.button(icon="delete", on_click=lambda i=ri: (collect(), cl["rooms"].pop(i), housekeeping.save_checklist(aid, cl), render_cfg())) \
                            .props("flat dense round color=negative")
                    for ti, t in enumerate(room["tasks"]):
                        with ui.row().classes("w-full items-center gap-2 no-wrap"):
                            tt = ui.input("Aufgabe", value=t["text"]).props("dense outlined").classes("flex-grow")
                            task_inputs.append((t, tt))
                            if t.get("ref_photo"):
                                _photo_thumb(f"/media/{t['ref_photo']}", "w-12 h-12")

                            def ref_saved(rel, tid=t["id"]):
                                collect()
                                housekeeping.save_checklist(aid, cl)
                                housekeeping.set_task_ref_photo(aid, tid, rel)
                                render_cfg()
                            _photo_button("Soll-Foto", "ref", ref_saved, icon="add_a_photo")
                            ui.button(icon="delete", on_click=lambda i=ti, rm=room: (collect(), rm["tasks"].pop(i), housekeeping.save_checklist(aid, cl), render_cfg())) \
                                .props("flat dense round color=negative")
                    ui.button("Aufgabe hinzufügen", icon="add",
                              on_click=lambda rm=room: (collect(), rm["tasks"].append({"id": housekeeping._uid(), "text": "Neue Aufgabe", "ref_photo": None}), housekeeping.save_checklist(aid, cl), render_cfg())) \
                        .props("flat dense no-caps")
            ui.button("Raum hinzufügen", icon="add_home",
                      on_click=lambda: (collect(), cl["rooms"].append({"name": "Neuer Raum", "tasks": []}), housekeeping.save_checklist(aid, cl), render_cfg())) \
                .props("outline no-caps")

            ui.separator()
            ui.label("Bestandsliste (Verbrauch/Wäsche)").classes("font-medium")
            for ii, it in enumerate(inv):
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    nm = ui.input("Artikel", value=it["name"]).props("dense outlined").classes("flex-grow")
                    ka = ui.select({"verbrauch": "Verbrauch", "waesche": "Wäsche"},
                                   value=it.get("kategorie", "verbrauch")).props("dense outlined").classes("w-40")
                    inv_inputs.append((it, nm, ka))
                    ui.button(icon="delete", on_click=lambda i=ii: (collect(), inv.pop(i), housekeeping.save_inventory(aid, inv), render_cfg())) \
                        .props("flat dense round color=negative")
            ui.button("Artikel hinzufügen", icon="add",
                      on_click=lambda: (collect(), inv.append({"id": housekeeping._uid(), "name": "Neuer Artikel", "kategorie": "verbrauch"}), housekeeping.save_inventory(aid, inv), render_cfg())) \
                .props("flat dense no-caps")

            ui.separator()
            with ui.row().classes("w-full justify-end"):
                ui.button("Konfiguration speichern", icon="save", on_click=lambda: persist()) \
                    .props("unelevated no-caps")

    sel.on_value_change(lambda e: render_cfg())
    render_cfg()


# ---------------------------------------------------------------- Buchungen
_PENDING_REINIGUNG = {}   # {"apt": (id, name)} – Workflow-Sprung Buchung → Checkliste


def _staff_users():
    """{username: Anzeigename} aller Mitarbeiter (Putzkräfte + Admins)."""
    return {u: (info.get("name") or u) for u, info in USERS.items()}


def _user_email(username):
    return (USERS.get(username, {}) or {}).get("email", "")


_WD = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def _dfmt(iso):
    try:
        d = date.fromisoformat(iso)
        return f"{_WD[d.weekday()]} {d.strftime('%d.%m.')}"
    except Exception:
        return iso or ""


def _persons_text(nb):
    a, c = nb.get("adults") or 0, nb.get("children") or 0
    parts = []
    if a:
        parts.append("1 Erwachsener" if a == 1 else f"{a} Erwachsene")
    if c:
        parts.append("1 Kind" if c == 1 else f"{c} Kinder")
    return " · ".join(parts) or f"{nb.get('persons', 0)} Pers."


def _events_between(d_from, d_to):
    """An-/Abreise-Ereignisse mit Datum in [d_from, d_to] (unsortiert)."""
    try:
        raw = data._reservations(d_from, d_to)
    except smoobu.SmoobuError as ex:
        ui.notify(f"Smoobu: {ex}", type="negative", timeout=8000)
        return []
    evs = []
    for b in raw:
        if not bookings.is_real(b):
            continue
        nb = bookings.normalize(b)
        try:
            nb["nights"] = (date.fromisoformat(nb["departure"])
                            - date.fromisoformat(nb["arrival"])).days
        except Exception:
            nb["nights"] = None
        if nb["arrival"] and d_from <= nb["arrival"] <= d_to:
            evs.append({**nb, "kind": "in", "date": nb["arrival"], "time": nb["checkin_time"]})
        if nb["departure"] and d_from <= nb["departure"] <= d_to:
            evs.append({**nb, "kind": "out", "date": nb["departure"], "time": nb["checkout_time"]})
    return evs


def _fetch_events(days_ahead=21, days_back=1):
    """An- und Abreise-Ereignisse aus Smoobu im Zeitfenster, chronologisch sortiert."""
    from datetime import timedelta
    today = date.today()
    evs = _events_between((today - timedelta(days=days_back)).isoformat(),
                          (today + timedelta(days=days_ahead)).isoformat())
    evs.sort(key=lambda e: (e["date"], e["time"] or "99:99", e["apartment_name"]))
    return evs


def _cleaning_jobs(days_ahead=21, days_back=1):
    """Reinigungs-Jobs: jede Abreise im Fenster + die nächste Anreise (Folgebuchung)
    derselben Wohnung – damit die Putzkraft weiß, für wie viele Personen vorzubereiten."""
    from datetime import timedelta
    today = date.today()
    d_from = (today - timedelta(days=days_back)).isoformat()
    d_to = (today + timedelta(days=days_ahead)).isoformat()
    look_to = (today + timedelta(days=days_ahead + 120)).isoformat()  # weit für Folgebuchung
    try:
        raw = data._reservations(d_from, look_to)
    except smoobu.SmoobuError as ex:
        ui.notify(f"Smoobu: {ex}", type="negative", timeout=8000)
        return []
    norm = [bookings.normalize(b) for b in raw if bookings.is_real(b)]
    by_apt = {}
    for nb in norm:
        by_apt.setdefault(nb["apartment_id"], []).append(nb)
    jobs = []
    for nb in norm:
        if not (nb["departure"] and d_from <= nb["departure"] <= d_to):
            continue
        nxt = None
        for cand in by_apt.get(nb["apartment_id"], []):
            if cand["id"] == nb["id"] or not cand["arrival"]:
                continue
            if cand["arrival"] >= nb["departure"] and (nxt is None or cand["arrival"] < nxt["arrival"]):
                nxt = cand
        jobs.append({**nb, "next": nxt})
    jobs.sort(key=lambda j: (j["departure"], j["checkout_time"] or "99:99", j["apartment_name"]))
    return jobs


def _open_checkliste(apt_id, apt_name, activate, booking_id=None):
    _PENDING_REINIGUNG["apt"] = (apt_id, apt_name)
    _PENDING_REINIGUNG["return"] = "buchungen"   # nach Abschluss zurück zu Buchungen
    _PENDING_REINIGUNG["booking"] = booking_id
    activate("reinigung")


# ------------------------------------------------------- Buchungs-/Reinigungs-Status
_STATUS = {
    "nicht_zugewiesen": ("Nicht zugewiesen", "grey-5", "person_off"),
    "zugewiesen":       ("Zugewiesen", "blue-6", "assignment_ind"),
    "in_progress":      ("In Arbeit", "green-6", "play_circle"),
    "abgeschlossen":    ("Fertig", "green-7", "check_circle"),
    "nachtragen":       ("Überfällig", "red-6", "warning"),
}


def _past_checkout(job):
    from datetime import datetime, time as _time_cls
    try:
        d = date.fromisoformat(job["departure"])
        hh, mm = (job.get("checkout_time") or "10:00").split(":")[:2]
        return datetime.now() > datetime.combine(d, _time_cls(int(hh), int(mm)))
    except Exception:
        return job.get("departure", "") < date.today().isoformat()


def _booking_status(job):
    """Status-Key gemäß Zuweisung / Arbeitszeit / Checkliste / Check-out-Zeit."""
    bid = job["id"]
    who = bookings.assignee_of(bid)
    cl_done = bookings.is_checklist_done(bid)
    entries = timetrack.entries_for_booking(bid)
    has_time = any(e.get("checkout") for e in entries)
    open_now = any(not e.get("checkout") for e in entries)
    started = bool(entries)
    if cl_done and has_time:
        return "abgeschlossen"
    if open_now:
        return "in_progress"
    if _past_checkout(job):
        return "nachtragen"
    if started:
        return "in_progress"
    if who:
        return "zugewiesen"
    return "nicht_zugewiesen"


def _status_chip(job):
    label, color, icon = _STATUS[_booking_status(job)]
    ui.chip(label, icon=icon).props(f"color={color} text-color=white dense")


def render_buchungen(activate):
    user = _cur_user()
    admin = _is_admin()
    with ui.row().classes("w-full items-center gap-3"):
        ui.icon("calendar_month").classes("text-3xl text-primary")
        with ui.column().classes("gap-0"):
            ui.label("Buchungen").classes("text-2xl font-bold text-slate-800 leading-tight")
            ui.label("Reinigungs-Übersicht & Buchungskalender") \
                .classes("text-sm text-gray-500")
        ui.space()
        ui.button(icon="refresh", on_click=lambda: (data.clear_cache(), activate("buchungen"))) \
            .props("flat round").tooltip("Aktualisieren")
    staff = _staff_users()
    with ui.tabs().props("dense no-caps align=left").classes("w-full") as tabs:
        t_clean = ui.tab("Reinigungen", icon="cleaning_services")
        t_cal = ui.tab("Kalender", icon="calendar_month")
    with ui.tab_panels(tabs, value=t_clean).classes("w-full"):
        with ui.tab_panel(t_clean):
            _render_cleaning(user, admin, staff, activate)
        with ui.tab_panel(t_cal):
            _render_calendar(user, admin, staff, activate)


_MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
           "August", "September", "Oktober", "November", "Dezember"]
_APT_HEX = ["#5E2A84", "#0F766E", "#B45309", "#BE185D", "#1D4ED8",
            "#4338CA", "#047857", "#9333EA"]


def _apt_hex(apt_id):
    """Stabile Farbe je Wohnung (nach Reihenfolge der Apartments)."""
    ids = list(_apts().keys())
    try:
        idx = ids.index(apt_id)
    except ValueError:
        idx = int(apt_id) if isinstance(apt_id, int) else 0
    return _APT_HEX[idx % len(_APT_HEX)]


def _render_calendar(user, admin, staff, activate):
    today = date.today()
    apts = _apts()
    state = {"mode": "multi", "start": today.isoformat(),
             "y": today.year, "m": today.month, "apt": next(iter(apts), None)}
    box = ui.column().classes("w-full gap-2")

    def render():
        box.clear()
        with box:
            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                mode = ui.toggle({"multi": "Alle Wohnungen", "single": "Einzeln"},
                                 value=state["mode"]).props("no-caps")
                mode.on_value_change(lambda e: (state.update(mode=e.value), render()))
                if state["mode"] == "single" and apts:
                    sel = ui.select(apts, value=state["apt"], label="Wohnung") \
                        .props("dense outlined").classes("min-w-[200px]")
                    sel.on_value_change(lambda e: (state.update(apt=e.value), render()))
            if state["mode"] == "single":
                _single_month(state, user, admin, staff, activate, render)
            else:
                _timeline(state, user, admin, staff, activate, render)
    render()


def _shift_days(state, delta, rerender):
    from datetime import timedelta
    state["start"] = (date.fromisoformat(state["start"]) + timedelta(days=delta)).isoformat()
    rerender()


def _shift_month(state, delta, rerender):
    m, y = state["m"] + delta, state["y"]
    while m < 1:
        m += 12; y -= 1
    while m > 12:
        m -= 12; y += 1
    state["y"], state["m"] = y, m
    rerender()


def _timeline(state, user, admin, staff, activate, rerender):
    """Reservierungs-Timeline: Wohnungen als Zeilen, Tage als Spalten, Buchungen als
    Balken (skaliert mit weiteren Wohnungen). Klick auf einen Balken öffnet Details."""
    from datetime import timedelta
    CELL, LABELW, NDAYS = 58, 130, 21
    start = date.fromisoformat(state["start"])
    days = [start + timedelta(days=i) for i in range(NDAYS)]
    gs, ge = days[0].isoformat(), days[-1].isoformat()
    today = date.today()
    apts = _apts()
    try:
        raw = data._reservations(gs, ge)
    except smoobu.SmoobuError as ex:
        ui.notify(f"Smoobu: {ex}", type="negative", timeout=8000)
        raw = []
    by_apt = {}
    for b in raw:
        if not bookings.is_real(b):
            continue
        nb = bookings.normalize(b)
        if nb["arrival"] and nb["departure"] and nb["apartment_id"]:
            by_apt.setdefault(nb["apartment_id"], []).append(nb)
    for lst in by_apt.values():
        lst.sort(key=lambda x: x["arrival"])

    # Navigation
    with ui.row().classes("w-full items-center gap-1"):
        ui.button(icon="chevron_left", on_click=lambda: _shift_days(state, -7, rerender)) \
            .props("flat round dense")
        ui.label(f"{start.strftime('%d.%m.')} – {days[-1].strftime('%d.%m.%Y')}") \
            .classes("text-sm font-semibold min-w-[150px] text-center")
        ui.button(icon="chevron_right", on_click=lambda: _shift_days(state, 7, rerender)) \
            .props("flat round dense")
        ui.space()
        ui.button("Heute", icon="today",
                  on_click=lambda: (state.update(start=date.today().isoformat()), rerender())) \
            .props("flat dense no-caps")

    lbl = f"width:{LABELW}px; flex:0 0 {LABELW}px"
    with ui.element("div").classes("w-full overflow-x-auto rounded-xl border border-slate-100"):
        with ui.column().classes("gap-0").style(f"min-width:{LABELW + NDAYS * CELL}px"):
            # Kopfzeile: Tage
            with ui.row().classes("no-wrap items-stretch gap-0 bg-slate-50 border-b border-slate-100"):
                ui.element("div").style(lbl)
                for d in days:
                    is_today = (d == today)
                    weekend = d.weekday() >= 5
                    with ui.column().classes("items-center justify-center gap-0 py-1") \
                            .style(f"width:{CELL}px; flex:0 0 {CELL}px"):
                        ui.label(_WD[d.weekday()]).classes(
                            "text-[10px] leading-none " + ("text-primary font-bold" if is_today
                            else ("text-blue-500" if weekend else "text-gray-400")))
                        ui.label(str(d.day)).classes(
                            "text-xs leading-tight " + ("text-primary font-bold" if is_today else "text-gray-600"))
            # Zeile je Wohnung
            grid_bg = ("background-image:repeating-linear-gradient(to right,"
                       "#eef2f7 0 1px,transparent 1px %dpx)" % CELL)
            for aid, name in apts.items():
                hexc = _apt_hex(aid)
                with ui.row().classes("no-wrap items-center gap-0 border-b border-slate-100").style("height:44px"):
                    with ui.row().classes("no-wrap items-center gap-1 px-2").style(lbl):
                        ui.element("div").classes("rounded-full shrink-0") \
                            .style(f"width:10px;height:10px;background:{hexc}")
                        ui.label(name).classes("text-sm font-medium truncate text-slate-700")
                    with ui.element("div").style(
                            f"position:relative; height:44px; width:{NDAYS * CELL}px; "
                            f"flex:0 0 {NDAYS * CELL}px; {grid_bg}"):
                        if gs <= today.isoformat() <= ge:
                            ti = (today - start).days
                            ui.element("div").style(
                                f"position:absolute; left:{ti * CELL}px; top:0; width:{CELL}px; "
                                "height:100%; background:rgba(94,42,132,0.07)")
                        for b in by_apt.get(aid, []):
                            a_idx = max((date.fromisoformat(b["arrival"]) - start).days, 0)
                            d_idx = min((date.fromisoformat(b["departure"]) - start).days, NDAYS)
                            if d_idx <= 0 or a_idx >= NDAYS or d_idx <= a_idx:
                                continue
                            w = (d_idx - a_idx) * CELL - 6
                            bar = ui.label((b["guest"] or b["apartment_name"])).classes(
                                "absolute text-white text-xs truncate cursor-pointer rounded-full px-3 "
                                "shadow-sm hover:brightness-110").style(
                                f"left:{a_idx * CELL + 3}px; width:{w}px; top:8px; height:28px; "
                                f"line-height:28px; background:{hexc}")
                            bar.on("click", lambda _e, bk=b: open_booking_dialog(bk, user, admin, staff, activate))
            if not apts:
                ui.label("Keine Wohnungen geladen.").classes("text-gray-500 p-4")


def _single_month(state, user, admin, staff, activate, rerender):
    """Monatskalender EINER Wohnung; Buchungen als durchgehende Balken pro Woche."""
    import calendar as _cal
    from datetime import timedelta
    aid = state["apt"]
    if not aid:
        ui.label("Keine Wohnung gewählt.").classes("text-gray-500 mt-2")
        return
    name = _apts().get(aid, "")
    hexc = _apt_hex(aid)
    y, m = state["y"], state["m"]
    first = date(y, m, 1)
    start = first - timedelta(days=first.weekday())
    last = date(y, m, _cal.monthrange(y, m)[1])
    weeks = ((last - start).days) // 7 + 1
    gs = start.isoformat()
    ge = (start + timedelta(days=weeks * 7 - 1)).isoformat()
    try:
        raw = data._reservations(gs, ge)
    except smoobu.SmoobuError as ex:
        ui.notify(f"Smoobu: {ex}", type="negative", timeout=8000)
        raw = []
    bks = [bookings.normalize(b) for b in raw if bookings.is_real(b)]
    bks = [b for b in bks if b["apartment_id"] == aid and b["arrival"] and b["departure"]]
    bks.sort(key=lambda b: b["arrival"])

    # Kopf: Navigation
    with ui.row().classes("w-full items-center gap-1"):
        ui.button(icon="chevron_left", on_click=lambda: _shift_month(state, -1, rerender)) \
            .props("flat round dense")
        ui.label(f"{_MONTHS[m - 1]} {y}").classes("text-lg font-semibold min-w-[150px] text-center")
        ui.button(icon="chevron_right", on_click=lambda: _shift_month(state, 1, rerender)) \
            .props("flat round dense")
        ui.space()
        ui.chip(name).style(f"background:{hexc};color:white")
        ui.button("Heute", icon="today",
                  on_click=lambda: (state.update(y=date.today().year, m=date.today().month), rerender())) \
            .props("flat dense no-caps")
    # Wochentags-Kopf
    with ui.row().classes("no-wrap w-full gap-0"):
        for wd in _WD:
            ui.label(wd).classes("text-xs font-medium text-gray-400 text-center").style("width:14.2857%")

    today = date.today()
    colpct = 100 / 7
    for w in range(weeks):
        ws = start + timedelta(days=w * 7)
        we = ws + timedelta(days=6)
        with ui.element("div").classes("relative w-full").style("min-height:78px"):
            # Hintergrund: 7 Tageszellen
            with ui.row().classes("no-wrap w-full gap-0"):
                for i in range(7):
                    d = ws + timedelta(days=i)
                    other = d.month != m
                    is_today = (d == today)
                    cc = "border border-slate-100 " + ("bg-violet-50 " if is_today else "")
                    with ui.element("div").classes(cc).style("width:14.2857%; min-height:78px"):
                        ui.label(str(d.day)).classes(
                            "text-xs px-1 pt-1 " + ("font-bold text-primary" if is_today
                            else ("text-gray-300" if other else "text-gray-500")))
            # Balken (durchgehend über die Woche)
            for b in bks:
                a = date.fromisoformat(b["arrival"])
                dep = date.fromisoformat(b["departure"])
                sc = max((a - ws).days, 0)
                ec = min((dep - ws).days, 7)        # exklusiv (deckt Nächte ab)
                if ec <= 0 or sc >= 7 or ec <= sc:
                    continue
                round_l = a >= ws                    # echter Anreisetag in dieser Woche
                round_r = dep <= we                  # echter Abreisetag in dieser Woche
                il = 3 if round_l else 0
                ir = 3 if round_r else 0
                style = (f"position:absolute; top:26px; height:22px; line-height:22px; "
                         f"left:calc({sc * colpct}% + {il}px); "
                         f"width:calc({(ec - sc) * colpct}% - {il + ir}px); "
                         f"background:{hexc};")
                if round_l:
                    style += "border-top-left-radius:9999px;border-bottom-left-radius:9999px;"
                if round_r:
                    style += "border-top-right-radius:9999px;border-bottom-right-radius:9999px;"
                label = (b["guest"] or name) if (a >= ws) else ""
                bar = ui.label(label).classes(
                    "text-white text-xs truncate cursor-pointer px-2 shadow-sm hover:brightness-110") \
                    .style(style)
                bar.on("click", lambda _e, bk=b: open_booking_dialog(bk, user, admin, staff, activate))


def _render_cleaning(user, admin, staff, activate):
    jobs = _cleaning_jobs()
    if not jobs:
        ui.label("Keine anstehenden Reinigungen.").classes("text-gray-500 mt-4")
        return
    # Offene "Nachtragen"-Fälle einmalig per E-Mail anstoßen
    for j in jobs:
        if _booking_status(j) == "nachtragen":
            _notify_nachtragen(j, staff)
    today = date.today().isoformat()
    overdue = [j for j in jobs if _booking_status(j) == "nachtragen"]
    odids = {j["id"] for j in overdue}
    todayj = [j for j in jobs if j["departure"] == today and j["id"] not in odids]
    future = [j for j in jobs if j["departure"] > today and j["id"] not in odids]

    # Überfällig – volle Karten
    if overdue:
        ui.label(f"Überfällig ({len(overdue)})").classes("text-sm font-semibold text-red-600 mt-2")
        for j in overdue:
            _cleaning_card(j, user, admin, staff, activate)
    # Heute – volle Karten
    if todayj:
        ui.label(f"Heute ({len(todayj)})").classes("text-sm font-semibold text-primary mt-3")
        for j in todayj:
            _cleaning_card(j, user, admin, staff, activate)
    if not overdue and not todayj:
        ui.label("Heute keine Reinigungen. 🎉").classes("text-gray-500 mt-2")

    # Kommende Tage – kompakt, ausklappbar
    if future:
        groups = {}
        for j in future:
            groups.setdefault(j["departure"], []).append(j)
        ui.label("KOMMENDE TAGE").classes("text-xs font-semibold tracking-wide text-gray-400 mt-4")
        for d in sorted(groups):
            dd = date.fromisoformat(d)
            n = len(groups[d])
            with ui.expansion(f"{_WD[dd.weekday()]} {dd.strftime('%d.%m.%Y')}  ·  "
                              f"{n} Reinigung{'en' if n != 1 else ''}", icon="event") \
                    .classes("w-full border border-slate-100 rounded-xl"):
                for j in groups[d]:
                    _cleaning_compact(j, user, admin, staff, activate)


def _add_time_dialog(job, user, activate):
    """Arbeitszeit für diese Buchung manuell nachtragen."""
    from datetime import datetime
    with ui.dialog() as dlg, ui.card().classes("w-[420px] max-w-full gap-2"):
        ui.label(f"Arbeitszeit nachtragen – {job['apartment_name']}").classes("text-lg font-bold")
        d = ui.input("Datum", value=job["departure"]).props("type=date outlined dense").classes("w-full")
        with ui.row().classes("w-full gap-2"):
            t1 = ui.input("Von", value=(job.get("checkout_time") or "10:00")) \
                .props("type=time outlined dense").classes("flex-grow")
            t2 = ui.input("Bis", value="12:00").props("type=time outlined dense").classes("flex-grow")

        def save():
            try:
                ci = datetime.fromisoformat(f"{d.value}T{t1.value}")
                co = datetime.fromisoformat(f"{d.value}T{t2.value}")
            except Exception:
                ui.notify("Bitte Datum und Uhrzeiten prüfen.", type="warning"); return
            if co <= ci:
                ui.notify("Ende muss nach Beginn liegen.", type="warning"); return
            timetrack.add_manual(user, ci, co, booking_id=job["id"], apartment=job["apartment_name"])
            ui.notify(f"Arbeitszeit nachgetragen: {timetrack.fmt_dur(int((co - ci).total_seconds() // 60))}",
                      type="positive")
            dlg.close()
            activate("buchungen")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Abbrechen", on_click=dlg.close).props("flat")
            ui.button("Speichern", icon="save", on_click=save).props("unelevated")
    dlg.open()


def _checklist_progress(job, user):
    """(erledigt, gesamt) der Checkliste für die Wohnung dieser Buchung."""
    try:
        cl = housekeeping.get_checklist(job["apartment_id"])
        total = sum(len(r["tasks"]) for r in cl["rooms"])
    except Exception:
        total = 0
    run = housekeeping.get_open_run(job["apartment_id"], user)
    if run:
        return sum(1 for v in run["tasks"].values() if v.get("done")), total
    if bookings.is_checklist_done(job["id"]):
        return total, total
    return 0, total


def _step_button(label, icon, cb):
    """Listen-Zeile als Button (Icon · Label · Chevron)."""
    b = ui.button(on_click=cb).props("flat no-caps align=left").classes("w-full")
    with b:
        with ui.row().classes("w-full items-center gap-3 no-wrap"):
            ui.icon(icon).classes("text-primary")
            ui.label(label).classes("flex-grow text-left normal-case text-slate-700")
            ui.icon("chevron_right").classes("text-gray-300")


def _note_dialog(job):
    rec = bookings.get_record(job["id"])
    with ui.dialog() as dlg, ui.card().classes("w-[420px] max-w-full gap-2"):
        ui.label(f"Notiz – {job['apartment_name']}").classes("text-lg font-bold")
        ta = ui.textarea("Notiz", value=rec.get("note", "")).props("outlined autogrow").classes("w-full")

        def save():
            bookings.set_field(job["id"], note=(ta.value or "").strip())
            ui.notify("Notiz gespeichert ✓", type="positive"); dlg.close()
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Abbrechen", on_click=dlg.close).props("flat")
            ui.button("Speichern", icon="save", on_click=save).props("unelevated")
    dlg.open()


def _restock_dialog(job, user):
    with ui.dialog() as dlg, ui.card().classes("w-[440px] max-w-full gap-2"):
        ui.label(f"Verbrauch / Wäsche – {job['apartment_name']}").classes("text-lg font-bold")
        ui.label("Was muss nachgekauft werden?").classes("text-sm text-gray-500")
        for it in housekeeping.get_inventory(job["apartment_id"]):
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.label(it["name"]).classes("flex-grow")
                qty = ui.input("Menge", value="1").props("dense outlined").classes("w-20")

                def melden(name=it["name"], kat=it["kategorie"], q=qty):
                    housekeeping.add_restock(job["apartment_id"], job["apartment_name"],
                                             name, (q.value or "1").strip(), kat, user)
                    ui.notify(f"{name} gemeldet ✓", type="positive")
                ui.button("melden", icon="add_shopping_cart", on_click=melden).props("flat dense no-caps")
        with ui.row().classes("w-full justify-end"):
            ui.button("Schließen", on_click=dlg.close).props("flat")
    dlg.open()


def _cleaning_card(job, user, admin, staff, activate):
    """Voll-Karte gemäß Entwurf: Status, Zeiten, Gast, Vorbereiten-für, Live-Timer +
    Checklisten-Fortschritt (wenn Arbeit läuft), sonst Arbeitszeit starten."""
    from datetime import datetime
    status = _booking_status(job)
    nxt = job.get("next")
    same_day = bool(nxt and nxt["arrival"] == job["departure"])
    done_entries = [e for e in timetrack.entries_for_booking(job["id"]) if e.get("checkout")]
    total_min = sum(timetrack.duration_minutes(e) or 0 for e in done_entries)
    oe = timetrack.get_open(user)
    open_here = bool(oe and str(oe.get("booking_id")) == str(job["id"]))

    async def _do_in():
        gps = None
        try:
            loc = await get_location()
            gps = None if loc.get("error") else loc
        except Exception:
            pass
        ort, dist = _match_geofence(gps)
        if timetrack.check_in(user, gps, None, ort, dist,
                              booking_id=job["id"], apartment=job["apartment_name"]) is None:
            ui.notify("Du bist bereits an einem anderen Ort eingecheckt.", type="warning")
        else:
            ui.notify("Arbeitszeit gestartet ✓", type="positive")
        activate("buchungen")

    async def _do_out():
        gps = None
        try:
            loc = await get_location()
            gps = None if loc.get("error") else loc
        except Exception:
            pass
        ort, dist = _match_geofence(gps)
        timetrack.check_out(user, gps, None, ort, dist)
        ui.notify("Arbeitszeit beendet ✓", type="positive")
        activate("buchungen")

    with ui.card().classes("w-full rounded-2xl shadow-sm border border-slate-100 gap-2 p-4 mt-1"):
        # Info (klickbar -> Detail-Dialog)
        info = ui.column().classes("w-full gap-1 cursor-pointer").mark("booking-details")
        info.on("click", lambda: open_booking_dialog(job, user, admin, staff, activate))
        with info:
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.icon("cleaning_services").classes("text-primary text-xl shrink-0")
                ui.label(job["apartment_name"]).classes("font-bold text-lg leading-tight")
                ui.space()
                _status_chip(job)
            if same_day:
                ui.chip("Wechseltag", icon="bolt").props("color=deep-orange text-color=white dense")
            with ui.row().classes("w-full items-center gap-1 text-sm text-slate-600 no-wrap"):
                ui.icon("logout").classes("text-deep-orange text-base")
                ui.label(f"Check-out {job['checkout_time'] or '—'}")
                ui.icon("arrow_forward").classes("text-gray-400 text-sm")
                ui.icon("login").classes("text-green-700 text-base")
                ui.label(f"Check-in {nxt['checkin_time'] if nxt else '—'}")
            with ui.row().classes("w-full items-center gap-1 text-sm no-wrap"):
                ui.icon("person").classes("text-gray-400 text-base")
                ui.label(f"{job['guest'] or 'Gast'} · {_persons_text(job)}") \
                    .classes("text-slate-700 truncate")
            ui.label("Anreise vorbereiten für").classes(
                "text-xs mt-1 " + ("text-red-500" if same_day else "text-gray-400"))
            ui.label(_persons_text(nxt) if nxt else "keine Folgebuchung").classes(
                "text-sm font-semibold " + ("text-red-700" if same_day
                else ("text-green-700" if nxt else "text-gray-500")))

        # Primärbereich je Zustand
        if open_here:
            checkin_dt = datetime.fromisoformat(oe["checkin"])
            dprog, tprog = _checklist_progress(job, user)
            complete = bool(tprog) and dprog >= tprog
            with ui.card().classes("w-full bg-violet-50 rounded-xl p-3 gap-1 shadow-none"):
                with ui.row().classes("w-full items-center"):
                    ui.label("Arbeitszeit läuft").classes("text-xs text-gray-500")
                    ui.space()
                    if not complete:
                        ui.button("Beenden", icon="stop_circle", on_click=_do_out) \
                            .props("outline dense no-caps color=negative")
                tl = ui.label("0:00:00").classes("text-3xl font-bold text-primary")

                def tick(cd=checkin_dt, lbl=tl):
                    lbl.text = str(datetime.now().replace(microsecond=0) - cd.replace(microsecond=0))
                tick()
                ui.timer(1.0, tick)
            with ui.row().classes("w-full items-center"):
                ui.label("Checkliste").classes("font-medium text-sm")
                ui.space()
                ui.label(f"{dprog}/{tprog} erledigt").classes("text-xs text-gray-500")
            ui.linear_progress(value=(dprog / tprog if tprog else 0), show_value=False) \
                .props(f"color={'green' if complete else 'primary'} rounded track-color=grey-3").classes("w-full")
            if not complete:
                ui.button("Weiter zur Checkliste", icon="checklist",
                          on_click=lambda: _open_checkliste(job["apartment_id"], job["apartment_name"], activate, job["id"])) \
                    .props("unelevated no-caps size=lg").classes("w-full")
            else:
                with ui.row().classes("w-full items-center gap-1 text-sm text-green-700"):
                    ui.icon("check_circle").classes("text-base")
                    ui.label("Alle Aufgaben abgeschlossen")
                ui.label("Nächste Schritte").classes("text-xs font-semibold text-gray-400 mt-1")
                with ui.column().classes("w-full gap-1"):
                    _step_button("Fotos & Schäden prüfen", "photo_camera",
                                 lambda: open_damage_dialog(job["apartment_id"], job["apartment_name"], user))
                    _step_button("Notiz hinzufügen", "sticky_note_2",
                                 lambda: _note_dialog(job))
                    _step_button("Verbrauch / Wäsche", "inventory_2",
                                 lambda: _restock_dialog(job, user))
                ui.button("Arbeitszeit beenden", icon="stop_circle", on_click=_do_out) \
                    .props("unelevated no-caps size=lg color=negative").classes("w-full mt-1")
        elif status == "abgeschlossen":
            dprog, tprog = _checklist_progress(job, user)
            with ui.row().classes("w-full items-center gap-2 text-sm text-green-700 bg-green-50 rounded-lg p-2"):
                ui.icon("check_circle")
                ui.label(f"Fertig · {timetrack.fmt_dur(total_min)} · {tprog}/{tprog} erledigt")
        else:
            if total_min:
                ui.label(f"Erfasst {timetrack.fmt_dur(total_min)}").classes("text-xs text-gray-500")
            ui.button("Arbeitszeit starten", icon="play_arrow", on_click=_do_in) \
                .props("unelevated no-caps size=lg").classes("w-full")


def _cleaning_compact(job, user, admin, staff, activate):
    nxt = job.get("next")
    card = ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100 p-3 cursor-pointer")
    card.on("click", lambda: open_booking_dialog(job, user, admin, staff, activate))
    with card:
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            ui.icon("home").classes("text-primary shrink-0")
            with ui.column().classes("gap-0 min-w-0 flex-grow"):
                ui.label(job["apartment_name"]).classes("font-medium truncate")
                ui.label(f"Check-out {job['checkout_time'] or '—'} → "
                         f"Check-in {nxt['checkin_time'] if nxt else '—'}") \
                    .classes("text-xs text-gray-500")
                ui.label(_persons_text(nxt) if nxt else _persons_text(job)) \
                    .classes("text-xs text-gray-500")
            _status_chip(job)
            ui.icon("chevron_right").classes("text-gray-300 shrink-0")


def _event_card(ev, user, admin, staff, activate):
    is_out = ev["kind"] == "out"
    who = bookings.assignee_of(ev["id"])
    who_name = staff.get(who, who) if who else None
    with ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100 gap-1 p-3"):
        with ui.row().classes("w-full items-center gap-2 flex-wrap"):
            if is_out:
                ui.chip("Abreise", icon="logout").props("color=deep-orange text-color=white dense")
            else:
                ui.chip("Anreise", icon="login").props("color=green text-color=white dense")
            ui.label(ev["apartment_name"]).classes("font-semibold")
            with ui.row().classes("items-center gap-1 text-sm text-gray-500"):
                ui.icon("schedule").classes("text-base")
                ui.label(ev["time"] or "—")
            if ev.get("nights") is not None:
                with ui.row().classes("items-center gap-1 text-sm text-gray-500") \
                        .tooltip("Nächte"):
                    ui.icon("dark_mode").classes("text-base")
                    ui.label(f"{ev['nights']}")
            ui.space()
            if is_out:
                if who_name:
                    ui.chip(who_name, icon="person").props("color=primary text-color=white dense")
                else:
                    ui.chip("nicht zugewiesen", icon="person_off").props("color=grey-4 dense")
        with ui.row().classes("w-full items-center gap-2 flex-wrap text-sm text-gray-500"):
            ui.label(f"{ev['guest'] or 'Gast'} · {ev['channel']}")
            ui.label(_persons_text(ev))
        with ui.row().classes("w-full items-center gap-2 flex-wrap mt-1"):
            ui.button("Öffnen", icon="open_in_full",
                      on_click=lambda e=ev: open_booking_dialog(e, user, admin, staff, activate)) \
                .props("unelevated dense no-caps")
            if is_out and who != user:
                ui.button("Ich übernehme", icon="how_to_reg",
                          on_click=lambda e=ev: _assign(e, user, user, staff, activate)) \
                    .props("outline dense no-caps")


def _assign(bk, assignee, by, staff, activate, note=""):
    bookings.set_assignment(bk["id"], assignee, by, note)
    if assignee != by:   # jemandem anderen zugewiesen → benachrichtigen
        _notify_assignee(bk, assignee, by, staff)
    ui.notify(f"{bk['apartment_name']} → {staff.get(assignee, assignee)} zugewiesen ✓",
              type="positive")
    activate("buchungen")


def _notify_assignee(bk, assignee, by, staff):
    to = _user_email(assignee)
    if not to:
        ui.notify(f"Hinweis: {staff.get(assignee, assignee)} hat keine E-Mail hinterlegt "
                  "(Benutzerverwaltung).", type="warning", timeout=8000)
        return
    body = (f"Hallo {staff.get(assignee, assignee)},\n\n"
            f"dir wurde eine Reinigung zugewiesen:\n\n"
            f"Wohnung: {bk['apartment_name']}\n"
            f"Abreise (Reinigung): {bk['departure']}, Check-out {bk['checkout_time'] or '—'}\n"
            f"Anreise nächster Gast: {bk['arrival']}\n"
            f"Personen: {bk['persons']}\n\n"
            f"Zugewiesen von: {staff.get(by, by)}\n\n"
            f"Bitte in der LIVARO-App bestätigen: https://app.ds-apartments.de\n")
    try:
        mailer.send_notify(CFG, to, f"Neue Reinigung: {bk['apartment_name']} ({bk['departure']})", body)
        ui.notify(f"{staff.get(assignee, assignee)} per E-Mail benachrichtigt ✓", type="positive")
    except mailer.MailError as ex:
        ui.notify(f"E-Mail nicht gesendet: {ex}", type="warning", timeout=9000)


def _notify_nachtragen(job, staff):
    """Einmalige Erinnerung, wenn nach Check-out nicht abgeschlossen (Checkliste +
    Arbeitszeit fehlen). Empfänger: zugewiesener Mitarbeiter, sonst Admin."""
    rec = bookings.get_record(job["id"])
    if rec.get("nachtragen_notified"):
        return
    who = bookings.assignee_of(job["id"])
    to = _user_email(who) if who else (CFG.get("notify_email", {}).get("absender")
                                       or CFG.get("email", {}).get("absender"))
    if not to:
        return
    anrede = staff.get(who, who) if who else "Team"
    body = (f"Hallo {anrede},\n\n"
            f"die folgende Reinigung wurde nach dem Check-out noch nicht abgeschlossen. "
            f"Bitte trage die Checkliste und die Arbeitszeit in der LIVARO-App nach:\n\n"
            f"Wohnung: {job['apartment_name']}\n"
            f"Abreise: {job['departure']}, Check-out {job.get('checkout_time') or '—'}\n"
            f"Gast: {job.get('guest') or '—'}\n\n"
            f"App: https://app.ds-apartments.de  →  Buchungen → Reinigungen\n")
    try:
        mailer.send_notify(CFG, to,
                           f"Bitte nachtragen: {job['apartment_name']} ({job['departure']})", body)
        bookings.set_field(job["id"], nachtragen_notified=bookings.now_iso())
    except mailer.MailError:
        pass   # später erneut versuchen (Flag nicht gesetzt)


def _open_swap(bk, user, staff, activate):
    who = bookings.assignee_of(bk["id"])
    others = {u: n for u, n in staff.items() if u != who}
    with ui.dialog() as dlg, ui.card().classes("w-[360px] max-w-full gap-2"):
        ui.label(f"Zuweisen / Tauschen – {bk['apartment_name']}").classes("font-bold")
        if not others:
            ui.label("Keine weiteren Mitarbeiter.").classes("text-sm text-gray-500")
        sel = ui.select(others, label="Mitarbeiter").props("dense outlined").classes("w-full")

        def go():
            if not sel.value:
                ui.notify("Bitte Mitarbeiter wählen.", type="warning"); return
            dlg.close()
            _assign(bk, sel.value, user, staff, activate)
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Abbrechen", on_click=dlg.close).props("flat")
            ui.button("Zuweisen", icon="check", on_click=go).props("unelevated")
    dlg.open()


def open_booking_dialog(bk, user, admin, staff, activate):
    who = bookings.assignee_of(bk["id"])
    nxt = bk.get("next")
    same_day = bool(nxt and nxt["arrival"] == bk["departure"])
    with ui.dialog() as dlg, ui.card().classes("w-[460px] max-w-full gap-0 p-0"):
        with ui.row().classes("w-full items-center gap-2 p-3 pb-1"):
            ui.icon("home").classes("text-primary text-2xl")
            ui.label(bk["apartment_name"]).classes("text-xl font-bold")
            ui.space()
            ui.button(icon="close", on_click=dlg.close).props("flat round dense")
        with ui.tabs().props("dense no-caps align=left").classes("w-full px-2") as tabs:
            t_b = ui.tab("Buchung")
            t_g = ui.tab("Gast")
            t_n = ui.tab("Notizen")
        with ui.tab_panels(tabs, value=t_b).classes("w-full"):
            with ui.tab_panel(t_b):
                with ui.grid(columns=2).classes("w-full gap-x-4 gap-y-1 text-sm"):
                    ui.label("Anreise").classes("text-gray-500")
                    ui.label(f"{_dfmt(bk['arrival'])} · {bk['checkin_time'] or '—'}")
                    ui.label("Abreise").classes("text-gray-500")
                    ui.label(f"{_dfmt(bk['departure'])} · {bk['checkout_time'] or '—'}")
                    ui.label("Personen").classes("text-gray-500")
                    ui.label(_persons_text(bk))
                    ui.label("Gast").classes("text-gray-500")
                    ui.label(bk["guest"] or "—")
                    ui.label("Buchungskanal").classes("text-gray-500")
                    ui.label(bk["channel"] or "—")
                if nxt:
                    with ui.column().classes("w-full gap-0 rounded-lg p-2 mt-2 "
                                             + ("bg-red-50" if same_day else "bg-green-50")):
                        ui.label("Anreise vorbereiten für").classes(
                            "text-xs " + ("text-red-500" if same_day else "text-gray-500"))
                        ui.label(_persons_text(nxt)).classes(
                            "text-sm font-semibold " + ("text-red-700" if same_day else "text-green-700"))
                        ui.label(f"Nächste Anreise: {_dfmt(nxt['arrival'])} · {nxt['checkin_time'] or ''}"
                                 + (" (Wechseltag)" if same_day else "")).classes("text-xs text-gray-500")
            with ui.tab_panel(t_g):
                with ui.grid(columns=2).classes("w-full gap-x-4 gap-y-1 text-sm"):
                    ui.label("Name").classes("text-gray-500")
                    ui.label(bk["guest"] or "—")
                    ui.label("E-Mail").classes("text-gray-500")
                    ui.label(bk.get("email") or "—")
                    ui.label("Telefon").classes("text-gray-500")
                    ui.label(bk.get("phone") or "—")
            with ui.tab_panel(t_n):
                intern = bookings.get_record(bk["id"]).get("note", "")
                if intern:
                    ui.label("Interne Notiz").classes("text-xs text-gray-500")
                    ui.label(intern).classes("text-sm whitespace-pre-wrap")
                    ui.separator().classes("my-1")
                ui.label("Buchungsdetails (Smoobu)").classes("text-xs text-gray-500")
                ui.label(bk["notice"] or "—").classes("text-sm whitespace-pre-wrap")

        ui.separator()
        ui.label("Aktionen").classes("text-xs font-semibold text-gray-400 px-3 pt-1")

        def action(label, icon, cb, color="primary"):
            b = ui.button(on_click=cb).props("flat no-caps align=left").classes("w-full")
            with b:
                with ui.row().classes("w-full items-center gap-3 no-wrap"):
                    ui.icon(icon).classes(f"text-{color}")
                    ui.label(label).classes("flex-grow text-left normal-case text-slate-700")
                    ui.icon("chevron_right").classes("text-gray-300")
        if who != user:
            action("Ich übernehme diesen Auftrag", "how_to_reg",
                   lambda: (dlg.close(), _assign(bk, user, user, staff, activate)))
        action("Tauschen / Zuweisen", "swap_horiz",
               lambda: (dlg.close(), _open_swap(bk, user, staff, activate)))
        action("Zeit nachtragen", "more_time",
               lambda: (dlg.close(), _add_time_dialog(bk, user, activate)))
        action("Notiz hinzufügen", "sticky_note_2",
               lambda: (dlg.close(), _note_dialog(bk)))
        action("Verbrauch / Wäsche", "inventory_2",
               lambda: (dlg.close(), _restock_dialog(bk, user)))
        action("Schaden melden", "report_problem",
               lambda: (dlg.close(), open_damage_dialog(bk["apartment_id"], bk["apartment_name"], user)),
               color="negative")
        action("Checkliste & Fotos", "checklist",
               lambda: (dlg.close(), _open_checkliste(bk["apartment_id"], bk["apartment_name"], activate, bk["id"])))
    dlg.open()


def _beleg_mirror():
    return CFG.get("belege_ordner") or None


def render_belege():
    user = _cur_user()
    admin = _is_admin()
    with ui.row().classes("w-full items-center gap-3"):
        ui.icon("receipt").classes("text-3xl text-primary")
        with ui.column().classes("gap-0"):
            ui.label("Belege").classes("text-2xl font-bold text-slate-800 leading-tight")
            ui.label("Rechnungen scannen, ablegen & per OCR auslesen") \
                .classes("text-sm text-gray-500")

    box = ui.column().classes("w-full gap-3")

    def render():
        box.clear()
        with box:
            # Upload-Karte
            with ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100 gap-2 p-4"):
                ui.label("Neuen Beleg hochladen").classes("font-medium")
                ui.label("Rechnung fotografieren (Kamera) oder aus der Galerie wählen. "
                         "Der Text wird automatisch per OCR erkannt.") \
                    .classes("text-xs text-gray-500")

                async def handle(e):
                    try:
                        content, name = await _read_upload(e)
                    except Exception as ex:
                        ui.notify(f"Upload fehlgeschlagen: {ex}", type="negative"); return
                    ext = (name.rsplit(".", 1)[-1] if "." in name else "jpg").lower()[:4] or "jpg"
                    rel = housekeeping.save_photo("beleg", content, ext=ext,
                                                  mirror_dir=_beleg_mirror())
                    ui.notify("Beleg gespeichert – Text wird erkannt …", type="info", timeout=3000)
                    from nicegui import run
                    try:
                        text = await run.io_bound(receipts.ocr_image,
                                                  os.path.join(housekeeping.MEDIA_DIR, rel))
                    except Exception:
                        text = ""
                    receipts.add_receipt(user, rel, ocr_text=text,
                                         amount=receipts.guess_amount(text),
                                         merchant=receipts.guess_merchant(text))
                    ui.notify("Beleg erfasst ✓", type="positive")
                    render()
                ui.upload(auto_upload=True, on_upload=handle, label="Beleg wählen") \
                    .props('accept="image/*"').classes("hk-upload w-full max-w-[260px]")
                if not receipts.ocr_available():
                    ui.label("Hinweis: OCR (Tesseract) ist auf dem Server nicht installiert – "
                             "Belege werden gespeichert, aber nicht automatisch ausgelesen.") \
                        .classes("text-xs text-amber-700")

            items = receipts.list_receipts()
            if not items:
                ui.label("Noch keine Belege abgelegt.").classes("text-gray-500 mt-2")
                return
            cur_month = None
            for r in items:
                month = r["ts"][:7]
                if month != cur_month:
                    cur_month = month
                    ym = f"{_MONATE[int(month[5:7]) - 1]} {month[:4]}"
                    ui.label(ym).classes("text-sm font-semibold text-primary mt-3")
                _beleg_card(r, user, admin, render)
    render()


_MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
           "August", "September", "Oktober", "November", "Dezember"]


def _beleg_card(r, user, admin, rerender):
    with ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100 gap-2 p-3"):
        with ui.row().classes("w-full items-start gap-3 no-wrap"):
            if r.get("photo"):
                _photo_thumb(f"/media/{r['photo']}", "w-20 h-20")
            with ui.column().classes("gap-1 min-w-0 flex-grow"):
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    merch = ui.input(placeholder="Händler", value=r.get("merchant", "")) \
                        .props("dense borderless").classes("font-semibold flex-grow min-w-0")
                    merch.on("blur", lambda e, i=r["id"], f=merch:
                             receipts.update_receipt(i, merchant=f.value or ""))
                    amount = ui.input(placeholder="€", value=r.get("amount", "")) \
                        .props("dense borderless").classes("w-20 text-right")
                    amount.on("blur", lambda e, i=r["id"], f=amount:
                              receipts.update_receipt(i, amount=f.value or ""))
                    ui.label("€").classes("text-sm text-gray-400")
                ui.label(f"{_d(r['ts'])} · {r.get('uploader', '')}").classes("text-xs text-gray-400")
                note = ui.input(placeholder="Notiz (z. B. Wofür / welche Wohnung)",
                                value=r.get("note", "")).props("dense borderless").classes("w-full")
                note.on("blur", lambda e, i=r["id"], f=note:
                        receipts.update_receipt(i, note=f.value or ""))
            if admin:
                ui.button(icon="delete", on_click=lambda i=r["id"]: _del_beleg(i, rerender)) \
                    .props("flat round dense color=negative").tooltip("Beleg löschen")
        if r.get("ocr_text"):
            with ui.expansion("Erkannter Text (OCR)", icon="document_scanner").classes("w-full"):
                ui.label(r["ocr_text"]).classes("text-xs whitespace-pre-wrap text-gray-600")


def _del_beleg(receipt_id, rerender):
    with ui.dialog() as dlg, ui.card().classes("gap-2"):
        ui.label("Beleg wirklich löschen?").classes("font-medium")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Abbrechen", on_click=dlg.close).props("flat")
            ui.button("Löschen", on_click=lambda: (receipts.delete_receipt(receipt_id),
                                                   dlg.close(),
                                                   ui.notify("Beleg gelöscht.", type="warning"),
                                                   rerender())) \
                .props("unelevated color=negative")
    dlg.open()


# ---------------------------------------------------------------- Hauptseite
@ui.page("/")
def main_page():
    ui.colors(primary="#5E2A84", secondary="#8A5CC2", accent="#C8A96E",
              positive="#16a34a", negative="#dc2626", dark="#2D2D2D")
    ui.query("body").classes("bg-[#F5F2EB]")
    # Foto-Uploader (.hk-upload) als kompakten Button darstellen: Byte/Prozent-
    # Anzeige und Dateiliste ausblenden; nativer Tap öffnet Kamera/Galerie (iOS-fest).
    ui.add_css("""
    .hk-upload.q-uploader { box-shadow:none; border:1px solid #5E2A84; border-radius:10px;
        max-height:44px; min-height:44px; overflow:hidden; background:#fff; }
    .hk-upload .q-uploader__header { background:transparent; color:#5E2A84; min-height:44px; }
    .hk-upload .q-uploader__header-content { padding:2px 8px; min-height:44px; align-items:center; }
    .hk-upload .q-uploader__subtitle { display:none !important; }
    .hk-upload .q-uploader__list { display:none !important; }
    .hk-upload .q-uploader__spinner { display:none !important; }
    .hk-upload .q-uploader__title { font-size:.8rem; font-weight:600; line-height:1; white-space:nowrap; }
    """)
    today = date.today()
    role = _cur_role()
    areas = _role_areas(role)

    with ui.header(elevated=True).classes("items-center px-4 bg-white text-slate-800 border-b border-slate-200"):
        ui.button(icon="menu", on_click=lambda: drawer.toggle()) \
            .props("flat round color=primary dense").classes("lg:hidden")
        logo(42)
        ui.space()
        if _is_admin():
            ui.button("Benutzer", icon="group", on_click=open_users) \
                .props("flat color=primary no-caps")
            ui.button("Einstellungen", icon="settings", on_click=open_settings) \
                .props("flat color=primary no-caps")
        ui.button("Mein Konto", icon="account_circle", on_click=open_account) \
            .props("flat color=primary no-caps")
        ui.button(icon="logout", on_click=logout).props("flat round color=primary") \
            .tooltip("Abmelden")

    with ui.left_drawer(bordered=True).props("width=230").classes("bg-white") as drawer:
        ui.label("Bereiche").classes("text-xs uppercase tracking-wide text-gray-400 px-3 pt-3 pb-1")
        nav = ui.column().classes("w-full gap-1")
        ui.space()
        with ui.column().classes("px-3 pb-3 gap-0"):
            ui.label(_cur_user()).classes("text-sm font-medium text-slate-700")
            ui.label(ROLES.get(role, role)).classes("text-xs text-gray-400")

    content = ui.column().classes("w-full max-w-6xl mx-auto p-3 sm:p-6 gap-4 sm:gap-5")
    visible = [a for a in AREAS if a["key"] in areas]

    def _feature_header(icon, title, subtitle, action=None):
        with ui.row().classes("w-full items-center gap-3"):
            ui.icon(icon).classes("text-3xl text-primary")
            with ui.column().classes("gap-0"):
                ui.label(title).classes("text-2xl font-bold text-slate-800 leading-tight")
                ui.label(subtitle).classes("text-sm text-gray-500")
            ui.space()
            if action:
                action()

    def build_beherbergungssteuer():
        apts = _load_apartments()
        _feature_header("receipt_long", "Beherbergungssteuer", "Dresden · monatliche Steueranmeldung",
                        lambda: ui.button("Archiv", icon="inventory_2",
                                          on_click=open_archive).props("outline no-caps"))
        with ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100"):
            with ui.row().classes("items-end gap-4 flex-wrap"):
                year = ui.select(list(range(2023, today.year + 2)), label="Jahr",
                                 value=today.year).props("outlined dense")
                month = ui.select({m: data.MONATE[m] for m in range(1, 13)}, label="Monat",
                                  value=today.month).props("outlined dense")
                apt = ui.select(apts or {}, label="Apartments", multiple=True,
                                value=list(apts.keys())).classes("min-w-[220px]") \
                    .props("outlined dense use-chips")
                airbnb = ui.number("Airbnb-ÜN (Override)", value=None, format="%d") \
                    .props('outlined dense placeholder="leer = berechnet" clearable')
                befreit = ui.number("Steuerbefr. Umsatz €", value=0, step=0.01).props("outlined dense")
                ui.button("Berechnen", icon="calculate",
                          on_click=lambda: do_compute()).props("unelevated no-caps")
                ui.button(icon="refresh", on_click=lambda: do_compute(force=True)) \
                    .props("flat round").tooltip("Frisch von Smoobu laden (Cache leeren)")
            with ui.row().classes("items-center gap-2"):
                ui.label("Zuordnung nach Abreisedatum (§6) · nur bereits stattgefundene "
                         "Buchungen · Airbnb wird berechnet, nicht besteuert.") \
                    .classes("text-xs text-gray-500")
                ui.space()
                status = ui.label("").classes("text-xs text-gray-400")
        results = ui.column().classes("w-full gap-4")

        def do_compute(force=False):
            if force:
                data.clear_cache()
            try:
                result = data.compute(
                    int(year.value), int(month.value),
                    apt_ids=apt.value or None,
                    airbnb_override=int(airbnb.value) if airbnb.value not in (None, "") else None,
                    befreit=float(befreit.value or 0))
            except smoobu.SmoobuError as ex:
                ui.notify(f"Smoobu: {ex}", type="negative", timeout=8000)
                return
            if data.LAST_FETCH:
                status.text = f"Daten zuletzt von Smoobu geladen: {data.LAST_FETCH.strftime('%H:%M:%S')} (Cache 5 Min.)"
            render_result(results, result)
            if force:
                ui.notify("Frisch von Smoobu geladen", type="positive")

    def build_zeiterfassung():
        user = _cur_user()
        _feature_header("schedule", "Zeiterfassung", "Check-in / Check-out mit Standort-Nachweis")
        with ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100 items-start gap-2"):
            status_box = ui.column().classes("items-start gap-2")
        own_box = ui.column().classes("w-full")
        admin_box = ui.column().classes("w-full")

        async def _presence_now():
            ui.notify("Standort wird geprüft …", type="info", timeout=2000)
            loc = await get_location()
            ip = await get_ip()                 # zusätzlich protokolliert
            gps = None if loc.get("error") else loc
            ort, dist = _match_geofence(gps)
            return gps, ip, ort, dist

        async def do_checkin():
            gps, ip, ort, dist = await _presence_now()
            if timetrack.check_in(user, gps, ip, ort, dist) is None:
                ui.notify("Du bist bereits eingecheckt.", type="warning")
            elif ort:
                ui.notify(f"Eingecheckt ✓ · {ort} ({dist} m)", type="positive")
            elif gps:
                ui.notify(f"Eingecheckt ✓ · ⚠️ nicht am Objekt (nächstes {dist} m)",
                          type="warning", timeout=9000)
            else:
                ui.notify("Eingecheckt ✓ · ⚠️ kein Standort – bitte Ortung am Handy aktivieren.",
                          type="warning", timeout=10000)
            refresh()

        async def do_checkout():
            gps, ip, ort, dist = await _presence_now()
            if timetrack.check_out(user, gps, ip, ort, dist) is None:
                ui.notify("Kein offener Check-in.", type="warning")
            else:
                ui.notify(f"Ausgecheckt ✓ · {ort} ({dist} m)" if ort else "Ausgecheckt ✓",
                          type="positive")
            refresh()

        def refresh():
            status_box.clear()
            with status_box:
                oe = timetrack.get_open(user)
                if oe:
                    ui.label(f"Eingecheckt seit {_t(oe['checkin'])} Uhr") \
                        .classes("text-lg font-medium text-green-700")
                    ui.label("Nachweis: " + _presence(oe.get("checkin_ort"),
                             oe.get("checkin_dist"), oe.get("checkin_loc"), oe.get("checkin_ip"))) \
                        .classes("text-xs text-gray-500")
                    ui.button("Check-out", icon="logout", on_click=do_checkout) \
                        .props("unelevated size=lg color=negative")
                else:
                    ui.label("Nicht eingecheckt").classes("text-gray-500")
                    ui.button("Check-in", icon="login", on_click=do_checkin) \
                        .props("unelevated size=lg")
            _zeit_table(own_box, timetrack.entries(user), False, "Meine Zeiten")
            if _is_admin():
                _zeit_table(admin_box, timetrack.entries(), True, "Alle Mitarbeiter", export=True)
        refresh()

    def build_reinigung():
        render_reinigung(activate)

    def build_buchungen():
        render_buchungen(activate)

    def build_belege():
        render_belege()

    builders = {"buchungen": build_buchungen,
                "beherbergungssteuer": build_beherbergungssteuer,
                "reinigung": build_reinigung,
                "belege": build_belege,
                "zeiterfassung": build_zeiterfassung}

    _BASE_NAV = "items-center gap-2 mx-2 px-2 py-2 rounded-lg no-wrap cursor-pointer "
    nav_rows = {}
    with nav:
        for a in visible:
            row = ui.row().classes(_BASE_NAV).mark(f"nav-{a['key']}")
            with row:
                ui.icon(a["icon"]).classes("text-xl")
                ui.label(a["label"]).classes("font-medium")
            row.on("click", lambda e, k=a["key"]: activate(k))
            nav_rows[a["key"]] = row

    def activate(key):
        for k, row in nav_rows.items():
            row.classes(replace=_BASE_NAV + (
                "bg-violet-50 text-primary" if k == key else "text-slate-600 hover:bg-slate-100"))
        content.clear()
        with content:
            builders.get(key, lambda: None)()

    if visible:
        activate(visible[0]["key"])
    else:
        with content:
            with ui.card().classes("w-full rounded-xl p-8 items-center gap-2"):
                ui.icon("lock").classes("text-5xl text-gray-300")
                ui.label(f"Willkommen, {_cur_user()}!").classes("text-lg font-medium text-slate-700")
                ui.label("Für deinen Zugang sind noch keine Bereiche freigeschaltet.") \
                    .classes("text-gray-500")


def run():
    ui.run(host="127.0.0.1", port=int(CFG.get("port", 3001)),
           title="LIVARO Suites", reload=False, show=False,
           storage_secret=STORAGE_SECRET)


if __name__ in {"__main__", "__mp_main__"}:
    run()
