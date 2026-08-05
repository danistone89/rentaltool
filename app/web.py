#!/usr/bin/env python3
"""Einstieg der Anwendung: Zeitzone, Login-Schranke, Routen, Hauptseite.

Start:  python3 app/web.py   (Port aus config.json, Default 3001)
Öffnen: http://localhost:3001/

Die Oberfläche liegt in `app/ui/` – ein Modul je Bereich (siehe `app/ui/basis.py`
für die gemeinsame Grundlage). Hier steht nur noch, was die ganze Anwendung
betrifft: Prozess-Zeitzone, statische Dateien, Login-Schranke, die beiden
API-Routen und das Gerüst der Hauptseite mit der Bereichs-Navigation.

Die Namen, die hier aus `app.ui.*` hereingeholt werden, sind zugleich die
öffentliche Fläche des Moduls: Tests greifen weiterhin über `web.…` darauf zu.
"""
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

from app import (data, smoobu, archive, mailer, auth, timetrack, housekeeping,  # noqa: E402,F401
                 bookings, receipts, feiertage, i18n, ical, mode)
from app.ui import basis, belege, buchungen, dialog, einstellungen  # noqa: E402,F401
from app.ui import kalender, reinigung, standort, steuer, zeiten, zugang  # noqa: E402,F401
from app.ui.basis import (AREAS, AUTH, CFG, ROLE_AREAS, ROLES, STORAGE_SECRET,  # noqa: E402,F401
                          USERS, _APARTMENTS, _apts, _checklisten_an, _cur_area,
                          _cur_role, _cur_user, _is_admin, _load_apartments,
                          _probe_hinweis, _role_areas, _role_label, _t, logo, t)
from app.ui.belege import render_belege  # noqa: E402,F401
from app.ui.buchungen import (_booking_status, _open_checkliste,  # noqa: E402,F401
                              _PENDING_REINIGUNG, _staff_users, render_buchungen)
from app.ui.einstellungen import open_settings  # noqa: E402,F401
from app.ui.reinigung import reinigung_uebersicht, render_reinigung  # noqa: E402,F401
from app.ui.standort import (_geo_enabled, _match_geofence, _presence,  # noqa: E402,F401
                             get_ip, get_location)
from app.ui.steuer import open_archive, render_result  # noqa: E402,F401
from app.ui.zeiten import (_admin_zeiten, _meine_kennzahlen,  # noqa: E402,F401
                           _time_edit_dialog, _zeit_list)
from app.ui.zugang import (_RESET_THROTTLE, logout, open_account,  # noqa: E402,F401
                           open_users)
from app.ui.belege import _SCAN_JS  # noqa: E402,F401

os.makedirs(housekeeping.MEDIA_DIR, exist_ok=True)
app.add_static_files("/media", housekeeping.MEDIA_DIR)


# Pfade ohne Login-Zwang: Login-Seite, Einladungs-Link, Smoobu-Webhook,
# NiceGUI-Interna.
_UNRESTRICTED = {"/login", "/invite"}


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

# Seiten der Bereiche anmelden. Siehe zugang.seiten_registrieren() – die
# Registrierung ist ein Aufruf und kein Dekorator, weil diese Datei im Testlauf
# je Test erneut ausgeführt wird, die Bereichsmodule aber geladen bleiben.
zugang.seiten_registrieren()

# Aus demselben Grund hier die flüchtigen Zwischenspeicher leeren: im Betrieb
# passiert das einmal beim Start, im Testlauf vor jedem Test.
_APARTMENTS.clear()
zugang._RESET_THROTTLE.clear()
buchungen._PENDING_REINIGUNG.clear()


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
        _probe_hinweis()
        ui.space()
        if _is_admin():
            ui.button("Benutzer", icon="group", on_click=open_users) \
                .props("flat color=primary no-caps")
            ui.button("Einstellungen", icon="settings", on_click=open_settings) \
                .props("flat color=primary no-caps")
        ui.button(t("Mein Konto"), icon="account_circle", on_click=open_account) \
            .props("flat color=primary no-caps")
        ui.button(icon="logout", on_click=logout).props("flat round color=primary") \
            .tooltip(t("Abmelden"))

    with ui.left_drawer(bordered=True).props("width=230").classes("bg-white") as drawer:
        ui.label(t("Bereiche")).classes("text-xs uppercase tracking-wide text-gray-400 px-3 pt-3 pb-1")
        nav = ui.column().classes("w-full gap-1")
        ui.space()
        with ui.column().classes("px-3 pb-3 gap-0"):
            ui.label(_cur_user()).classes("text-sm font-medium text-slate-700")
            ui.label(_role_label(role)).classes("text-xs text-gray-400")

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
                ui.notify(t("Smoobu: {fehler}", fehler=ex), type="negative", timeout=8000)
                return
            if data.LAST_FETCH:
                status.text = f"Daten zuletzt von Smoobu geladen: {data.LAST_FETCH.strftime('%H:%M:%S')} (Cache 5 Min.)"
            render_result(results, result)
            if force:
                ui.notify("Frisch von Smoobu geladen", type="positive")

    def build_zeiterfassung():
        user = _cur_user()
        admin = _is_admin()
        apts = _apts()
        staff = _staff_users()
        _feature_header("schedule", "Zeiterfassung", "Start/Stop, manuell erfassen & bearbeiten")
        # Platz für Dialoge, der beim Neuaufbau von `body` stehen bleibt.
        dlg_slot = ui.element("div")
        body = ui.column().classes("w-full gap-4")

        async def _presence_now():
            """GPS/IP nur abfragen, wenn die Standorterfassung eingeschaltet ist."""
            if not _geo_enabled():
                return None, "", None, None
            ui.notify(t("Standort wird geprüft …"), type="info", timeout=2000)
            loc = await get_location()
            ip = await get_ip()
            gps = None if loc.get("error") else loc
            ort, dist = _match_geofence(gps)
            return gps, ip, ort, dist

        async def do_checkin():
            gps, ip, ort, dist = await _presence_now()
            if timetrack.check_in(user, gps, ip, ort, dist) is None:
                ui.notify(t("Du bist bereits eingecheckt."), type="warning")
            elif not _geo_enabled():
                ui.notify(t("Eingecheckt ✓"), type="positive")
            elif ort:
                ui.notify(t("Eingecheckt ✓ · {ort} ({dist} m)", ort=ort, dist=dist), type="positive")
            elif gps:
                ui.notify(t("Eingecheckt ✓ · ⚠️ nicht am Objekt (nächstes {dist} m)", dist=dist),
                          type="warning", timeout=9000)
            else:
                ui.notify(t("Eingecheckt ✓ · ⚠️ kein Standort – bitte Ortung aktivieren."),
                          type="warning", timeout=10000)
            render()

        async def do_checkout():
            gps, ip, ort, dist = await _presence_now()
            if timetrack.check_out(user, gps, ip, ort, dist) is None:
                ui.notify(t("Kein offener Check-in."), type="warning")
            else:
                ui.notify(t("Ausgecheckt ✓ · {ort} ({dist} m)", ort=ort, dist=dist) if ort
                          else t("Ausgecheckt ✓"), type="positive")
            render()

        def render():
            body.clear()
            with body:
                with ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100 items-start gap-2"):
                    oe = timetrack.get_open(user)
                    if oe:
                        ui.label(t("Eingecheckt seit {zeit} Uhr", zeit=_t(oe["checkin"]))) \
                            .classes("text-lg font-medium text-green-700")
                        _nachweis = _presence(oe.get("checkin_ort"), oe.get("checkin_dist"),
                                              oe.get("checkin_loc"), oe.get("checkin_ip"))
                        if _nachweis:
                            ui.label(t("Nachweis: ") + _nachweis).classes("text-xs text-gray-500")
                        ui.button(t("Check-out"), icon="logout", on_click=do_checkout) \
                            .props("unelevated size=lg color=negative")
                    else:
                        ui.label(t("Nicht eingecheckt")).classes("text-gray-500")
                        ui.button(t("Check-in"), icon="login", on_click=do_checkin) \
                            .props("unelevated size=lg")
                ui.button(t("Zeit manuell erfassen"), icon="add",
                          on_click=lambda: _time_edit_dialog(user, apts, admin, staff, on_saved=render)) \
                    .props("outline no-caps")
                _meine_kennzahlen(user)
                _zeit_list(timetrack.entries(user), apts, admin, staff, render, t("Meine Zeiten"), False)
                if admin:
                    ui.separator()
                    ui.label("Auswertung (Admin)").classes("text-lg font-semibold")
                    _admin_zeiten(apts, staff, render, dlg_slot)
        render()

    def build_reinigung():
        render_reinigung(activate)

    def build_uebersicht():
        reinigung_uebersicht(activate)

    def build_buchungen():
        render_buchungen(activate)

    def build_belege():
        render_belege()

    builders = {"buchungen": build_buchungen,
                "uebersicht": build_uebersicht,
                "beherbergungssteuer": build_beherbergungssteuer,
                "reinigung": build_reinigung,   # kein Menüpunkt; Ziel von _open_checkliste
                "belege": build_belege,
                "zeiterfassung": build_zeiterfassung}

    _BASE_NAV = "items-center gap-2 mx-2 px-2 py-2 rounded-lg no-wrap cursor-pointer "
    nav_rows = {}
    with nav:
        for a in visible:
            row = ui.row().classes(_BASE_NAV).mark(f"nav-{a['key']}")
            with row:
                ui.icon(a["icon"]).classes("text-xl")
                ui.label(t(a["label"])).classes("font-medium")
            row.on("click", lambda e, k=a["key"]: activate(k))
            nav_rows[a["key"]] = row

    def activate(key):
        # "reinigung" ist kein Menüpunkt, sondern ein Zwischenschritt – der
        # merkt sich nicht als Rücksprungziel.
        if key != "reinigung":
            app.storage.user["area"] = key
        for k, row in nav_rows.items():
            row.classes(replace=_BASE_NAV + (
                "bg-violet-50 text-primary" if k == key else "text-slate-600 hover:bg-slate-100"))
        content.clear()
        with content:
            builders.get(key, lambda: None)()

    if visible:
        # Nach einem Neuladen dort weitermachen, wo man war. Sonst landet man
        # jedes Mal auf der Startseite – auch nach Aktionen, die die Seite neu
        # laden (z. B. „Schaden erledigt“ in der Übersicht).
        erlaubt = [a["key"] for a in visible]
        start = _cur_area(erlaubt[0])
        activate(start if start in erlaubt else erlaubt[0])
    else:
        with content:
            with ui.card().classes("w-full rounded-xl p-8 items-center gap-2"):
                ui.icon("lock").classes("text-5xl text-gray-300")
                ui.label(t("Willkommen, {name}!", name=_cur_user())).classes("text-lg font-medium text-slate-700")
                ui.label(t("Für deinen Zugang sind noch keine Bereiche freigeschaltet.")) \
                    .classes("text-gray-500")


def run():
    ui.run(host="127.0.0.1", port=int(CFG.get("port", 3001)),
           title="LIVARO Suites", reload=False, show=False,
           storage_secret=STORAGE_SECRET)


if __name__ in {"__main__", "__mp_main__"}:
    run()
