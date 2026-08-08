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
                 bookings, receipts, feiertage, i18n, ical, mode, rechte)
from app.ui import basis, belege, buchungen, dialog, einstellungen, ton  # noqa: E402,F401
from app.ui import pwa  # noqa: E402,F401
from app.ui import ueberblick as ui_ueberblick  # noqa: E402,F401
from app.ui import kalender, kontoblatt, rechnungen, reinigung, standort, steuer, zeiten, zugang  # noqa: E402,F401
from app.ui.basis import (AREAS, AUTH, BAR_PLAETZE, CFG, ROLE_AREAS, ROLES,  # noqa: E402,F401
                          STORAGE_SECRET, USERS, _APARTMENTS, _apts,
                          _checklisten_an, _cur_area, _cur_role, _cur_user,
                          _darf, _is_admin, _lang_select, _load_apartments,
                          _probe_hinweis, _role_areas, _role_label, _t, logo,
                          nav_plan, platz_von, t)
from app.ui.belege import render_belege  # noqa: E402,F401
from app.ui.buchungen import (_booking_status, _open_checkliste,  # noqa: E402,F401
                              _PENDING_REINIGUNG, _staff_users, nav_zaehler,
                              render_buchungen)
from app.ui.einstellungen import open_settings  # noqa: E402,F401
from app.ui.reinigung import reinigung_uebersicht, render_reinigung  # noqa: E402,F401
from app.ui.standort import (_geo_enabled, _match_geofence, _presence,  # noqa: E402,F401
                             get_ip, get_location)
from app.ui.steuer import (open_archive, render_meldungen,  # noqa: E402,F401
                           render_result)
from app.ui.zeiten import (_admin_zeiten, _meine_kennzahlen,  # noqa: E402,F401
                           _time_edit_dialog, _zeit_list, lohn_vorschau,
                           team_vorschau)
from app.ui.zugang import (_RESET_THROTTLE, logout, open_account,  # noqa: E402,F401
                           open_users)
from app.ui.belege import _SCAN_JS  # noqa: E402,F401

os.makedirs(housekeeping.MEDIA_DIR, exist_ok=True)
app.add_static_files("/media", housekeeping.MEDIA_DIR)


# Pfade ohne Login-Zwang: Login-Seite, Einladungs-Link, Smoobu-Webhook,
# NiceGUI-Interna – und alles, was die Handy-App braucht.
#
# Letzteres ist keine Kleinigkeit: das Handy holt Manifest und Icon, **bevor**
# sich jemand anmeldet. Landen sie auf der Anmeldeseite, bekommt iOS HTML statt
# eines Icons – das Symbol auf dem Home-Bildschirm bliebe grau, und der Service
# Worker ließe sich gar nicht erst registrieren.
_UNRESTRICTED = {"/login", "/invite", "/manifest.webmanifest", "/sw.js", "/offline",
                 "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if not app.storage.user.get("authenticated", False):
            path = request.url.path
            # /media = in der UI eingebettete Fotos (zufällige UUID-Dateinamen);
            # app.storage.user ist bei Static-Requests nicht verlässlich verfügbar,
            # daher hier durchlassen statt auf /login umzuleiten.
            # /static = Icons der Handy-App (siehe oben).
            if not (path in _UNRESTRICTED or path.startswith("/_nicegui")
                    or path.startswith("/api/") or path.startswith("/media/")
                    or path.startswith("/static/")):
                app.storage.user["referrer"] = path
                return RedirectResponse("/login")
        return await call_next(request)


app.add_middleware(AuthMiddleware)

# Seiten und Routen der Bereiche anmelden – ein Aufruf und kein Dekorator, weil
# diese Datei im Testlauf je Test erneut ausgeführt wird, die Bereichsmodule
# aber geladen bleiben (siehe zugang.seiten_registrieren()).
zugang.seiten_registrieren()
pwa.routen_registrieren()

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
    pwa.kopf()
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
    /* Leiste unten (Handy). Sie sitzt ueber dem Home-Balken des iPhones,
       sonst tippt man daneben. Der aktive Platz ist doppelt markiert –
       Farbe UND Strich: Farbe allein traegt nicht, wenn die Sonne aufs
       Display faellt oder jemand Farben schlecht unterscheidet. */
    /* Auf den neuen iPhones (17 Pro) schnitt das Gehaeuse die aeusseren
       Beschriftungen an: "Buchungen" links und "Menue" rechts lagen in der
       Rundung der Displayecke. `safe-area-inset-bottom` allein reicht dafuer
       nicht – der Inset beschreibt den Home-Balken, nicht den Eckradius.
       Deshalb dreierlei: mehr Luft nach unten als der reine Inset, ein
       Mindestabstand zu beiden Seiten, und eine hoehere Leiste, damit die
       Schrift ueber der Rundung sitzt. Die Hoehe steht als Variable, weil das
       Menue-Blatt (.nav-blatt) genau darauf aufsetzt. */
    :root { --leiste-hoehe: 66px; --leiste-seite: 14px; }
    .nav-leiste {
        padding-bottom: max(env(safe-area-inset-bottom), 10px);
        padding-left: max(env(safe-area-inset-left), var(--leiste-seite));
        padding-right: max(env(safe-area-inset-right), var(--leiste-seite));
    }
    /* Checklisten-Aufgabe: der Text ist Teil des Kaestchens, damit die ganze
       Zeile das Tap-Ziel ist. Erledigtes bleibt durchgestrichen lesbar. */
    .aufgabe .q-checkbox__label { font-size:.875rem; color:#334155; line-height:1.3; }
    .aufgabe-erledigt .q-checkbox__label { text-decoration:line-through; color:#9ca3af; }
    .nav-platz { color:#64748b; min-height: var(--leiste-hoehe); }
    /* Das Menue-Blatt endet ueber der Leiste, statt sie zu verdecken: sonst
       ist waehrend des Blaetterns nicht mehr zu sehen, in welchem Bereich man
       steht – und ohne Adressleiste ist die Leiste die einzige Orientierung. */
    .nav-blatt { margin-bottom: calc(var(--leiste-hoehe)
                                + max(env(safe-area-inset-bottom), 10px)); }
    .nav-platz .nav-strich { position:absolute; top:0; left:50%;
        transform:translateX(-50%); width:26px; height:3px;
        border-radius:0 0 3px 3px; background:transparent; }
    /* Der Zaehler gehoert sichtbar zu SEINEM Symbol. Quasars "floating" setzt
       ihn ausserhalb des Platzes – er stand dann ueber dem Nachbarn und las
       sich, als zaehle der. */
    .nav-platz .nav-zaehler { position:absolute; top:-5px; left:13px;
        min-width:16px; height:16px; padding:0 4px; font-size:10px;
        line-height:16px; font-weight:700; }
    .nav-platz.nav-aktiv { color:#5E2A84; }
    .nav-platz.nav-aktiv .nav-strich { background:#5E2A84; }
    .nav-platz.nav-aktiv .nav-etikett { font-weight:650; }
    """)
    today = date.today()
    role = _cur_role()
    leiste_plan, menue_plan = nav_plan(role)
    visible = leiste_plan + menue_plan

    # Die Kopfzeile ist schlank: Logo und – auf der Probe-Instanz – das orange
    # Kennzeichen. Benutzer, Einstellungen, Mein Konto und Abmelden stehen im
    # Menue; das gibt am Handy eine Zeile Inhalt zurueck.
    with ui.header(elevated=True).classes("items-center px-4 bg-white text-slate-800 border-b border-slate-200"):
        logo(42)
        _probe_hinweis()

    # Ab Tablet bleibt die Schublade links (Quasar blendet sie unter 1024 px
    # selbst aus, dort uebernimmt die Leiste unten).
    with ui.left_drawer(bordered=True).props("width=248 show-if-above breakpoint=1024") \
            .classes("bg-white") as drawer:
        schublade = ui.column().classes("w-full gap-0 grow")
        with ui.column().classes("px-4 pb-3 gap-0"):
            ui.label(_cur_user()).classes("text-sm font-medium text-slate-700")
            ui.label(_role_label(role)).classes("text-xs text-slate-400")

    # Das Menue faehrt von unten aus und bleibt damit in Daumennaehe.
    menue_blatt = ui.dialog().props("position=bottom")

    # Hinweise stehen NEBEN dem Bereichsinhalt, nicht darin: `activate()` leert
    # `content` bei jedem Bereichswechsel. Der PWA-Hinweis stand seit AP6 darin
    # und war deshalb nach dem ersten Klick weg – gemerkt hat das niemand, weil
    # er ohnehin erst im Browser sichtbar wird.
    hinweise = ui.column().classes("w-full max-w-6xl mx-auto px-3 sm:px-6 pt-3 gap-2")
    with hinweise:
        zugang.zwei_faktor_hinweis()
        pwa.einrichten_banner()

    content = ui.column().classes("w-full max-w-6xl mx-auto p-3 sm:p-6 gap-4 sm:gap-5")

    # Die Kopfzeile steht seit AP-D2 in basis.bereichskopf – vier Bereiche
    # hatten sie vorher Zeile für Zeile nachgebaut.
    _feature_header = basis.bereichskopf

    def build_beherbergungssteuer():
        apts = _load_apartments()
        _feature_header("receipt_long", "Beherbergungssteuer", "Dresden · monatliche Steueranmeldung",
                        lambda: ui.button("Archiv", icon="inventory_2",
                                          on_click=open_archive).props("outline no-caps")
                        .mark("steuer-archiv"))
        # Zuerst, was ansteht – erst danach der Rechner. Wer den Bereich
        # oeffnet, will meistens wissen, ob noch etwas offen ist.
        render_meldungen(lambda: activate("beherbergungssteuer"))
        with ui.card().classes(ton.KARTE):
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
                    .classes("text-xs text-slate-500")
                ui.space()
                status = ui.label("").classes("text-xs text-slate-400")
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
                with ui.card().classes(ton.KARTE + " items-start gap-2"):
                    oe = timetrack.get_open(user)
                    if oe:
                        ui.label(t("Eingecheckt seit {zeit} Uhr", zeit=_t(oe["checkin"]))) \
                            .classes("text-lg font-medium text-green-700")
                        _nachweis = _presence(oe.get("checkin_ort"), oe.get("checkin_dist"),
                                              oe.get("checkin_loc"), oe.get("checkin_ip"))
                        if _nachweis:
                            ui.label(t("Nachweis: ") + _nachweis).classes("text-xs text-slate-500")
                        ui.button(t("Check-out"), icon="logout", on_click=do_checkout) \
                            .props("unelevated size=lg color=negative")
                    else:
                        ui.label(t("Nicht eingecheckt")).classes("text-slate-500")
                        ui.button(t("Check-in"), icon="login", on_click=do_checkin) \
                            .props("unelevated size=lg")
                ui.button(t("Zeit manuell erfassen"), icon="add",
                          on_click=lambda: _time_edit_dialog(user, apts, admin, staff, on_saved=render)) \
                    .props("outline no-caps")
                # Erst was kommt, dann was war: wer sich Reinigungen nimmt,
                # will wissen, worauf er zulaeuft – nicht nur, was schon war.
                lohn_vorschau(user, buchungen._cleaning_jobs(quiet=True))
                _meine_kennzahlen(user)
                _zeit_list(timetrack.entries(user), apts, admin, staff, render, t("Meine Zeiten"), False)
                if _darf(rechte.ZEITEN_FREMDE):
                    ui.separator()
                    # Zuerst die Frage, die beim Zuweisen gestellt wird.
                    team_vorschau(buchungen._cleaning_jobs(quiet=True), staff)
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

    def build_rechnungen():
        rechnungen.render_rechnungen(activate)

    def build_konto():
        kontoblatt.render_konto()

    def build_ueberblick():
        ui_ueberblick.render_ueberblick()

    def build_einstellungen():
        einstellungen.render_einstellungen()

    builders = {"buchungen": build_buchungen,
                "uebersicht": build_uebersicht,
                "beherbergungssteuer": build_beherbergungssteuer,
                "reinigung": build_reinigung,   # kein Menüpunkt; Ziel von _open_checkliste
                "belege": build_belege,
                "rechnungen": build_rechnungen,
                "konto": build_konto,
                "ueberblick": build_ueberblick,
                "einstellungen": build_einstellungen,
                "zeiterfassung": build_zeiterfassung}

    # ------------------------------------------------------------ Navigation
    # Leiste unten (Handy), Schublade links (ab Tablet) und das Menue-Blatt
    # entstehen aus EINER Liste – siehe basis.nav_plan(). Zwei getrennt
    # gepflegte Listen laufen garantiert auseinander.
    # "flex flex-row" bzw. "flex flex-col" muessen hier drinstehen: das Markieren
    # unten setzt die Klassen per replace= neu und wirft dabei auch NiceGUIs
    # eigene .nicegui-row/.nicegui-column weg – ohne sie faellt das Element auf
    # display:block zurueck, und Symbol und Beschriftung rutschen auseinander.
    _BASE_NAV = ("flex flex-row items-center gap-3 mx-2 px-3 py-2 rounded-lg "
                 "no-wrap cursor-pointer min-h-[44px] ")
    _BASE_PLATZ = ("nav-platz flex flex-col items-center justify-center gap-1 "
                   "py-1.5 px-1 cursor-pointer relative ")
    nav_rows = {}     # Schublade: key -> Zeile
    bar_slots = {}    # Leiste: key -> Platz ("menue" fuer den vierten)

    def _bereichszeile(area, marker):
        row = ui.row().classes(_BASE_NAV).mark(marker)
        with row:
            ui.icon(area["icon"]).classes("text-xl")
            ui.label(t(area["label"])).classes("font-medium text-sm")
        row.on("click", lambda e, k=area["key"]: activate(k))
        return row

    def _menue_zeile(icon, text, on_click, marker, klasse=""):
        zeile = ui.row().classes(
            "items-center gap-3 mx-2 px-3 py-2 rounded-lg no-wrap cursor-pointer "
            "min-h-[44px] hover:bg-slate-100 " + klasse).mark(marker)
        with zeile:
            ui.icon(icon).classes("text-xl")
            ui.label(text).classes("text-sm")
        zeile.on("click", on_click)
        return zeile

    def _gruppe(titel):
        ui.label(t(titel)).classes(
            "text-[11px] uppercase tracking-wider text-slate-400 px-5 pt-3 pb-1")

    def _menue_inhalt(bereiche, gruppentitel, praefix, danach=None):
        """Menue-Inhalt – einmal fuer das Blatt von unten, einmal fuer die
        Schublade. `danach` schliesst das Blatt, bevor ein Dialog aufgeht."""
        def _tap(fn):
            def _run():
                if danach:
                    danach()
                fn()
            return _run

        if bereiche:
            _gruppe(gruppentitel)
            for area in bereiche:
                nav_rows[(praefix, area["key"])] = _bereichszeile(
                    area, f"{praefix}-{area['key']}")
        _gruppe("Mein Zugang")
        _menue_zeile("account_circle", t("Mein Konto"), _tap(open_account),
                     f"{praefix}-konto")
        with ui.element("div").classes("px-4 py-2 w-full"):
            _lang_select().classes("w-full")
        if _is_admin():
            _gruppe("Verwaltung")
            _menue_zeile("group", t("Benutzer"), _tap(open_users), f"{praefix}-benutzer")
            # „Einstellungen“ steht nicht mehr hier: sie sind seit dem Umbau ein
            # eigener Bereich und erscheinen weiter oben in der Bereichsliste –
            # zweimal derselbe Eintrag wäre nur verwirrend.
            _menue_zeile("inventory_2", t("Archiv"), _tap(open_archive), f"{praefix}-archiv")
        ui.separator().classes("my-2")
        _menue_zeile("logout", t("Abmelden"), _tap(logout), f"{praefix}-abmelden",
                     klasse="text-red-700")

    def _platz(key, label, icon, on_click=None, zaehler=0):
        slot = ui.column().classes(_BASE_PLATZ).mark(f"bar-{key}")
        with slot:
            ui.element("div").classes("nav-strich")
            with ui.element("div").classes("relative leading-none"):
                ui.icon(icon).classes("text-2xl")
                if zaehler:
                    ui.badge(str(zaehler)).props("color=warning rounded") \
                        .classes("nav-zaehler").mark(f"bar-zaehler-{key}")
            ui.label(t(label)).classes(
                "nav-etikett text-[11px] leading-tight text-center truncate max-w-full")
        slot.on("click", on_click or (lambda e, k=key: activate(k)))
        bar_slots[key] = slot
        return slot

    # Schublade (ab Tablet): alle Bereiche, danach Zugang und Verwaltung.
    with schublade:
        _menue_inhalt(visible, "Bereiche", "nav")

    # Menue-Blatt (Handy): nur, was nicht in die Leiste passt – plus Zugang.
    with menue_blatt, ui.card().classes(
            "nav-blatt w-full m-0 p-0 pb-3 rounded-t-2xl rounded-b-none gap-0"):
        ui.element("div").classes("w-9 h-1 rounded bg-slate-200 mx-auto mt-2 mb-1")
        _menue_inhalt(menue_plan, "Weitere Bereiche", "menu", danach=menue_blatt.close)

    # Leiste unten (Handy): drei Bereiche, vierter Platz immer das Menue.
    if visible:
        with ui.footer(fixed=True).classes(
                "nav-leiste lg:hidden bg-white border-t border-slate-200 p-0"):
            with ui.element("div").classes("w-full grid grid-cols-4"):
                for a in leiste_plan:
                    _platz(a["key"], a["bar_label"], a["icon"],
                           zaehler=(nav_zaehler(_cur_user(), role in ("admin", "manager"))
                                    if a["key"] == "buchungen" else 0))
                _platz("menue", "Menü", "menu", on_click=menue_blatt.open)

    def activate(key):
        # "reinigung" ist kein Menuepunkt, sondern ein Zwischenschritt – der
        # merkt sich nicht als Ruecksprungziel.
        if key != "reinigung":
            app.storage.user["area"] = key
        menue_blatt.close()
        platz = platz_von(key)
        for (_praefix, k), row in nav_rows.items():
            row.classes(replace=_BASE_NAV + (
                "bg-violet-50 text-primary" if k == platz
                else "text-slate-600 hover:bg-slate-100"))
        # Liegt der Bereich im Menue, leuchtet der Menue-Platz – sonst waere in
        # der Leiste nirgends zu sehen, wo man ist.
        if platz not in bar_slots:
            platz = "menue"
        for k, slot in bar_slots.items():
            slot.classes(replace=_BASE_PLATZ + ("nav-aktiv" if k == platz else ""))
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
            with ui.card().classes("w-full rounded-xl"):
                basis.leer("lock", t("Willkommen, {name}!", name=_cur_user()),
                           t("Für deinen Zugang sind noch keine Bereiche freigeschaltet."))


def run():
    ui.run(host="127.0.0.1", port=int(CFG.get("port", 3001)),
           title="LIVARO Suites", reload=False, show=False,
           storage_secret=STORAGE_SECRET)


if __name__ in {"__main__", "__mp_main__"}:
    run()
