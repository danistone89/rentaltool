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
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nicegui import app, ui  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import RedirectResponse  # noqa: E402

from app import data, smoobu, archive, mailer, auth, timetrack  # noqa: E402
try:
    from app import pdf_form
except Exception:  # PyMuPDF optional
    pdf_form = None

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
    {"key": "beherbergungssteuer", "label": "Beherbergungssteuer", "icon": "receipt_long"},
    {"key": "zeiterfassung", "label": "Zeiterfassung", "icon": "schedule"},
]
ROLE_AREAS = {
    "admin": {a["key"] for a in AREAS},   # Admin sieht alles
    "putzkraft": {"zeiterfassung"},       # Putzkräfte: Arbeitszeit erfassen
}


def _cur_user():
    return app.storage.user.get("user", "")


def _cur_role():
    return app.storage.user.get("role", "")


def _is_admin():
    return _cur_role() == "admin"


def _role_areas(role):
    return ROLE_AREAS.get(role, set())


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
    import json
    import urllib.parse
    import urllib.request
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": address, "format": "json", "limit": 1})
    req = urllib.request.Request(url, headers={"User-Agent": "LIVARO-Suites/1.0 (zeiterfassung)"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            res = json.load(r)
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


def _loc_text(loc):
    if not loc or loc.get("error"):
        return "⚠️ " + (loc.get("error", "kein Standort") if loc else "kein Standort")
    return f"{loc['lat']:.4f}, {loc['lon']:.4f} (±{round(loc.get('acc', 0))} m)"


def _t(iso):
    return iso[11:16] if iso and len(iso) >= 16 else ""


def _d(iso):
    return iso[:10] if iso else ""


def _export_csv(rows, show_user):
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow((["Mitarbeiter"] if show_user else []) +
               ["Datum", "Check-in", "Ort/Netz ein", "Check-out", "Ort/Netz aus", "Dauer"])
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
        {"name": "lin", "label": "Ort/Netz ein", "field": "lin", "align": "left"},
        {"name": "cout", "label": "Check-out", "field": "cout", "align": "left"},
        {"name": "lout", "label": "Ort/Netz aus", "field": "lout", "align": "left"},
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
            if not (path in _UNRESTRICTED or path.startswith("/_nicegui")
                    or path.startswith("/api/")):
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


# ---------------------------------------------------------------- Webhook / API
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
            if (new_pw.value or "").strip():
                if len(new_pw.value.strip()) < 6:
                    ui.notify("Passwort zu kurz (min. 6).", type="warning"); return
                u["password_hash"] = auth.hash_password(new_pw.value.strip())
                data.save_config()
                ui.notify("Passwort geändert.", type="positive")
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
        render()

        ui.separator()
        ui.label("Neuen Benutzer anlegen").classes("font-medium")
        with ui.row().classes("w-full items-end gap-2"):
            nu = ui.input("Benutzername").props("dense outlined")
            npw = ui.input("Passwort", password=True).props("dense outlined")
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
                               "role": nrole.value, "totp_secret": "", "name": name}
                data.save_config()
                ui.notify(f"Benutzer {name} angelegt.", type="positive")
                nu.value = ""; npw.value = ""; render()
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
            t_orte = ui.tab("Standorte", icon="wifi")
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
                                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                                    nm = ui.input("Name", value=o.get("name", "")) \
                                        .props("dense outlined").classes("w-40")
                                    addr = ui.input("Adresse", value=o.get("address", "")) \
                                        .props("dense outlined").classes("flex-grow")
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

        def save():
            for key in inputs:
                betr[key] = inputs[key].value or ""
            v = sig_x.value
            CFG["unterschrift_x"] = int(v) if v == int(v) else v
            CFG["steuersatz"] = round((steuer_pct.value or 6) / 100, 4)
            CFG["archiv_spiegel"] = spiegel.value or ""
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


# ---------------------------------------------------------------- Hauptseite
@ui.page("/")
def main_page():
    ui.colors(primary="#5E2A84", secondary="#8A5CC2", accent="#C8A96E",
              positive="#16a34a", negative="#dc2626", dark="#2D2D2D")
    ui.query("body").classes("bg-[#F5F2EB]")
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

    content = ui.column().classes("w-full max-w-6xl mx-auto p-6 gap-5")
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

    builders = {"beherbergungssteuer": build_beherbergungssteuer,
                "zeiterfassung": build_zeiterfassung}

    def activate(key):
        nav.clear()
        with nav:
            for a in visible:
                on = a["key"] == key
                cls = ("items-center gap-2 mx-2 px-2 py-2 rounded-lg no-wrap cursor-pointer " +
                       ("bg-violet-50 text-primary" if on else "text-slate-600 hover:bg-slate-100"))
                row = ui.row().classes(cls)
                with row:
                    ui.icon(a["icon"]).classes("text-xl")
                    ui.label(a["label"]).classes("font-medium")
                row.on("click", lambda e, k=a["key"]: activate(k))
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
