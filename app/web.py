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

from app import (data, smoobu, archive, mailer, auth, timetrack, housekeeping,  # noqa: E402
                 bookings, receipts, feiertage, i18n)
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


# ---- Sprache ---------------------------------------------------------------
def _lang():
    """Sprache des aktuellen Benutzers: Session, sonst Benutzerprofil, sonst DE."""
    code = app.storage.user.get("lang")
    if not code:
        code = (USERS.get(app.storage.user.get("user", ""), {}) or {}).get("lang")
    return code or i18n.DEFAULT


i18n.set_resolver(_lang)
t = i18n.t


def _set_lang(code):
    """Sprache für Session und Benutzerprofil setzen und Seite neu aufbauen."""
    code = code if code in i18n.LANGUAGES else i18n.DEFAULT
    app.storage.user["lang"] = code
    u = USERS.get(_cur_user())
    if u is not None:
        u["lang"] = code
        data.save_config()
    ui.navigate.reload()


def _lang_select(**kwargs):
    """Sprachauswahl als Dropdown."""
    return ui.select(i18n.LANGUAGES, value=_lang(), label=t("Sprache"),
                     on_change=lambda e: _set_lang(e.value), **kwargs) \
        .props("outlined dense")


DEFAULT_APP_URL = "https://app.ds-apartments.de"


def _app_url():
    """Öffentliche Adresse der App – für Links in E-Mails (Einladung, Hinweise)."""
    return (CFG.get("app_url") or DEFAULT_APP_URL).rstrip("/")


ROLES = {"admin": "Administrator", "manager": "Manager", "putzkraft": "Putzkraft"}


def _role_label(role):
    return t(ROLES.get(role, role or ""))

# Bereiche (Features). Welche Rolle was sieht, wird über ROLE_AREAS gesteuert –
# die feinen Rechte definieren wir später, hier nur das Grundgerüst.
AREAS = [
    {"key": "buchungen", "label": "Buchungen", "icon": "calendar_month"},
    {"key": "uebersicht", "label": "Übersicht", "icon": "insights"},
    {"key": "belege", "label": "Belege", "icon": "receipt"},
    {"key": "zeiterfassung", "label": "Zeiterfassung", "icon": "schedule"},
    {"key": "beherbergungssteuer", "label": "Beherbergungssteuer", "icon": "receipt_long"},
]
# "reinigung" ist KEIN Menüpunkt mehr – die Checkliste wird aus einer Buchung geöffnet
# (activate('reinigung') via _open_checkliste). "uebersicht" ist die Admin-Auswertung.
ROLE_AREAS = {
    "admin": {a["key"] for a in AREAS},          # Admin sieht alles
    # Manager: operative Koordination (Übersicht + Checklisten/Einkauf/Schäden-Konfig),
    # aber keine Steuer, keine Benutzer-/Einstellungsverwaltung.
    "manager": {"buchungen", "uebersicht", "belege", "zeiterfassung"},
    "putzkraft": {"buchungen", "belege", "zeiterfassung"},  # Putzkräfte
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
                ui.label(t("Noch keine Einträge.")).classes("text-sm text-gray-400")

def _month_label(m):
    try:
        return f"{_MONATE[int(m[5:7]) - 1]} {m[:4]}"
    except Exception:
        return m


# --- Abrechnungslogik Steuerberater: Meldung zum 19., Übertrag danach -----------
def _billing_month(iso):
    """Abrechnungsmonat: Tage ab dem 19. zählen zum Folgemonat (Meldung zum 19.)."""
    d = date.fromisoformat(iso[:10])
    y, m = d.year, d.month
    if d.day >= 19:
        m += 1
        if m > 12:
            m = 1; y += 1
    return f"{y:04d}-{m:02d}"


def _billing_period(ym):
    """(Start, Ende) des Abrechnungsmonats: 19. Vormonat bis 18. des Monats."""
    y, m = int(ym[:4]), int(ym[5:7])
    end = date(y, m, 18)
    pm, py = (12, y - 1) if m == 1 else (m - 1, y)
    return date(py, pm, 19), end


def _hours_num(minutes):
    s = f"{minutes / 60.0:.1f}".replace(".", ",")
    return s[:-2] if s.endswith(",0") else s


def _esc_attr(v):
    """Text für ein HTML-Attribut entschärfen (ui.html wird roh eingebettet)."""
    return (str(v).replace("&", "&amp;").replace('"', "&quot;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def _eur(betrag):
    """1234.5 -> '1.234,50 €'"""
    return f"{betrag:,.2f}".replace(",", "#").replace(".", ",").replace("#", ".") + " €"


def _rate_defaults():
    """Globale Vorgabe-Stundensätze aus den Einstellungen."""
    return {"stundensatz_werktag": CFG.get("stundensatz_werktag", ""),
            "stundensatz_wochenende": CFG.get("stundensatz_wochenende", "")}


def _zeit_aggregat(rows):
    """Zeiten je Mitarbeiter nach Tagesart, inkl. Beträgen aus den Stundensätzen."""
    return timetrack.aggregate(rows, USERS, _rate_defaults())


def _has_rates():
    """Sind überhaupt Stundensätze gepflegt? Sonst Beträge ausblenden."""
    d = _rate_defaults()
    if any(str(v).strip() for v in d.values()):
        return True
    return any(str(u.get(k, "")).strip()
               for u in USERS.values()
               for k in ("stundensatz_werktag", "stundensatz_wochenende"))


def _zeit_csv_bytes(rows, show_user):
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow((["Mitarbeiter"] if show_user else []) +
               ["Datum", "Von", "Bis", "Wohnung", "Dauer", "Minuten",
                "Tagesart", "Anlass", "Stundensatz", "Betrag", "Ort ein"])
    defaults = _rate_defaults()
    for e in rows:
        mins = timetrack.duration_minutes(e) or 0
        d = timetrack.entry_date(e)
        kind = timetrack.kind_of(e)
        rate = timetrack.rate_for(kind, USERS.get(e["user"]), defaults)
        w.writerow((([e["user"]] if show_user else []) + [
            _d(e["checkin"]), _t(e["checkin"]),
            _t(e["checkout"]) if e.get("checkout") else "",
            e.get("apartment") or "", timetrack.fmt_dur(mins), mins,
            feiertage.LABELS[kind], feiertage.label_of(d),
            f"{rate:.2f}".replace(".", ",") if rate else "",
            f"{timetrack.amount(mins, rate):.2f}".replace(".", ",") if rate else "",
            _presence(e.get("checkin_ort"), e.get("checkin_dist"),
                      e.get("checkin_loc"), e.get("checkin_ip"))]))
    return buf.getvalue().encode("utf-8-sig")


def _time_edit_dialog(default_user, apts, admin, staff, entry=None, on_saved=None):
    from datetime import datetime
    apt_opts = {"": t("— keine Wohnung —"), **{v: v for v in apts.values()}}
    d0 = entry["checkin"][:10] if entry else date.today().isoformat()
    von0 = _t(entry["checkin"]) if entry else "09:00"
    bis0 = _t(entry["checkout"]) if entry and entry.get("checkout") else "11:00"
    with ui.dialog() as dlg, ui.card().classes("w-[420px] max-w-full gap-2"):
        ui.label(t("Zeit bearbeiten") if entry else t("Zeit manuell erfassen")).classes("text-lg font-bold")
        usel = None
        if admin and not entry:
            usel = ui.select({u: (staff.get(u) or u) for u in staff}, value=default_user,
                             label=t("Mitarbeiter")).props("outlined dense").classes("w-full")
        d = ui.input(t("Datum"), value=d0).props("type=date outlined dense").classes("w-full")
        with ui.row().classes("w-full gap-2"):
            t1 = ui.input(t("Von"), value=von0).props("type=time outlined dense").classes("flex-grow")
            t2 = ui.input(t("Bis"), value=bis0).props("type=time outlined dense").classes("flex-grow")
        aptsel = ui.select(apt_opts, value=(entry.get("apartment") if entry else "") or "",
                           label=t("Wohnung")).props("outlined dense").classes("w-full")

        def save():
            try:
                ci = datetime.fromisoformat(f"{d.value}T{t1.value}")
                co = datetime.fromisoformat(f"{d.value}T{t2.value}")
            except Exception:
                ui.notify(t("Bitte Datum und Uhrzeiten prüfen."), type="warning"); return
            if co <= ci:
                ui.notify(t("Ende muss nach Beginn liegen."), type="warning"); return
            apt = aptsel.value or ""
            if entry:
                timetrack.update_entry(entry["id"], checkin=ci, checkout=co, apartment=apt)
            else:
                timetrack.add_manual(usel.value if usel else default_user, ci, co, apartment=apt)
            dlg.close(); ui.notify(t("Gespeichert ✓"), type="positive")
            if on_saved:
                on_saved()
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button(t("Abbrechen"), on_click=dlg.close).props("flat")
            ui.button(t("Speichern"), icon="save", on_click=save).props("unelevated")
    dlg.open()


def _zeit_list(rows, apts, admin, staff, on_change, title, show_user):
    with ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100 gap-1 p-3"):
        with ui.row().classes("w-full items-center"):
            ui.label(title).classes("font-medium")
            ui.space()
            if rows:
                ui.button("CSV", icon="download",
                          on_click=lambda: ui.download.content(
                              _zeit_csv_bytes(rows, show_user), "arbeitszeiten.csv",
                              media_type="text/csv")).props("flat dense no-caps")
        if not rows:
            ui.label(t("Noch keine Einträge.")).classes("text-sm text-gray-400"); return
        for e in rows:
            with ui.row().classes("w-full items-center gap-2 no-wrap border-b border-slate-50 py-1"):
                with ui.column().classes("gap-0 min-w-0 flex-grow"):
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        ui.label(f"{_d(e['checkin'])} · {_t(e['checkin'])}–"
                                 + (_t(e['checkout']) if e.get('checkout') else '…')) \
                            .classes("text-sm text-slate-700 truncate")
                        if timetrack.kind_of(e) == feiertage.WOCHENENDE:
                            ui.chip(t(feiertage.label_of(timetrack.entry_date(e)))) \
                                .props("color=amber-7 text-color=white dense square") \
                                .classes("text-[10px] shrink-0")
                    sub = []
                    if show_user:
                        sub.append(staff.get(e["user"], e["user"]))
                    if e.get("apartment"):
                        sub.append(e["apartment"])
                    if e.get("manual") or e.get("edited"):
                        sub.append("manuell")
                    if sub:
                        ui.label(" · ".join(sub)).classes("text-xs text-gray-400 truncate")
                ui.label(timetrack.fmt_dur(timetrack.duration_minutes(e))) \
                    .classes("text-sm font-medium shrink-0")
                ui.button(icon="edit", on_click=lambda ev=e:
                          _time_edit_dialog(ev["user"], apts, admin, staff, entry=ev, on_saved=on_change)) \
                    .props("flat round dense").tooltip(t("Bearbeiten"))
                ui.button(icon="delete", on_click=lambda ev=e:
                          (timetrack.delete_entry(ev["id"]), ui.notify(t("Eintrag gelöscht."), type="warning"),
                           on_change())).props("flat round dense color=negative").tooltip(t("Löschen"))


def _stb_email_body(ym, rows, staff):
    """Vorlagenbasierten Text für den Steuerberater bauen: je Mitarbeiter Stunden
    getrennt nach Werktag und Wochenende/Feiertag, mit Beträgen aus den
    hinterlegten Stundensätzen. Meldezeitraum endet am 18."""
    start, end = _billing_period(ym)
    monat = _MONATE[int(ym[5:7]) - 1]
    anrede = CFG.get("steuerberater_anrede") or "Sehr geehrte Damen und Herren,"
    intro = (CFG.get("steuerberater_intro") or "anbei die Stunden für {monat}.") \
        .replace("{monat}", monat).replace("{jahr}", ym[:4])
    gruss = CFG.get("steuerberater_gruss") or "Mit freundlichen Grüßen"
    agg = _zeit_aggregat(rows)
    money = _has_rates()
    bis = end.strftime("%d.%m.%Y")

    def zeile(text, mins, betrag):
        s = f"{text}: {_hours_num(mins)} Stunden"
        return s + (f" = {_eur(betrag)}" if money and betrag else "")

    blocks = []
    for u in sorted(agg, key=lambda x: -agg[x]["total_minutes"]):
        a = agg[u]
        lines = [f"{staff.get(u, u)}:"]
        wt = a["minutes"][feiertage.WERKTAG]
        we = a["minutes"][feiertage.WOCHENENDE]
        if we > 0:
            lines.append(zeile("Werktags", wt, a["amount"][feiertage.WERKTAG]))
            lines.append(zeile("Wochenende/Feiertag", we, a["amount"][feiertage.WOCHENENDE]))
            lines.append(f"Gesamt: {_hours_num(a['total_minutes'])} Stunden (bis {bis})"
                         + (f" = {_eur(a['total_amount'])}" if money and a["total_amount"] else ""))
        else:
            lines.append(f"{_hours_num(wt)} Stunden (bis {bis})"
                         + (f" = {_eur(a['amount'][feiertage.WERKTAG])}"
                            if money and a["amount"][feiertage.WERKTAG] else ""))
        note = (USERS.get(u, {}) or {}).get("steuer_notiz", "").strip()
        if note:
            lines.append(note)
        blocks.append("\n".join(lines))
    return anrede + "\n\n" + intro + "\n\n" + "\n\n".join(blocks) + "\n\n" + gruss


def _admin_zeiten(apts, staff, on_change):
    all_entries = [e for e in timetrack.entries() if e.get("checkout")]
    months = sorted({_billing_month(e["checkin"]) for e in all_entries}, reverse=True) \
        or [_billing_month(date.today().isoformat())]
    state = {"month": months[0], "user": None}
    box = ui.column().classes("w-full gap-2")

    def render():
        box.clear()
        with box:
            with ui.row().classes("items-end gap-2 flex-wrap"):
                msel = ui.select({m: _month_label(m) for m in months}, value=state["month"],
                                 label="Abrechnungsmonat").props("outlined dense").classes("min-w-[170px]")
                msel.on_value_change(lambda e: (state.update(month=e.value), render()))
                ppl = {None: "Alle Mitarbeiter",
                       **{u: (staff.get(u) or u) for u in sorted({x["user"] for x in all_entries})}}
                usel = ui.select(ppl, value=state["user"], label="Mitarbeiter") \
                    .props("outlined dense").classes("min-w-[180px]")
                usel.on_value_change(lambda e: (state.update(user=e.value), render()))
            st, en = _billing_period(state["month"])
            ui.label(f"Zeitraum {st.strftime('%d.%m.')}–{en.strftime('%d.%m.%Y')} "
                     "(Meldung zum 19., spätere Stunden im Folgemonat)") \
                .classes("text-xs text-gray-500")
            rows = [e for e in all_entries
                    if _billing_month(e["checkin"]) == state["month"]
                    and (state["user"] is None or e["user"] == state["user"])]
            agg = _zeit_aggregat(rows)
            money = _has_rates()
            total = sum(a["total_minutes"] for a in agg.values())
            total_eur = round(sum(a["total_amount"] for a in agg.values()), 2)
            ui.label(f"{_month_label(state['month'])} · Summe {_hours_num(total)} Stunden"
                     + (f" · {_eur(total_eur)}" if money and total_eur else "")) \
                .classes("font-semibold mt-1")
            for u, a in sorted(agg.items(), key=lambda x: -x[1]["total_minutes"]):
                we = a["minutes"][feiertage.WOCHENENDE]
                with ui.row().classes("w-full items-center gap-2"):
                    ui.icon("person").classes("text-primary")
                    with ui.column().classes("gap-0 flex-grow min-w-0"):
                        ui.label(staff.get(u, u)).classes("truncate")
                        if we > 0:
                            ui.label(f"Werktags {_hours_num(a['minutes'][feiertage.WERKTAG])} · "
                                     f"Wochenende/Feiertag {_hours_num(we)} Std") \
                                .classes("text-xs text-gray-400")
                    with ui.column().classes("gap-0 items-end shrink-0"):
                        ui.label(f"{_hours_num(a['total_minutes'])} Std").classes("font-medium")
                        if money and a["total_amount"]:
                            ui.label(_eur(a["total_amount"])).classes("text-xs text-gray-500")

            def send_stb():
                stb = (CFG.get("steuerberater_email") or "").strip()
                if not stb:
                    ui.notify("Keine Steuerberater-E-Mail (Einstellungen → Steuerberater).",
                              type="warning", timeout=8000); return
                if not rows:
                    ui.notify("Keine Zeiten im Zeitraum.", type="warning"); return
                body = _stb_email_body(state["month"], rows, staff)
                try:
                    mailer.send_document(
                        CFG, stb, f"Arbeitszeiten {_month_label(state['month'])} – LIVARO Suites",
                        body, f"arbeitszeiten_{state['month']}.csv", _zeit_csv_bytes(rows, True))
                    ui.notify(f"An {stb} gesendet ✓", type="positive", timeout=8000)
                except mailer.MailError as ex:
                    ui.notify(f"Versand fehlgeschlagen: {ex}", type="negative", timeout=10000)

            def preview():
                with ui.dialog() as dlg, ui.card().classes("w-[480px] max-w-full gap-2"):
                    ui.label("Vorschau E-Mail an Steuerberater").classes("font-bold")
                    ui.label(_stb_email_body(state["month"], rows, staff)) \
                        .classes("text-sm whitespace-pre-wrap")
                    with ui.row().classes("w-full justify-end"):
                        ui.button("Schließen", on_click=dlg.close).props("flat")
                dlg.open()

            with ui.row().classes("gap-2 mt-2 flex-wrap"):
                ui.button("An Steuerberater senden", icon="send", on_click=send_stb) \
                    .props("unelevated no-caps") \
                    .tooltip(CFG.get("steuerberater_email") or "keine E-Mail konfiguriert")
                ui.button("Vorschau", icon="visibility", on_click=preview).props("outline no-caps")
                ui.button("CSV", icon="download",
                          on_click=lambda: ui.download.content(
                              _zeit_csv_bytes(rows, True), f"arbeitszeiten_{state['month']}.csv",
                              media_type="text/csv")).props("outline no-caps")
            _zeit_list(rows, apts, True, staff, on_change, "Einzelne Einträge", True)
    render()


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
            ui.notify(t("Smoobu: {fehler}", fehler=ex), type="negative", timeout=8000)
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
def _finish_login(username, role):
    """Session anlegen und zur Startseite (bzw. zur ursprünglich gewünschten Seite)."""
    app.storage.user["authenticated"] = True
    app.storage.user["user"] = username
    app.storage.user["role"] = role
    # Profilsprache schlägt die am Login-Schirm gewählte Sprache
    profil = (USERS.get(username, {}) or {}).get("lang")
    if profil:
        app.storage.user["lang"] = profil
    ui.navigate.to(app.storage.user.get("referrer") or "/")


@ui.page("/login")
def login_page():
    ui.colors(primary="#5E2A84", secondary="#8A5CC2", accent="#C8A96E",
              positive="#16a34a", negative="#dc2626")
    ui.query("body").classes("bg-[#F5F2EB]")
    if app.storage.user.get("authenticated"):
        ui.navigate.to("/")
        return

    finish2 = _finish_login

    with ui.column().classes("absolute-center items-center gap-4"):
        logo(60)
        with ui.card().classes("w-[360px] max-w-full gap-2 rounded-xl shadow-md"):
            if not USERS:
                ui.label(t("Erst-Einrichtung – Administrator anlegen")).classes("font-semibold")
                un = ui.input(t("Benutzername"), value="admin").classes("w-full")
                p1 = ui.input(t("Passwort"), password=True,
                              password_toggle_button=True).classes("w-full")
                p2 = ui.input(t("Passwort wiederholen"), password=True).classes("w-full")

                def setup():
                    name = (un.value or "").strip()
                    if not name:
                        ui.notify(t("Benutzername fehlt."), type="warning"); return
                    if len(p1.value or "") < 6:
                        ui.notify(t("Passwort mindestens 6 Zeichen."), type="warning"); return
                    if p1.value != p2.value:
                        ui.notify(t("Passwörter stimmen nicht überein."), type="negative"); return
                    USERS[name] = {"password_hash": auth.hash_password(p1.value),
                                   "role": "admin", "totp_secret": "", "name": name,
                                   "lang": _lang()}
                    data.save_config()
                    finish2(name, "admin")
                ui.button(t("Anlegen & anmelden"), on_click=setup) \
                    .props("unelevated").classes("w-full")
            else:
                ui.label(t("Anmelden")).classes("font-semibold")
                un = ui.input(t("Benutzername")).classes("w-full").mark("login-user")
                pw = ui.input(t("Passwort"), password=True,
                              password_toggle_button=True).classes("w-full").mark("login-pw")
                code = ui.input(t("6-stelliger Code (falls 2FA aktiv)")) \
                    .classes("w-full").mark("login-code")

                def do_login():
                    u = USERS.get((un.value or "").strip())
                    if u and not u.get("password_hash"):
                        # Eingeladen, aber noch kein Passwort gesetzt
                        ui.notify(t("Dein Zugang ist noch nicht aktiviert – bitte den Link "
                                    "aus der Einladungs-E-Mail benutzen.")
                                  if auth.invite_state(u) == "offen"
                                  else t("Bitte fordere bei deinem Administrator eine neue "
                                         "Einladung an."),
                                  type="warning", timeout=9000); return
                    if not u or not auth.verify_password(pw.value or "", u.get("password_hash", "")):
                        ui.notify(t("Benutzername oder Passwort falsch."), type="negative"); return
                    if u.get("totp_secret") and not auth.verify_totp(u["totp_secret"], code.value or ""):
                        ui.notify(t("Code fehlt oder ist falsch."), type="negative"); return
                    finish2((un.value or "").strip(), u.get("role", "putzkraft"))
                for f in (un, pw, code):
                    f.on("keydown.enter", lambda: do_login())
                ui.button(t("Anmelden"), on_click=do_login).props("unelevated").classes("w-full")
                ui.button(t("Passwort vergessen?"),
                          on_click=lambda: open_forgot_password(un.value)) \
                    .props("flat dense no-caps").classes("w-full").mark("forgot-open")
        _lang_select().classes("w-[360px] max-w-full")


def logout():
    app.storage.user["authenticated"] = False
    ui.navigate.to("/login")


# ------------------------------------------------------- Passwort vergessen
# Letzter Versand je Konto – bremst wiederholtes Anfordern (auch als Schutz
# gegen fremde Anfragen, die das Postfach eines Mitarbeiters zumüllen).
_RESET_THROTTLE = {}
_RESET_WAIT = 120        # Sekunden


def _log(msg):
    """Serverseitige Spur (journalctl -u rentaltool). Der Besucher bekommt beim
    Zurücksetzen bewusst nie zu sehen, ob und warum etwas schiefging."""
    print(f"[zugang] {msg}", flush=True)


def _find_by_kennung(kennung):
    """Benutzer über Benutzername ODER hinterlegte E-Mail finden."""
    k = (kennung or "").strip().lower()
    if not k:
        return None
    for name, u in USERS.items():
        if name.lower() == k or (u.get("email") or "").strip().lower() == k:
            return name
    return None


def open_forgot_password(vorbelegt=""):
    """Selbstbedienung: Link zum Neusetzen des Passworts anfordern.

    Meldet bewusst IMMER dasselbe zurück – ob es ein Konto gibt, verrät die
    Seite einem Unbekannten nicht.
    """
    with ui.dialog() as dlg, ui.card().classes("w-[380px] max-w-full gap-2"):
        ui.label(t("Passwort zurücksetzen")).classes("text-lg font-bold")
        ui.label(t("Wir schicken dir einen Link, mit dem du dir ein neues Passwort "
                   "setzt.")).classes("text-sm text-gray-500")
        feld = ui.input(t("Benutzername oder E-Mail"), value=(vorbelegt or "").strip()) \
            .classes("w-full").mark("forgot-input")

        def anfordern():
            kennung = (feld.value or "").strip()
            name = _find_by_kennung(kennung)
            if not name:
                _log(f"Reset angefragt für '{kennung}' – kein Konto gefunden")
            elif not (USERS[name].get("email") or "").strip():
                _log(f"Reset für '{name}' nicht möglich – keine E-Mail-Adresse am Konto")
            else:
                letzte = _RESET_THROTTLE.get(name, 0)
                wartet = _RESET_WAIT - (_time.time() - letzte)
                if wartet > 0:
                    _log(f"Reset für '{name}' gebremst – noch {int(wartet)}s")
                else:
                    _RESET_THROTTLE[name] = _time.time()
                    # Ergebnis absichtlich nicht anzeigen: kein Link, kein
                    # Hinweis darauf, ob es das Konto gibt.
                    _issue_invite(name, "reset")
            ui.notify(t("Wenn es dazu ein Konto mit E-Mail-Adresse gibt, ist gleich "
                        "eine E-Mail mit einem Link unterwegs."),
                      type="positive", timeout=9000)
            dlg.close()
        feld.on("keydown.enter", lambda: anfordern())
        with ui.row().classes("w-full justify-end"):
            ui.button(t("Abbrechen"), on_click=dlg.close).props("flat")
            ui.button(t("Link anfordern"), on_click=anfordern) \
                .props("unelevated").mark("forgot-send")
    dlg.open()


# ---------------------------------------------------------------- Einladung
def _find_invite(token):
    """Benutzer zum Einladungs-Token suchen -> (name, user) oder (None, None)."""
    if not token:
        return None, None
    for name, u in USERS.items():
        if auth.invite_valid(u.get("invite"), token):
            return name, u
    return None, None


@ui.page("/invite")
def invite_page(token: str = ""):
    """Einmal-Link aus der Einladungs-/Zurücksetzen-Mail: Passwort selbst vergeben."""
    ui.colors(primary="#5E2A84", secondary="#8A5CC2", accent="#C8A96E",
              positive="#16a34a", negative="#dc2626")
    ui.query("body").classes("bg-[#F5F2EB]")

    username, u = _find_invite(token)
    if u:   # Seite in der Sprache des Eingeladenen zeigen
        app.storage.user["lang"] = u.get("lang") or i18n.DEFAULT

    with ui.column().classes("absolute-center items-center gap-4"):
        logo(60)
        with ui.card().classes("w-[360px] max-w-full gap-2 rounded-xl shadow-md"):
            if not u:
                ui.label(t("Link ungültig oder abgelaufen.")).classes("font-semibold")
                ui.label(t("Bitte fordere bei deinem Administrator eine neue Einladung an.")) \
                    .classes("text-sm text-gray-500")
                ui.button(t("Zur Anmeldung"), on_click=lambda: ui.navigate.to("/login")) \
                    .props("unelevated").classes("w-full")
                _lang_select().classes("w-full")
                return

            reset = (u.get("invite", {}) or {}).get("zweck") == "reset"
            ui.label(t("Neues Passwort vergeben") if reset else t("Zugang einrichten")) \
                .classes("font-semibold")
            ui.label(t("Konto: {benutzer}", benutzer=username)).classes("text-sm text-gray-500")
            ui.label(t("Vergib hier dein Passwort – danach bist du direkt angemeldet.")) \
                .classes("text-xs text-gray-400")
            p1 = ui.input(t("Passwort"), password=True,
                          password_toggle_button=True).classes("w-full").mark("invite-pw1")
            p2 = ui.input(t("Passwort wiederholen"), password=True) \
                .classes("w-full").mark("invite-pw2")

            def save():
                # Token erneut prüfen – zwischen Aufruf und Klick kann er ablaufen
                # oder (zweiter Browser) schon eingelöst worden sein.
                name, user = _find_invite(token)
                if not user:
                    ui.notify(t("Link ungültig oder abgelaufen."), type="negative")
                    ui.navigate.reload(); return
                if len(p1.value or "") < 6:
                    ui.notify(t("Passwort mindestens 6 Zeichen."), type="warning"); return
                if p1.value != p2.value:
                    ui.notify(t("Passwörter stimmen nicht überein."), type="negative"); return
                user["password_hash"] = auth.hash_password(p1.value)
                user.pop("invite", None)       # Einmal-Link verbraucht
                data.save_config()
                ui.notify(t("Passwort gesetzt – willkommen!"), type="positive")
                _finish_login(name, user.get("role", "putzkraft"))
            for f in (p1, p2):
                f.on("keydown.enter", lambda: save())
            ui.button(t("Passwort speichern & anmelden"), on_click=save) \
                .props("unelevated").classes("w-full").mark("invite-save")
        _lang_select().classes("w-[360px] max-w-full")


# ---------------------------------------------------------------- 2FA-Einrichtung
def open_2fa_setup(on_done=None):
    username = _cur_user()
    u = USERS.get(username)
    if not u:
        ui.notify(t("Kein angemeldeter Benutzer."), type="negative"); return
    secret = auth.generate_totp_secret()
    uri = auth.provisioning_uri(secret, username or "LIVARO", issuer="LIVARO Suites")
    with ui.dialog() as dlg, ui.card().classes("w-[420px] max-w-full items-center gap-2"):
        ui.label(t("🔐 Google Authenticator einrichten")).classes("text-lg font-bold")
        ui.label(t("1. QR-Code in der Authenticator-App scannen:")).classes("text-sm")
        ui.image(auth.qr_data_uri(uri)).classes("w-48 h-48")
        ui.label(t("oder Secret manuell eintippen:")).classes("text-xs text-gray-500")
        ui.label(secret).classes("text-xs font-mono break-all")
        ui.label(t("2. Zur Bestätigung den aktuellen 6-stelligen Code eingeben:")).classes("text-sm")
        code = ui.input(t("Code")).classes("w-full")

        def confirm():
            if not auth.verify_totp(secret, code.value or ""):
                ui.notify(t("Code stimmt nicht – bitte erneut versuchen."), type="negative"); return
            u["totp_secret"] = secret
            data.save_config()
            ui.notify(t("2FA aktiviert."), type="positive")
            dlg.close()
            if on_done:
                on_done()
        with ui.row().classes("w-full justify-end"):
            ui.button(t("Abbrechen"), on_click=dlg.close).props("flat")
            ui.button(t("Aktivieren"), on_click=confirm).props("unelevated")
    dlg.open()


# ---------------------------------------------------------------- Mein Konto
def open_account():
    username = _cur_user()
    u = USERS.get(username, {})
    with ui.dialog() as dlg, ui.card().classes("w-[420px] max-w-full gap-2"):
        ui.label(t("Mein Konto")).classes("text-xl font-bold")
        ui.label(t("Angemeldet als {user} · {rolle}",
                   user=username, rolle=_role_label(u.get("role")))) \
            .classes("text-sm text-gray-500")
        _lang_select().classes("w-full")
        email_in = ui.input(t("E-Mail (für Benachrichtigungen)"),
                            value=u.get("email", "")).classes("w-full")
        new_pw = ui.input(t("Neues Passwort (leer = unverändert)"), password=True,
                          password_toggle_button=True).classes("w-full")
        with ui.row().classes("items-center gap-2 mt-1"):
            if u.get("totp_secret"):
                def disable_2fa():
                    u["totp_secret"] = ""
                    data.save_config()
                    ui.notify(t("2FA deaktiviert."), type="warning"); dlg.close()
                ui.label("🔐 " + t("2FA aktiv")).classes("text-sm text-green-700")
                ui.button(t("2FA deaktivieren"), on_click=disable_2fa).props("flat no-caps")
            else:
                ui.button(t("2FA aktivieren"), icon="qr_code_2",
                          on_click=lambda: (dlg.close(), open_2fa_setup())).props("outline no-caps")

        def save():
            u["email"] = (email_in.value or "").strip()
            if (new_pw.value or "").strip():
                if len(new_pw.value.strip()) < 6:
                    ui.notify(t("Passwort zu kurz (min. 6)."), type="warning"); return
                u["password_hash"] = auth.hash_password(new_pw.value.strip())
            data.save_config()
            ui.notify(t("Gespeichert."), type="positive")
            dlg.close()
        with ui.row().classes("w-full justify-end"):
            ui.button(t("Schließen"), on_click=dlg.close).props("flat")
            ui.button(t("Speichern"), on_click=save).props("unelevated")
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
            USERS[username].pop("invite", None)   # offener Einmal-Link wird ungültig
            data.save_config()
            ui.notify(f"Passwort für {username} gesetzt.", type="positive"); dlg.close()
        with ui.row().classes("w-full justify-end"):
            ui.button(t("Abbrechen"), on_click=dlg.close).props("flat")
            ui.button("Setzen", on_click=save).props("unelevated")
    dlg.open()


# ---------------------------------------------------------------- Einladung (Admin)
def _invite_link(token):
    return f"{_app_url()}/invite?token={token}"


def _show_invite_link(username, link, hinweis=""):
    """Einmal-Link zum Kopieren zeigen – der Klartext existiert nur jetzt
    (gespeichert wird nur sein Hash), z. B. wenn die Mail nicht rausging."""
    with ui.dialog() as dlg, ui.card().classes("w-[520px] max-w-full gap-2"):
        ui.label(f"Zugangslink für {username}").classes("text-lg font-bold")
        if hinweis:
            ui.label(hinweis).classes("text-sm text-amber-700")
        ui.label("Nur einmal verwendbar, 7 Tage gültig. Dieser Link ist danach nicht "
                 "mehr abrufbar – bei Bedarf einfach neu einladen.") \
            .classes("text-xs text-gray-500")
        ui.label(link).classes("text-xs font-mono break-all bg-gray-100 p-2 rounded")
        with ui.row().classes("w-full justify-end"):
            ui.button("Kopieren", icon="content_copy",
                      on_click=lambda: (ui.clipboard.write(link),
                                        ui.notify("Link kopiert.", type="positive"))) \
                .props("outline no-caps")
            ui.button("Schließen", on_click=dlg.close).props("flat")
    dlg.open()


def _invite_mail(username, u, link, zweck, ablauf):
    """Betreff + Text der Einladungsmail in der Profilsprache des Mitarbeiters."""
    lang = u.get("lang") or i18n.DEFAULT
    tl = i18n.tl
    reset = zweck == "reset"
    betreff = tl(lang, "Neues Passwort für die LIVARO-App" if reset
                 else "Dein Zugang zur LIVARO-App")
    text = "\n".join([
        tl(lang, "Hallo {name},", name=u.get("name") or username),
        "",
        tl(lang, "für deinen Zugang zur LIVARO-App wurde ein neues Passwort angefordert."
           if reset else "für dich wurde ein Zugang zur LIVARO-App angelegt."),
        "",
        tl(lang, "Dein Benutzername: {benutzer}", benutzer=username),
        "",
        tl(lang, "Über diesen Link vergibst du dein Passwort (nur einmal verwendbar):"),
        link,
        "",
        tl(lang, "Der Link ist bis zum {datum} gültig.", datum=ablauf),
        tl(lang, "Danach meldest du dich jederzeit unter {url} mit deinem Benutzernamen "
           "und deinem Passwort an.", url=_app_url()),
        "",
        tl(lang, "Viele Grüße"),
        "",
        tl(lang, "Diese E-Mail wurde automatisch von der LIVARO-App verschickt."),
    ])
    return betreff, text


def _confirm_reset(username, on_ok):
    with ui.dialog() as dlg, ui.card().classes("w-[440px] max-w-full gap-2"):
        ui.label(f"Zugang von {username} zurücksetzen?").classes("text-lg font-bold")
        ui.label("Der Mitarbeiter bekommt eine E-Mail mit einem Einmal-Link und setzt "
                 "sich damit selbst ein neues Passwort. Das bisherige Passwort bleibt "
                 "gültig, bis der Link benutzt wird.").classes("text-sm text-gray-500")
        with ui.row().classes("w-full justify-end"):
            ui.button("Abbrechen", on_click=dlg.close).props("flat")
            ui.button("Link senden", icon="mail",
                      on_click=lambda: (dlg.close(), on_ok(username, "reset"))) \
                .props("unelevated no-caps")
    dlg.open()


def _issue_invite(username, zweck="einladung"):
    """Einmal-Token erzeugen, am Benutzer ablegen und per E-Mail verschicken.

    Reine Fachlogik ohne UI -> (link, ablauf, empfaenger, fehler). `fehler` ist
    None, wenn die Mail raus ist; der Token gilt in jedem Fall.
    """
    u = USERS.get(username)
    if not u:
        return None, None, "", "Benutzer nicht gefunden."
    token, rec = auth.new_invite(zweck)
    u["invite"] = rec
    data.save_config()
    link = _invite_link(token)
    ablauf = _time.strftime("%d.%m.%Y", _time.localtime(rec["expires"]))
    empfaenger = (u.get("email") or "").strip()
    if not empfaenger:
        _log(f"{zweck} für '{username}': keine E-Mail-Adresse hinterlegt")
        return link, ablauf, "", "Keine E-Mail-Adresse hinterlegt."
    betreff, text = _invite_mail(username, u, link, zweck, ablauf)
    try:
        mailer.send_notify(CFG, empfaenger, betreff, text)
    except mailer.MailError as ex:
        _log(f"{zweck} für '{username}': Versand fehlgeschlagen – {ex}")
        return link, ablauf, empfaenger, f"E-Mail nicht gesendet: {ex}"
    _log(f"{zweck} für '{username}' verschickt, Link gültig bis {ablauf}")
    return link, ablauf, empfaenger, None


def _send_invite(username, zweck="einladung"):
    """Admin-Weg: verschicken und Rückmeldung geben.

    Klappt der Versand nicht (kein Absender hinterlegt, Gmail streikt), bleibt
    der Token gültig und der Link wird zum Kopieren angezeigt – so ist niemand
    ausgesperrt, nur weil die Mail hakt. Das gibt es bewusst NUR hier, für
    angemeldete Admins.
    """
    link, ablauf, empfaenger, fehler = _issue_invite(username, zweck)
    if link is None:
        ui.notify(fehler, type="negative"); return False
    if fehler:
        _show_invite_link(username, link, fehler + (" Bitte den Link selbst weitergeben."
                                                    if not empfaenger else ""))
    else:
        ui.notify(f"Einladung an {empfaenger} gesendet ✓ (Link gültig bis {ablauf})",
                  type="positive", timeout=8000)
    return True


# ---------------------------------------------------------------- Benutzer (Admin)
def _user_saetze(uname, u):
    """Stundensätze eines Mitarbeiters: Werktag immer, Wochenende/Feiertag nur
    wenn dafür ein abweichender Satz aktiviert ist."""
    def _save_rate(key, field):
        def h(e):
            raw = (str(field.value or "")).strip().replace(",", ".")
            if raw:
                try:
                    USERS[uname][key] = round(float(raw), 2)
                except ValueError:
                    ui.notify("Bitte eine Zahl eingeben (z. B. 15,50).", type="warning")
                    return
            else:
                USERS[uname].pop(key, None)
            data.save_config()
        return h

    with ui.row().classes("w-full items-center gap-2 flex-wrap"):
        w = ui.number("Stundensatz Werktag (€)", value=u.get("stundensatz_werktag"),
                      format="%.2f", step=0.5, min=0) \
            .props("dense outlined suffix=€").classes("w-[190px]")
        w.on("blur", _save_rate("stundensatz_werktag", w))
        sw = ui.switch("Abweichender Satz an Wochenende/Feiertagen",
                       value=bool(u.get("wochenendsatz_aktiv"))).props("dense")

        def _toggle(e):
            USERS[uname]["wochenendsatz_aktiv"] = bool(e.value)
            data.save_config()
        sw.on_value_change(_toggle)
        # Feld nur bei aktiviertem Schalter zeigen – ohne die Liste neu zu bauen
        f = ui.number("Stundensatz Wochenende/Feiertag (€)",
                      value=u.get("stundensatz_wochenende"),
                      format="%.2f", step=0.5, min=0) \
            .props("dense outlined suffix=€").classes("w-[250px]")
        f.on("blur", _save_rate("stundensatz_wochenende", f))
        f.bind_visibility_from(sw, "value")
    ui.label("Leer lassen = globaler Vorgabewert aus Einstellungen → Steuerberater. "
             "Wochenende/Feiertag umfasst Sa, So und die sächsischen Feiertage.") \
        .classes("text-[11px] text-gray-400")


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
                            zustand = auth.invite_state(u)
                            if zustand == "offen":
                                bis = _time.strftime("%d.%m.", _time.localtime(
                                    u["invite"].get("expires", 0)))
                                ui.label(f"Einladung offen – Link gültig bis {bis}") \
                                    .classes("text-xs text-amber-700")
                            elif zustand == "abgelaufen":
                                ui.label("Einladung abgelaufen").classes("text-xs text-red-600")
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

                            lsel = ui.select(i18n.LANGUAGES,
                                             value=u.get("lang") or i18n.DEFAULT) \
                                .props("dense outlined").classes("w-32") \
                                .tooltip("Sprache der Oberfläche für diesen Benutzer")

                            def _lang_handler(un):
                                def h(e):
                                    USERS[un]["lang"] = e.value
                                    data.save_config()
                                    if un == _cur_user():
                                        app.storage.user["lang"] = e.value
                                    ui.notify(f"Sprache für {un}: "
                                              f"{i18n.LANGUAGES.get(e.value, e.value)}",
                                              type="positive")
                                return h
                            lsel.on_value_change(_lang_handler(uname))

                            def _invite(un=uname, zw="einladung"):
                                if _send_invite(un, zw):
                                    render()
                            if zustand == "aktiv":
                                ui.button("Zugang zurücksetzen", icon="mail",
                                          on_click=lambda un=uname: _confirm_reset(un, _invite)) \
                                    .props("flat dense no-caps") \
                                    .tooltip("Schickt einen Link, mit dem sich der Mitarbeiter "
                                             "selbst ein neues Passwort setzt. Das bisherige "
                                             "Passwort gilt, bis der Link benutzt wird.")
                            else:
                                ui.button("Einladung erneut senden", icon="forward_to_inbox",
                                          on_click=lambda un=uname: _invite(un, "einladung")) \
                                    .props("flat dense no-caps")
                            ui.button("Passwort", icon="key",
                                      on_click=lambda un=uname: open_reset_pw(un)) \
                                .props("flat dense no-caps") \
                                .tooltip("Passwort direkt setzen (Notfall, ohne E-Mail)")
                            if uname != _cur_user():
                                def _del(un=uname):
                                    USERS.pop(un, None); data.save_config()
                                    ui.notify(f"{un} gelöscht.", type="warning"); render()
                                ui.button(icon="delete", on_click=_del) \
                                    .props("flat dense round color=negative").tooltip(t("Löschen"))
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
                        with ui.row().classes("w-full items-center gap-2 no-wrap"):
                            sn = ui.input("Steuerberater-Notiz (z. B. Befreiung Rentenversicherung anbei)",
                                          value=u.get("steuer_notiz", "")).props("dense outlined") \
                                .classes("flex-grow")

                            def _note_handler(un, field):
                                def h(e):
                                    USERS[un]["steuer_notiz"] = (field.value or "").strip()
                                    data.save_config()
                                return h
                            sn.on("blur", _note_handler(uname, sn))
                        _user_saetze(uname, u)
        render()

        ui.separator()
        ui.label("Neuen Benutzer einladen").classes("font-medium")
        ui.label("Der Mitarbeiter bekommt eine E-Mail mit einem Link (7 Tage gültig) und "
                 "vergibt sich darüber selbst ein Passwort – du musst keines vorgeben.") \
            .classes("text-xs text-gray-500")
        with ui.row().classes("w-full items-end gap-2 flex-wrap"):
            nu = ui.input("Benutzername").props("dense outlined").mark("new-user")
            nem = ui.input("E-Mail").props("dense outlined") \
                .classes("min-w-[200px]").mark("new-user-mail")
            nrole = ui.select(ROLES, value="putzkraft", label="Rolle") \
                .props("dense outlined").classes("w-40")
            nlang = ui.select(i18n.LANGUAGES, value=i18n.DEFAULT, label="Sprache") \
                .props("dense outlined").classes("w-32") \
                .tooltip("Sprache der Oberfläche und der Einladungs-E-Mail")

            def add():
                name = (nu.value or "").strip()
                mail = (nem.value or "").strip()
                if not name:
                    ui.notify("Benutzername fehlt.", type="warning"); return
                if name in USERS:
                    ui.notify("Benutzername existiert bereits.", type="negative"); return
                if "@" not in mail:
                    ui.notify("E-Mail-Adresse fehlt – dorthin geht die Einladung.",
                              type="warning"); return
                USERS[name] = {"password_hash": "", "role": nrole.value,
                               "totp_secret": "", "name": name, "email": mail,
                               "lang": nlang.value}
                data.save_config()
                _send_invite(name, "einladung")
                nu.value = ""; nem.value = ""; render()
            ui.button("Einladen", icon="person_add", on_click=add) \
                .props("unelevated no-caps").mark("new-user-invite")

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
            ui.button(t("Abbrechen"), on_click=dlg.close).props("flat")
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
            t_stb = ui.tab("Steuerberater", icon="account_balance")

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
                geo_on = ui.switch("Standort bei der Zeiterfassung erfassen",
                                   value=_geo_enabled()).props("dense")
                ui.label("Ist der Schalter aus, wird beim Ein- und Auschecken weder GPS "
                         "noch IP abgefragt oder gespeichert – die Mitarbeiter werden "
                         "nicht nach Ortungsfreigabe gefragt. Bereits erfasste Standorte "
                         "alter Einträge bleiben in worklog.json erhalten.") \
                    .classes("text-xs text-gray-500")
                ui.separator().classes("my-2")
                ui.label("Objekte für die GPS-Standortprüfung der Zeiterfassung. Adresse "
                         "eintragen und Lupe antippen (Koordinaten), Radius in Metern "
                         "(z. B. 150). Check-in außerhalb wird markiert.") \
                    .classes("text-sm text-gray-500")
                _orte_hint = ui.label("Wirkt erst, wenn die Standorterfassung oben "
                                      "eingeschaltet ist.").classes("text-xs text-amber-700")
                _orte_hint.bind_visibility_from(geo_on, "value", lambda v: not v)
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

                ui.separator().classes("my-2")
                ui.label("Adresse der App – wird für Links in E-Mails benutzt "
                         "(Einladungen, Reinigungs-Hinweise). Muss von außen erreichbar sein.") \
                    .classes("text-sm text-gray-500")
                app_url_in = ui.input("Adresse der App", value=CFG.get("app_url", "") or DEFAULT_APP_URL,
                                      placeholder=DEFAULT_APP_URL) \
                    .props("outlined dense").classes("w-full max-w-[420px]")

            with ui.tab_panel(t_stb):
                ui.label("Empfänger für den monatlichen Arbeitszeiten-Versand "
                         "(Zeiterfassung → Auswertung → An Steuerberater senden). "
                         "Unabhängig von der E-Mail für die Beherbergungssteuer.") \
                    .classes("text-sm text-gray-500")
                stb = ui.input("E-Mail Steuerberater", value=CFG.get("steuerberater_email", "")) \
                    .props("outlined dense").classes("w-full max-w-[420px]")
                ui.label("E-Mail-Vorlage (Platzhalter {monat}, {jahr}). Die Stunden je "
                         "Mitarbeiter und der Zeitraum werden automatisch eingefügt; eine "
                         "Notiz je Mitarbeiter kommt aus der Benutzerverwaltung.") \
                    .classes("text-xs text-gray-500 mt-2")
                stb_anrede = ui.input("Anrede", value=CFG.get("steuerberater_anrede", "")
                                      or "Sehr geehrte Damen und Herren,") \
                    .props("outlined dense").classes("w-full max-w-[420px]")
                stb_intro = ui.input("Einleitung",
                                     value=CFG.get("steuerberater_intro", "") or "anbei die Stunden für {monat}.") \
                    .props("outlined dense").classes("w-full max-w-[420px]")
                stb_gruss = ui.textarea("Grußformel",
                                        value=CFG.get("steuerberater_gruss", "")
                                        or "Vielen Dank im Voraus.\n\nMit freundlichen Grüßen\nDaniel Steinhauß") \
                    .props("outlined autogrow").classes("w-full max-w-[420px]")
                ui.separator().classes("my-2")
                ui.label("Stundensätze (Vorgabe)").classes("font-medium")
                ui.label("Gelten für alle Mitarbeiter ohne eigenen Satz. Der Satz für "
                         "Wochenende/Feiertag greift nur bei Mitarbeitern, bei denen er in "
                         "der Benutzerverwaltung aktiviert ist. Wochenende/Feiertag = Sa, So "
                         "und die gesetzlichen Feiertage in Sachsen.") \
                    .classes("text-xs text-gray-500")
                with ui.row().classes("items-center gap-2 flex-wrap"):
                    satz_wt = ui.number("Werktag", value=CFG.get("stundensatz_werktag") or None,
                                        format="%.2f", step=0.5, min=0) \
                        .props("outlined dense suffix=€").classes("w-[160px]")
                    satz_we = ui.number("Wochenende/Feiertag",
                                        value=CFG.get("stundensatz_wochenende") or None,
                                        format="%.2f", step=0.5, min=0) \
                        .props("outlined dense suffix=€").classes("w-[200px]")

        def save():
            CFG["steuerberater_email"] = (stb.value or "").strip()
            CFG["steuerberater_anrede"] = (stb_anrede.value or "").strip()
            CFG["steuerberater_intro"] = (stb_intro.value or "").strip()
            CFG["steuerberater_gruss"] = stb_gruss.value or ""
            for key, fld in (("stundensatz_werktag", satz_wt),
                             ("stundensatz_wochenende", satz_we)):
                CFG[key] = round(float(fld.value), 2) if fld.value else ""
            CFG["standort_erfassung"] = bool(geo_on.value)
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
            CFG["app_url"] = (app_url_in.value or "").strip().rstrip("/") or DEFAULT_APP_URL
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


def _satz_label(satz):
    """0.06 -> '6 %', 0.065 -> '6,5 %'."""
    p = round(satz * 100, 4)
    s = f"{p:g}".replace(".", ",")
    return f"{s} %"


def _summen_tabelle(r, satz):
    """Alle Summen einer Anmeldung als Tabelle.

    Beantwortet die Frage, an der man sich sonst verrechnet: WELCHE Summe ist
    die Bemessungsgrundlage? Nicht die Summe der Rechnungsbeträge – aus der
    muss erst die vom Gast mitbezahlte Beherbergungssteuer raus. Die Spalte
    rechts sagt, welche Zeile tatsächlich ins amtliche Formular wandert.
    """
    rem = r["remaining_rows"]
    s_rechnung = round(sum(x["price"] for x in rem), 2)
    s_citytax = round(sum(x["citytax"] for x in rem), 2)
    s_zeilen = round(sum(round(x["base"] * r["steuersatz"], 2) for x in rem), 2)
    e = data.euro

    # (Art, Bezeichnung, Wert, Herkunft)
    zeilen = [
        ("head", "Übernachtungen", "", ""),
        ("line", "Übernachtungen insgesamt",
         str(r["uebernachtungen_insgesamt"]), "Formular"),
        ("line", "davon über Airbnb gebucht (Airbnb meldet selbst)",
         str(r["uebernachtungen_airbnb"]), "Formular"),
        ("sum", "= verbleibende Übernachtungen",
         str(r["uebernachtungen_verbleibend"]), "Formular"),
        ("head", f"Beträge – nur die {len(rem)} verbleibenden Buchungen, ohne Airbnb", "", ""),
        ("line", "Summe Rechnungsbeträge (was die Gäste insgesamt gezahlt haben)",
         e(s_rechnung) + " €", "nachrichtlich"),
        ("minus", "− darin enthaltene Beherbergungssteuer (Durchlaufposten)",
         "− " + e(s_citytax) + " €", "nachrichtlich"),
        ("sum", "= Umsätze aus verbleibenden Übernachtungen (Bemessungsgrundlage)",
         e(r["umsatz_verbleibend"]) + " €", "Formular"),
        ("minus", "− steuerbefreite Umsätze",
         "− " + e(r["umsatz_steuerbefreit"]) + " €", "Formular"),
        ("sum", "= steuerpflichtige Umsätze",
         e(r["umsatz_steuerpflichtig"]) + " €", "Formular"),
        ("result", f"× {satz} = Beherbergungssteuer",
         e(r["beherbergungssteuer"]) + " €", "Formular"),
    ]

    with ui.card().classes("w-full").mark("summen"):
        ui.label("Summen dieser Anmeldung").classes("font-medium")
        ui.label("Welche Summe wofür – die rechte Spalte zeigt, was ins amtliche "
                 "Formular eingetragen wird.").classes("text-xs text-gray-500")
        with ui.element("div").classes(
                "w-full grid grid-cols-[1fr_auto_auto] gap-x-4 gap-y-0 mt-2 "
                "border border-slate-200 rounded-lg overflow-hidden"):
            def zelle(text, cls):
                ui.label(text).classes("px-3 py-1.5 " + cls)

            for art, bez, wert, herkunft in zeilen:
                if art == "head":
                    zelle(bez, "text-xs font-semibold uppercase tracking-wide "
                               "text-slate-500 bg-slate-100 pt-2")
                    zelle("", "bg-slate-100")
                    zelle("", "bg-slate-100")
                    continue
                basis = {
                    "line":   ("text-sm text-slate-700", "text-sm tabular-nums text-slate-700"),
                    "minus":  ("text-sm text-slate-600", "text-sm tabular-nums text-slate-600"),
                    "sum":    ("text-sm font-semibold text-slate-800 border-t border-slate-200",
                               "text-sm font-semibold tabular-nums text-slate-800 "
                               "border-t border-slate-200"),
                    "result": ("text-base font-bold text-primary border-t-2 border-slate-300 "
                               "bg-[#faf7f0]",
                               "text-base font-bold tabular-nums text-primary "
                               "border-t-2 border-slate-300 bg-[#faf7f0]"),
                }[art]
                zelle(bez, basis[0])
                zelle(wert, basis[1] + " text-right")
                zelle(herkunft, "text-xs text-gray-400 self-center whitespace-nowrap"
                      + (" bg-[#faf7f0]" if art == "result" else ""))

        if s_zeilen != r["beherbergungssteuer"]:
            ui.label(f"Hinweis: Die Steuer-Spalte der Buchungstabelle aufsummiert ergibt "
                     f"{e(s_zeilen)} €. Der Cent-Unterschied entsteht, weil die Steuer auf die "
                     f"Gesamtsumme gerechnet wird und nicht je Buchung – angemeldet wird "
                     f"{e(r['beherbergungssteuer'])} €.").classes("text-xs text-gray-500 mt-2")


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
                 f"Steuer ein (Airbnb meldet selbst).").classes("text-xs text-gray-500")

        satz = _satz_label(r["steuersatz"])

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
            {"name": "price", "label": "Rechnungsbetrag €", "field": "price", "align": "right"},
            {"name": "citytax", "label": "− enth. BSt €", "field": "citytax", "align": "right"},
            {"name": "base", "label": "= Bemessungsgrundlage €", "field": "base", "align": "right"},
            {"name": "steuer", "label": f"Steuer € ({satz})", "field": "steuer", "align": "right"},
        ]
        rows = []
        for x in r["rows"]:
            # Airbnb wird nicht besteuert – dann bleiben Basis und Steuer leer,
            # sonst summiert sich die Spalte nicht auf den steuerpfl. Umsatz.
            leer = x["is_airbnb"]
            rows.append({
                "departure": x["departure"], "guest": x["guest"],
                "apartment": x["apartment"], "channel": x["channel"],
                "arrival": x["arrival"], "nights": x["nights"],
                "persons": x["persons"], "overnights": x["overnights"],
                "price": data.euro(x["price"]),
                "citytax": "—" if leer else ("–" + data.euro(x["citytax"]) if x["citytax"] else "0,00"),
                "base": "—" if leer else data.euro(x["base"]),
                "steuer": "—" if leer else data.euro(round(x["base"] * r["steuersatz"], 2)),
            })
        _summen_tabelle(r, satz)

        with ui.card().classes("w-full"):
            ui.label(f"Buchungen ({len(rows)}) – Abreise im Monat, bereits stattgefunden").classes("font-medium")
            # Legende zu den vier Betragsspalten. Bewusst NICHT "Bruttopreis" für die
            # Basis – das liest sich wie "alles inklusive" und ist genau die
            # Verwechslung, die hier droht.
            with ui.row().classes("w-full items-center gap-2 flex-wrap text-xs text-gray-600 "
                                  "bg-slate-50 border border-slate-200 rounded-lg px-3 py-2"):
                ui.icon("functions").classes("text-slate-400 text-base")
                ui.label("Rechnungsbetrag (was der Gast zahlt)").classes("font-medium")
                ui.label("−").classes("text-gray-400")
                ui.label("darin enthaltene Beherbergungssteuer (Durchlaufposten)")
                ui.label("=").classes("text-gray-400")
                ui.label("Bemessungsgrundlage (Beherbergungsentgelt inkl. 7 % USt)").classes("font-medium")
                ui.label(f"× {satz} =").classes("text-gray-400")
                ui.label("Steuer").classes("font-medium")
            ui.table(columns=cols, rows=rows, row_key="departure").classes("w-full").props("dense flat")

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
                    ui.button(t("Abbrechen"), on_click=dlg.close).props("flat")
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
            ui.notify(t("Foto konnte nicht gespeichert werden: {fehler}", fehler=ex), type="negative")
            return
        ui.notify(t("Foto gespeichert ✓"), type="positive")
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


def open_damage_dialog(apt_id, apt_name, reporter, on_saved=None, booking_id=None):
    photo = {"rel": None}
    with ui.dialog() as dlg, ui.card().classes("w-[460px] max-w-full gap-2"):
        ui.label(t("Schaden melden – {wohnung}", wohnung=apt_name)).classes("text-lg font-bold")
        room = ui.input("Raum/Bereich").props("dense outlined").classes("w-full")
        desc = ui.textarea(t("Was ist beschädigt?")).props("outlined").classes("w-full")
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
                ui.notify(t("Bitte Beschreibung angeben."), type="warning"); return
            d = housekeeping.add_damage(apt_id, apt_name, (room.value or "").strip(),
                                        desc.value.strip(), urg.value, photo["rel"], reporter,
                                        booking_id=booking_id)
            _notify_damage(d)
            ui.notify(t("Schaden gemeldet – Danke!"), type="positive")
            dlg.close()
            if on_saved:
                on_saved()
        with ui.row().classes("w-full justify-end"):
            ui.button(t("Abbrechen"), on_click=dlg.close).props("flat")
            ui.button(t("Melden"), on_click=save).props("unelevated")
    dlg.open()


def _hk_header(title, subtitle):
    with ui.row().classes("w-full items-center gap-3"):
        ui.icon("cleaning_services").classes("text-3xl text-primary")
        with ui.column().classes("gap-0"):
            ui.label(title).classes("text-2xl font-bold text-slate-800 leading-tight")
            ui.label(subtitle).classes("text-sm text-gray-500")


def render_reinigung(activate=None):
    # "reinigung" wird nur noch aus einer Buchung geöffnet -> immer die Checklisten-
    # Durchgangs-Ansicht (auch für Admins, die eine Reinigung inspizieren).
    reinigung_putzkraft(activate)


_ROOM_ICONS = {"bad": "bathtub", "wc": "wc", "küche": "kitchen", "kueche": "kitchen",
               "schlafzimmer": "bed", "wohnbereich": "weekend", "wohnzimmer": "weekend",
               "flur": "door_front", "balkon": "balcony", "allgemein": "home"}


def _room_icon(name):
    key = (name or "").lower()
    for k, ic in _ROOM_ICONS.items():
        if k in key:
            return ic
    return "checklist"


def reinigung_putzkraft(activate=None):
    user = _cur_user()
    apts = _apts()
    pre = _PENDING_REINIGUNG.pop("apt", None)
    ret = _PENDING_REINIGUNG.pop("return", None)
    bkid = _PENDING_REINIGUNG.pop("booking", None)
    co = _PENDING_REINIGUNG.pop("co", None)
    ci = _PENDING_REINIGUNG.pop("ci", None)
    nxt = _PENDING_REINIGUNG.pop("next", None)
    same_day = _PENDING_REINIGUNG.pop("same_day", False)
    state = {"apt": pre, "return": ret, "booking": bkid, "co": co, "ci": ci,
             "next": nxt, "same_day": same_day, "group": True, "collapsed": set()}
    body = ui.column().classes("w-full gap-4")

    def open_apt(aid, anm):
        state["apt"] = (aid, anm); render()

    def _photo_dialog(run, t):
        with ui.dialog() as dlg, ui.card().classes("w-[380px] max-w-full gap-2"):
            ui.label(t["text"]).classes("font-bold")
            with ui.row().classes("gap-3 flex-wrap"):
                if t.get("ref_photo"):
                    with ui.column().classes("items-center gap-0"):
                        _photo_thumb(f"/media/{t['ref_photo']}", "w-24 h-24")
                        ui.label(t("Soll")).classes("text-xs text-gray-400")
                istc = ui.column().classes("items-center gap-1")

                def draw():
                    istc.clear()
                    with istc:
                        p = _run_ist(run["id"], t["id"])
                        if p:
                            _photo_thumb(f"/media/{p}", "w-24 h-24")
                            ui.button("entfernen", on_click=lambda: (
                                housekeeping.update_task(run["id"], t["id"], ist_photo=""),
                                draw(), render())).props("flat dense no-caps size=sm")
                        else:
                            def saved(rel):
                                housekeeping.update_task(run["id"], t["id"], ist_photo=rel)
                                draw(); render()
                            _photo_button("Ist-Foto", "ist", saved)
                            ui.label(t("Ist")).classes("text-xs text-gray-400")
                draw()
            with ui.row().classes("w-full justify-end"):
                ui.button(t("Schließen"), on_click=dlg.close).props("flat")
        dlg.open()

    def _task_row(run, t):
        done = run["tasks"].get(t["id"], {}).get("done", False)
        has_photo = bool(_run_ist(run["id"], t["id"]))
        with ui.row().classes("w-full items-center gap-2 no-wrap py-1"):
            cb = ui.checkbox(value=done).props("dense")
            cb.on_value_change(lambda e, tid=t["id"]:
                               (housekeeping.update_task(run["id"], tid, done=e.value), render()))
            ui.label(t["text"]).classes(
                "flex-grow text-sm " + ("line-through text-gray-400" if done else "text-slate-700"))
            ui.button(icon="photo_camera", on_click=lambda: _photo_dialog(run, t)) \
                .props("flat round dense").classes("text-green-600" if has_photo else "text-primary") \
                .tooltip(t("Foto"))

    def _picker():
        _hk_header("Reinigung", "Checkliste, Fotonachweis, Schäden & Bestand")
        with ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100 gap-2"):
            due = _due_today()
            if due:
                ui.label(t("Heute fällig (nach Abreise):")).classes("font-medium")
                with ui.row().classes("gap-2 flex-wrap"):
                    for aid, anm in due:
                        ui.button(anm, icon="event_available",
                                  on_click=lambda a=aid, n=anm: open_apt(a, n)) \
                            .props("unelevated no-caps")
            ui.label(t("Apartment wählen:")).classes("text-sm text-gray-500 mt-1")
            with ui.row().classes("items-end gap-2"):
                sel = ui.select(apts, label=t("Apartment")).props("outlined dense").classes("min-w-[240px]")
                ui.button(t("Reinigung starten"), icon="play_arrow",
                          on_click=lambda: (open_apt(sel.value, apts.get(sel.value)) if sel.value
                                            else ui.notify(t("Bitte Apartment wählen."), type="warning"))) \
                    .props("unelevated no-caps")

    def render():
        body.clear()
        with body:
            if state["apt"] is None:
                _picker(); return
            aid, anm = state["apt"]
            run = housekeeping.start_run(aid, anm, user)
            cl = housekeeping.get_checklist(aid)
            all_tasks = [t for r in cl["rooms"] for t in r["tasks"]]
            total = len(all_tasks)
            done = sum(1 for t in all_tasks if run["tasks"].get(t["id"], {}).get("done"))

            # Kopfzeile: zurück + Titel + Menü
            with ui.row().classes("w-full items-center gap-2"):
                ui.button(icon="arrow_back",
                          on_click=lambda: (state.update(apt=None), render())).props("flat round color=primary")
                ui.label(anm).classes("text-xl font-bold text-primary")
                ui.space()
                with ui.button(icon="more_vert").props("flat round color=primary"):
                    with ui.menu():
                        ui.menu_item("Schaden melden", lambda: open_damage_dialog(aid, anm, user, booking_id=state.get("booking")))
                        ui.menu_item("Verbrauch / Wäsche",
                                     lambda: _restock_dialog({"apartment_id": aid, "apartment_name": anm, "id": state.get("booking")}, user))

            # Wohnungs-Karte mit Zeiten
            with ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100 p-4 gap-2"):
                with ui.row().classes("w-full items-center gap-2"):
                    ui.icon("apartment").classes("text-primary text-xl")
                    ui.label(anm).classes("font-bold text-lg")
                if state.get("co") or state.get("ci"):
                    with ui.row().classes("w-full items-center gap-4"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("logout").classes("text-deep-orange")
                            with ui.column().classes("gap-0"):
                                ui.label(t("Check-out")).classes("text-xs text-gray-500")
                                ui.label(state.get("co") or "—").classes("font-semibold")
                        ui.element("div").classes("w-px h-8 bg-slate-200")
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("login").classes("text-green-700")
                            with ui.column().classes("gap-0"):
                                ui.label(t("Check-in")).classes("text-xs text-gray-500")
                                ui.label(state.get("ci") or "—").classes("font-semibold")
                # Für wie viele einzudecken ist – hier, wo tatsächlich gearbeitet wird.
                if state.get("apt") and state.get("booking"):
                    _prep_panel(state.get("next"), state.get("same_day"))

            # Fortschritt
            with ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100 p-4 gap-1"):
                with ui.row().classes("w-full items-center"):
                    ui.label(t("Fortschritt")).classes("font-medium")
                    ui.space()
                    ui.label(f"{done} / {total} erledigt").classes("font-semibold")
                ui.linear_progress(value=(done / total if total else 0), show_value=False) \
                    .props("color=primary rounded track-color=grey-3").classes("w-full")

            # Räume & Aufgaben + Umschalter
            with ui.row().classes("w-full items-center gap-2"):
                ui.label(t("Räume & Aufgaben")).classes("font-medium")
                ui.space()
                ui.label(t("Nach Raum gruppieren")).classes("text-xs text-gray-500")
                sw = ui.switch(value=state["group"]).props("dense")
                sw.on_value_change(lambda e: (state.update(group=e.value), render()))

            if state["group"]:
                collapsed = state["collapsed"]
                for room in cl["rooms"]:
                    rtasks = room["tasks"]
                    if not rtasks:
                        continue
                    rn = room["name"]
                    rdone = sum(1 for t in rtasks if run["tasks"].get(t["id"], {}).get("done"))
                    is_open = rn not in collapsed
                    with ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100 p-3 gap-1"):
                        hdr = ui.row().classes("w-full items-center gap-2 cursor-pointer no-wrap")

                        def _toggle(name=rn):
                            (collapsed.discard(name) if name in collapsed else collapsed.add(name))
                            render()
                        hdr.on("click", _toggle)
                        with hdr:
                            with ui.element("div").classes("rounded-full bg-violet-50 p-1 flex"):
                                ui.icon(_room_icon(rn)).classes("text-primary text-lg")
                            ui.label(rn).classes("font-medium")
                            ui.space()
                            ui.label(f"{rdone} / {len(rtasks)} erledigt").classes("text-xs text-gray-500")
                            ui.icon("expand_less" if is_open else "expand_more").classes("text-gray-400")
                        ui.linear_progress(value=(rdone / len(rtasks) if rtasks else 0), show_value=False) \
                            .props("color=primary rounded track-color=grey-3 size=5px").classes("w-full")
                        if is_open:
                            for t in rtasks:
                                _task_row(run, t)
                # Alle aus-/einklappen
                if collapsed:
                    ui.button(t("Alle Aufgaben anzeigen"), icon="more_horiz",
                              on_click=lambda: (collapsed.clear(), render())) \
                        .props("flat no-caps color=primary").classes("w-full")
                else:
                    ui.button(t("Alle einklappen"), icon="unfold_less",
                              on_click=lambda: (state["collapsed"].update(r["name"] for r in cl["rooms"]), render())) \
                        .props("flat no-caps color=primary").classes("w-full")
            else:
                with ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100 p-3"):
                    for t in all_tasks:
                        _task_row(run, t)

            # Abschließen
            def finish():
                housekeeping.finish_run(run["id"])
                if state.get("booking"):
                    bookings.mark_checklist_done(state["booking"], user)
                ui.notify(t("Checkliste abgeschlossen ✓"), type="positive")
                if state.get("return") == "buchungen" and activate:
                    activate("buchungen")
                else:
                    state.update(apt=None); render()
            ui.button(t("Checkliste abschließen"), icon="check_circle", on_click=finish) \
                .props("unelevated no-caps size=lg").classes("w-full mt-2")
    render()


def reinigung_uebersicht(activate=None):
    _hk_header("Übersicht", "Zusammenfassung aller Reinigungen, Schäden & Bestand")
    apts = _apts()
    with ui.tabs().props("dense no-caps align=left").classes("w-full") as tabs:
        t_sum = ui.tab("Zusammenfassung", icon="insights")
        t_runs = ui.tab("Durchgänge", icon="fact_check")
        t_dmg = ui.tab("Schäden", icon="report_problem")
        t_shop = ui.tab("Einkaufsliste", icon="shopping_cart")
        t_cfg = ui.tab("Konfiguration", icon="tune")
    with ui.tab_panels(tabs, value=t_sum).classes("w-full"):
        with ui.tab_panel(t_sum):
            _admin_summary(activate)
        with ui.tab_panel(t_runs):
            _admin_runs()
        with ui.tab_panel(t_dmg):
            _admin_damages()
        with ui.tab_panel(t_shop):
            _admin_shopping()
        with ui.tab_panel(t_cfg):
            _admin_config(apts)


def _sum_kpi(label, value, icon, color="text-primary"):
    with ui.card().classes("rounded-xl shadow-sm border border-slate-100 p-3 items-center gap-0 min-w-[104px]"):
        ui.icon(icon).classes(color + " text-2xl")
        ui.label(str(value)).classes("text-2xl font-bold text-slate-800 leading-tight")
        ui.label(label).classes("text-xs text-gray-500")


def _admin_summary(activate):
    staff = _staff_users()
    jobs = _cleaning_jobs()
    statuses = [_booking_status(j) for j in jobs]
    fertig = statuses.count("abgeschlossen")
    ueberf = statuses.count("nachtragen")
    dmg_open = len(housekeeping.list_damages(only_open=True))
    rest_open = len(housekeeping.list_restock(only_open=True))
    with ui.row().classes("w-full gap-2 flex-wrap"):
        _sum_kpi("Reinigungen", len(jobs), "cleaning_services")
        _sum_kpi("Fertig", fertig, "check_circle", "text-green-600")
        _sum_kpi("Überfällig", ueberf, "warning", "text-red-600")
        _sum_kpi("Offene Schäden", dmg_open, "report_problem", "text-red-600")
        _sum_kpi("Einkäufe offen", rest_open, "shopping_cart", "text-primary")

    if not jobs:
        ui.label("Keine Reinigungen im Zeitraum.").classes("text-gray-500 mt-3"); return
    ui.label("Alle Reinigungen").classes("text-sm font-semibold text-gray-500 mt-3")
    for j, st in zip(jobs, statuses):
        dprog, tprog = _checklist_progress(j, None)
        done_entries = [e for e in timetrack.entries_for_booking(j["id"]) if e.get("checkout")]
        total_min = sum(timetrack.duration_minutes(e) or 0 for e in done_entries)
        who = bookings.assignee_of(j["id"])
        wn = staff.get(who, who) if who else "nicht zugewiesen"
        card = ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100 p-3 cursor-pointer")
        card.on("click", lambda b=j: open_booking_dialog(b, _cur_user(), _is_admin(), staff, activate))
        with card:
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.icon("home").classes("text-primary shrink-0")
                with ui.column().classes("gap-0 min-w-0 flex-grow"):
                    with ui.row().classes("w-full items-center gap-2 no-wrap"):
                        ui.label(j["apartment_name"]).classes("font-medium truncate flex-grow min-w-0")
                        _status_chip(j)
                    ui.label(f"{_dfmt(j['departure'])} · {wn} · Checkliste {dprog}/{tprog} · "
                             f"{timetrack.fmt_dur(total_min) if total_min else '0:00 h'}") \
                        .classes("text-xs text-gray-500 truncate")
                ui.icon("chevron_right").classes("text-gray-300 shrink-0")


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
        nfotos = sum(1 for v in r["tasks"].values() if v.get("ist_photo"))
        with ui.expansion(head + (f" · {nfotos} Foto(s)" if nfotos else ""),
                          icon="cleaning_services").classes("w-full"):
            for room in cl["rooms"]:
                ui.label(room["name"]).classes("font-medium text-sm mt-2")
                for t in room["tasks"]:
                    st = r["tasks"].get(t["id"], {})
                    with ui.column().classes("w-full gap-1 pl-1 py-1 border-b border-slate-50"):
                        with ui.row().classes("w-full items-center gap-2"):
                            ui.icon("check_circle" if st.get("done") else "radio_button_unchecked") \
                                .classes("text-green-600" if st.get("done") else "text-gray-300")
                            ui.label(t["text"]).classes("text-sm")
                        if t.get("ref_photo") or st.get("ist_photo"):
                            with ui.row().classes("items-end gap-4 pl-7 flex-wrap"):
                                if t.get("ref_photo"):
                                    with ui.column().classes("items-center gap-0"):
                                        _photo_thumb(f"/media/{t['ref_photo']}", "w-16 h-16")
                                        ui.label("Soll").classes("text-xs text-gray-400")
                                if st.get("ist_photo"):
                                    with ui.column().classes("items-center gap-0"):
                                        _photo_thumb(f"/media/{st['ist_photo']}", "w-16 h-16")
                                        ui.label("Ist (Putzkraft)").classes("text-xs text-green-600")


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
    ui.label("Checkliste & Bestand je Wohnung. Pro Aufgabe ein Beispielfoto (Soll-Zustand) "
             "aufnehmen – die Putzkraft sieht es dann in der Checkliste.") \
        .classes("text-sm text-gray-500")
    sel = ui.select(apts, label="Wohnung wählen",
                    value=(next(iter(apts), None))).props("outlined dense") \
        .classes("w-full max-w-[320px]")
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
                        with ui.column().classes("w-full gap-1 py-1 border-b border-slate-50"):
                            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                                tt = ui.input("Aufgabe", value=t["text"]).props("dense outlined").classes("flex-grow")
                                task_inputs.append((t, tt))
                                ui.button(icon="delete", on_click=lambda i=ti, rm=room: (collect(), rm["tasks"].pop(i), housekeeping.save_checklist(aid, cl), render_cfg())) \
                                    .props("flat dense round color=negative").tooltip("Aufgabe löschen")

                            def ref_saved(rel, tid=t["id"]):
                                collect()
                                housekeeping.save_checklist(aid, cl)
                                housekeeping.set_task_ref_photo(aid, tid, rel)
                                render_cfg()

                            def ref_remove(tid=t["id"]):
                                collect()
                                housekeeping.save_checklist(aid, cl)
                                housekeeping.set_task_ref_photo(aid, tid, None)
                                render_cfg()
                            with ui.row().classes("w-full items-center gap-2 flex-wrap pl-1"):
                                if t.get("ref_photo"):
                                    _photo_thumb(f"/media/{t['ref_photo']}", "w-16 h-16")
                                    ui.label("Beispielfoto").classes("text-xs text-gray-400")
                                    _photo_button("ändern", "ref", ref_saved, icon="photo_camera")
                                    ui.button("entfernen", icon="close", on_click=ref_remove) \
                                        .props("flat dense no-caps size=sm color=negative")
                                else:
                                    _photo_button("Beispielfoto", "ref", ref_saved, icon="add_a_photo")
                                    ui.label("(Soll-Zustand fotografieren)").classes("text-xs text-gray-400")
                    ui.button("Aufgabe hinzufügen", icon="add",
                              on_click=lambda rm=room: (collect(), rm["tasks"].append({"id": housekeeping._uid(), "text": "Neue Aufgabe", "ref_photo": None}), housekeeping.save_checklist(aid, cl), render_cfg())) \
                        .props("flat dense no-caps")
            ui.button("Raum hinzufügen", icon="add_home",
                      on_click=lambda: (collect(), cl["rooms"].append({"name": "Neuer Raum", "tasks": []}), housekeeping.save_checklist(aid, cl), render_cfg())) \
                .props("outline no-caps")

            ui.separator()
            ui.label("Bestandsliste (Verbrauch/Wäsche)").classes("font-medium")
            for ii, it in enumerate(inv):
                with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                    nm = ui.input("Artikel", value=it["name"]).props("dense outlined").classes("flex-grow min-w-[140px]")
                    ka = ui.select({"verbrauch": "Verbrauch", "waesche": "Wäsche"},
                                   value=it.get("kategorie", "verbrauch")).props("dense outlined").classes("w-32")
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
_WD_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _dfmt(iso):
    try:
        d = date.fromisoformat(iso)
        wd = (_WD_EN if i18n.lang() == "en" else _WD)[d.weekday()]
        return f"{wd} {d.strftime('%d.%m.')}"
    except Exception:
        return iso or ""


def _persons_text(nb, explicit_children=False):
    """'2 Erwachsene · 1 Kind'. Mit explicit_children auch 'keine Kinder',
    damit im Wechsel klar ist, dass wirklich keine gebucht sind."""
    a, c = nb.get("adults") or 0, nb.get("children") or 0
    parts = []
    if a:
        parts.append(t("1 Erwachsener") if a == 1 else t("{n} Erwachsene", n=a))
    if c:
        parts.append(t("1 Kind") if c == 1 else t("{n} Kinder", n=c))
    elif explicit_children and a:
        parts.append(t("keine Kinder"))
    return " · ".join(parts) or t("{n} Pers.", n=nb.get("persons", 0))


def _guest_persons(nb, explicit_children=False):
    """'Max Mustermann · 2 Erwachsene · 1 Kind'"""
    return f"{nb.get('guest') or t('Gast')} · {_persons_text(nb, explicit_children)}"


def _pers_count(nb):
    """Personen einer Buchung (Erwachsene + Kinder)."""
    if not nb:
        return 0
    return (nb.get("adults") or 0) + (nb.get("children") or 0) or (nb.get("persons") or 0)


def _prep_panel(nxt, same_day):
    """Der 'Vorbereiten für N'-Block – die EINZIGE Stelle mit einer grossen
    Personenzahl. Die Abreise-Zahl steht bewusst nirgends so prominent, damit
    das Putzteam nicht für die abreisenden statt für die anreisenden Gäste
    eindeckt."""
    if not nxt:
        with ui.row().classes("w-full items-center gap-2 rounded-xl border border-slate-200 "
                              "bg-slate-50 p-3"):
            ui.icon("event_busy").classes("text-gray-400")
            with ui.column().classes("gap-0 min-w-0"):
                ui.label(t("keine Folgebuchung")).classes("font-medium text-slate-600")
                ui.label(t("Nichts vorzubereiten – nur reinigen.")).classes("text-xs text-gray-500")
        return
    n = _pers_count(nxt)
    tone, txt = (("bg-orange-50 border-orange-300", "text-orange-800") if same_day
                 else ("bg-green-50 border-green-200", "text-green-800"))
    with ui.column().classes(f"w-full gap-0 rounded-xl border p-3 {tone}").mark("prep-block"):
        with ui.row().classes("w-full items-center gap-1 no-wrap"):
            ui.icon("login").classes(f"{txt} text-base shrink-0")
            ui.label(t("Vorbereiten für")).classes(
                f"text-xs font-semibold uppercase tracking-wide {txt}")
        with ui.row().classes("items-baseline gap-2 no-wrap"):
            ui.label(str(n)).classes(f"text-4xl font-extrabold leading-none {txt}").mark("prep-count")
            ui.label(t("Person") if n == 1 else t("Personen")).classes(
                f"text-base font-semibold {txt}")
        ui.label(_persons_text(nxt, True)).classes(f"text-sm {txt} leading-tight")
        ui.label(nxt.get("guest") or t("Gast")).classes(
            "text-sm text-slate-600 truncate leading-tight mt-1")
        ui.label(f"{t('Anreise')} {_dfmt(nxt['arrival'])} · {nxt['checkin_time'] or '—'}") \
            .classes("text-xs text-slate-500 leading-tight")
        if same_day:
            with ui.row().classes("w-full items-center gap-1 no-wrap mt-1"):
                ui.icon("bolt").classes("text-orange-700 text-sm shrink-0")
                ui.label(t("Wechseltag – Anreise noch heute")).classes(
                    "text-xs font-semibold text-orange-700")


def _depart_panel(job):
    """Abreise-Angaben – bewusst neutral/klein gehalten (siehe _prep_panel)."""
    with ui.column().classes("w-full gap-0 rounded-xl border border-slate-200 bg-slate-50 p-3") \
            .mark("depart-block"):
        with ui.row().classes("w-full items-center gap-1 no-wrap"):
            ui.icon("logout").classes("text-slate-500 text-base shrink-0")
            ui.label(t("Es reist ab")).classes(
                "text-xs font-semibold uppercase tracking-wide text-slate-500")
        ui.label(job.get("guest") or t("Gast")).classes(
            "font-medium text-slate-700 truncate leading-tight")
        ui.label(_persons_text(job, True)).classes("text-sm text-slate-600 leading-tight")
        ui.label(f"{t('Check-out')} {_dfmt(job['departure'])} · {job.get('checkout_time') or '—'}") \
            .classes("text-xs text-slate-500 leading-tight")
        ui.label(t("Nur zur Info – nicht die Zahl für die Vorbereitung.")) \
            .classes("text-xs text-slate-400 italic mt-1")


def _ab_an_tabs(job, nxt, same_day):
    """Abreise und Anreise in getrennten Tabs statt untereinander – Standard ist
    'Vorbereiten', weil nur diese Zahl fürs Eindecken zählt."""
    with ui.tabs().props("dense no-caps align=left").classes("w-full") as tabs:
        tab_prep = ui.tab(t("Vorbereiten"), icon="login")
        tab_ab = ui.tab(t("Abreise"), icon="logout")
    with ui.tab_panels(tabs, value=tab_prep).classes("w-full"):
        with ui.tab_panel(tab_prep).classes("p-0 pt-2"):
            _prep_panel(nxt, same_day)
        with ui.tab_panel(tab_ab).classes("p-0 pt-2"):
            _depart_panel(job)


def _events_between(d_from, d_to):
    """An-/Abreise-Ereignisse mit Datum in [d_from, d_to] (unsortiert)."""
    try:
        raw = data._reservations(d_from, d_to)
    except smoobu.SmoobuError as ex:
        ui.notify(t("Smoobu: {fehler}", fehler=ex), type="negative", timeout=8000)
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
        ui.notify(t("Smoobu: {fehler}", fehler=ex), type="negative", timeout=8000)
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


def _open_checkliste(job, activate):
    """Sprung Buchung → Checkliste. Nimmt den ganzen Job mit, damit in der
    Checkliste steht, für wie viele Personen einzudecken ist."""
    nxt = job.get("next") or None
    _PENDING_REINIGUNG["apt"] = (job["apartment_id"], job["apartment_name"])
    _PENDING_REINIGUNG["return"] = "buchungen"   # nach Abschluss zurück zu Buchungen
    _PENDING_REINIGUNG["booking"] = job.get("id")
    _PENDING_REINIGUNG["co"] = job.get("checkout_time")
    _PENDING_REINIGUNG["ci"] = (nxt or {}).get("checkin_time")
    _PENDING_REINIGUNG["next"] = nxt
    _PENDING_REINIGUNG["same_day"] = bool(nxt and nxt.get("arrival") == job.get("departure"))
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
    """Status-Key. 'Fertig' nur, wenn die Checkliste VOLLSTÄNDIG erledigt ist UND
    Arbeitszeit erfasst wurde."""
    bid = job["id"]
    who = bookings.assignee_of(bid)
    entries = timetrack.entries_for_booking(bid)
    has_time = any(e.get("checkout") for e in entries)
    open_now = any(not e.get("checkout") for e in entries)
    started = bool(entries)
    dprog, tprog = _checklist_progress(job, None)
    fully_done = tprog > 0 and dprog >= tprog
    if fully_done and has_time:
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
    ui.chip(t(label), icon=icon).props(f"color={color} text-color=white dense") \
        .classes("shrink-0 whitespace-nowrap")


def render_buchungen(activate):
    user = _cur_user()
    admin = _is_admin()
    with ui.row().classes("w-full items-center gap-3"):
        ui.icon("calendar_month").classes("text-3xl text-primary")
        with ui.column().classes("gap-0"):
            ui.label(t("Buchungen")).classes("text-2xl font-bold text-slate-800 leading-tight")
            ui.label(t("Reinigungs-Übersicht & Buchungskalender")) \
                .classes("text-sm text-gray-500")
        ui.space()
        ui.button(icon="refresh", on_click=lambda: (data.clear_cache(), activate("buchungen"))) \
            .props("flat round").tooltip(t("Aktualisieren"))
    staff = _staff_users()
    with ui.tabs().props("dense no-caps align=left").classes("w-full") as tabs:
        t_clean = ui.tab(t("Reinigungen"), icon="cleaning_services")
        t_cal = ui.tab(t("Kalender"), icon="calendar_month")
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
                mode = ui.toggle({"multi": t("Alle Wohnungen"), "single": t("Einzeln")},
                                 value=state["mode"]).props("no-caps")
                mode.on_value_change(lambda e: (state.update(mode=e.value), render()))
                if state["mode"] == "single" and apts:
                    sel = ui.select(apts, value=state["apt"], label=t("Wohnung")) \
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
        ui.notify(t("Smoobu: {fehler}", fehler=ex), type="negative", timeout=8000)
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
        ui.button(t("Heute"), icon="today",
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
                            taken = "👤 " if bookings.assignee_of(b["id"]) else ""
                            bar = ui.label(taken + (b["guest"] or b["apartment_name"])).classes(
                                "absolute text-white text-xs truncate cursor-pointer rounded-full px-3 "
                                "shadow-sm hover:brightness-110").style(
                                f"left:{a_idx * CELL + 3}px; width:{w}px; top:8px; height:28px; "
                                f"line-height:28px; background:{hexc}") \
                                .tooltip(t("Reinigung übernommen") if taken else "")
                            bar.on("click", lambda _e, bk=b: open_booking_dialog(bk, user, admin, staff, activate))
            if not apts:
                ui.label(t("Keine Wohnungen geladen.")).classes("text-gray-500 p-4")


def _single_month(state, user, admin, staff, activate, rerender):
    """Monatskalender EINER Wohnung; Buchungen als durchgehende Balken pro Woche."""
    import calendar as _cal
    from datetime import timedelta
    aid = state["apt"]
    if not aid:
        ui.label(t("Keine Wohnung gewählt.")).classes("text-gray-500 mt-2")
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
        ui.notify(t("Smoobu: {fehler}", fehler=ex), type="negative", timeout=8000)
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
        ui.button(t("Heute"), icon="today",
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
                taken = "👤 " if bookings.assignee_of(b["id"]) else ""
                label = (taken + (b["guest"] or name)) if (a >= ws) else ""
                bar = ui.label(label).classes(
                    "text-white text-xs truncate cursor-pointer px-2 shadow-sm hover:brightness-110") \
                    .style(style)
                bar.on("click", lambda _e, bk=b: open_booking_dialog(bk, user, admin, staff, activate))


def _render_cleaning(user, admin, staff, activate):
    jobs = _cleaning_jobs()
    if not jobs:
        ui.label(t("Keine anstehenden Reinigungen.")).classes("text-gray-500 mt-4")
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
        ui.label(t("Überfällig ({n})", n=len(overdue))).classes("text-sm font-semibold text-red-600 mt-2")
        for j in overdue:
            _cleaning_card(j, user, admin, staff, activate)
    # Heute – volle Karten
    if todayj:
        ui.label(t("Heute ({n})", n=len(todayj))).classes("text-sm font-semibold text-primary mt-3")
        for j in todayj:
            _cleaning_card(j, user, admin, staff, activate)
    if not overdue and not todayj:
        ui.label(t("Heute keine Reinigungen. 🎉")).classes("text-gray-500 mt-2")

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


def _add_time_dialog(job, user, on_saved=None):
    """Arbeitszeit für diese Buchung manuell nachtragen."""
    from datetime import datetime
    with ui.dialog() as dlg, ui.card().classes("w-[420px] max-w-full gap-2"):
        ui.label(t("Arbeitszeit nachtragen – {wohnung}", wohnung=job["apartment_name"])).classes("text-lg font-bold")
        d = ui.input(t("Datum"), value=job["departure"]).props("type=date outlined dense").classes("w-full")
        with ui.row().classes("w-full gap-2"):
            t1 = ui.input(t("Von"), value=(job.get("checkout_time") or "10:00")) \
                .props("type=time outlined dense").classes("flex-grow")
            t2 = ui.input(t("Bis"), value="12:00").props("type=time outlined dense").classes("flex-grow")

        def save():
            try:
                ci = datetime.fromisoformat(f"{d.value}T{t1.value}")
                co = datetime.fromisoformat(f"{d.value}T{t2.value}")
            except Exception:
                ui.notify(t("Bitte Datum und Uhrzeiten prüfen."), type="warning"); return
            if co <= ci:
                ui.notify(t("Ende muss nach Beginn liegen."), type="warning"); return
            timetrack.add_manual(user, ci, co, booking_id=job["id"], apartment=job["apartment_name"])
            ui.notify(t("Arbeitszeit nachgetragen: {dauer}",
                        dauer=timetrack.fmt_dur(int((co - ci).total_seconds() // 60))),
                      type="positive")
            dlg.close()
            if on_saved:
                on_saved()
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button(t("Abbrechen"), on_click=dlg.close).props("flat")
            ui.button(t("Speichern"), icon="save", on_click=save).props("unelevated")
    dlg.open()


def _checklist_progress(job, user):
    """(erledigt, gesamt) der Checkliste – zählt die TATSÄCHLICH abgehakten Aufgaben
    des relevanten Durchgangs (offen, sonst letzter für diese Wohnung)."""
    try:
        cl = housekeeping.get_checklist(job["apartment_id"])
        total = sum(len(r["tasks"]) for r in cl["rooms"])
    except Exception:
        total = 0
    run = housekeeping.get_open_run(job["apartment_id"], user)
    if not run:
        run = next((r for r in housekeeping.list_runs()
                    if str(r["apartment_id"]) == str(job["apartment_id"])), None)
    done = sum(1 for v in run["tasks"].values() if v.get("done")) if run else 0
    return min(done, total), total


def _step_button(label, icon, cb):
    """Listen-Zeile als Button (Icon · Label · Chevron)."""
    b = ui.button(on_click=cb).props("flat no-caps align=left").classes("w-full")
    with b:
        with ui.row().classes("w-full items-center gap-3 no-wrap"):
            ui.icon(icon).classes("text-primary")
            ui.label(label).classes("flex-grow text-left normal-case text-slate-700")
            ui.icon("chevron_right").classes("text-gray-300")


def _note_dialog(job, on_saved=None):
    rec = bookings.get_record(job["id"])
    with ui.dialog() as dlg, ui.card().classes("w-[420px] max-w-full gap-2"):
        ui.label(t("Notiz – {wohnung}", wohnung=job["apartment_name"])).classes("text-lg font-bold")
        ta = ui.textarea(t("Notiz"), value=rec.get("note", "")).props("outlined autogrow").classes("w-full")

        def save():
            bookings.set_field(job["id"], note=(ta.value or "").strip())
            ui.notify(t("Notiz gespeichert ✓"), type="positive"); dlg.close()
            if on_saved:
                on_saved()
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button(t("Abbrechen"), on_click=dlg.close).props("flat")
            ui.button(t("Speichern"), icon="save", on_click=save).props("unelevated")
    dlg.open()


def _restock_dialog(job, user, on_close=None):
    with ui.dialog() as dlg, ui.card().classes("w-[440px] max-w-full gap-2"):
        ui.label(t("Verbrauch / Wäsche – {wohnung}", wohnung=job["apartment_name"])).classes("text-lg font-bold")
        ui.label(t("Was muss nachgekauft werden?")).classes("text-sm text-gray-500")
        for it in housekeeping.get_inventory(job["apartment_id"]):
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.label(it["name"]).classes("flex-grow")
                qty = ui.input(t("Menge"), value="1").props("dense outlined").classes("w-20")

                def melden(name=it["name"], kat=it["kategorie"], q=qty):
                    housekeeping.add_restock(job["apartment_id"], job["apartment_name"],
                                             name, (q.value or "1").strip(), kat, user,
                                             booking_id=job.get("id"))
                    ui.notify(t("{name} gemeldet ✓", name=name), type="positive")
                ui.button(t("melden"), icon="add_shopping_cart", on_click=melden).props("flat dense no-caps")
        with ui.row().classes("w-full justify-end"):
            ui.button(t("Schließen"), on_click=lambda: (dlg.close(), on_close() if on_close else None)).props("flat")
    dlg.open()


def _cleaning_card(job, user, admin, staff, activate):
    """Voll-Karte gemäß Entwurf. Start/Stop zeichnet NUR diese Karte neu (kein
    Seiten-Sprung), daher lokales render() statt activate()."""
    from datetime import datetime
    nxt = job.get("next")
    same_day = bool(nxt and nxt["arrival"] == job["departure"])
    wrap = ui.column().classes("w-full")

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
            ui.notify(t("Du bist bereits an einem anderen Ort eingecheckt."), type="warning")
        else:
            ui.notify(t("Arbeitszeit gestartet ✓"), type="positive")
        render()

    async def _do_out():
        gps = None
        try:
            loc = await get_location()
            gps = None if loc.get("error") else loc
        except Exception:
            pass
        ort, dist = _match_geofence(gps)
        timetrack.check_out(user, gps, None, ort, dist)
        ui.notify(t("Arbeitszeit beendet ✓"), type="positive")
        render()

    def render():
        wrap.clear()
        with wrap:
            status = _booking_status(job)
            done_entries = [e for e in timetrack.entries_for_booking(job["id"]) if e.get("checkout")]
            total_min = sum(timetrack.duration_minutes(e) or 0 for e in done_entries)
            oe = timetrack.get_open(user)
            open_here = bool(oe and str(oe.get("booking_id")) == str(job["id"]))
            with ui.card().classes("w-full rounded-2xl shadow-sm border border-slate-100 gap-2 p-4 mt-1"):
                info = ui.column().classes("w-full gap-1 cursor-pointer").mark("booking-details")
                info.on("click", lambda: open_booking_dialog(job, user, admin, staff, activate))
                with info:
                    with ui.row().classes("w-full items-center gap-2 no-wrap"):
                        ui.icon("cleaning_services").classes("text-primary text-xl shrink-0")
                        ui.label(job["apartment_name"]).classes("font-bold text-lg leading-tight")
                        ui.space()
                        _status_chip(job)
                    if same_day:
                        ui.chip(t("Wechseltag"), icon="bolt").props("color=deep-orange text-color=white dense")
                    with ui.row().classes("w-full items-center gap-1 text-sm text-slate-600 no-wrap"):
                        ui.icon("logout").classes("text-deep-orange text-base")
                        ui.label(f"{t('Check-out')} {job['checkout_time'] or '—'}")
                        ui.icon("arrow_forward").classes("text-gray-400 text-sm")
                        ui.icon("login").classes("text-green-700 text-base")
                        ui.label(f"{t('Check-in')} {nxt['checkin_time'] if nxt else '—'}")

                # Ausserhalb von `info`, sonst öffnet jeder Tab-Klick den Dialog.
                _ab_an_tabs(job, nxt, same_day)

                if open_here:
                    checkin_dt = datetime.fromisoformat(oe["checkin"])
                    dprog, tprog = _checklist_progress(job, user)
                    complete = bool(tprog) and dprog >= tprog
                    with ui.card().classes("w-full bg-violet-50 rounded-xl p-3 gap-1 shadow-none"):
                        with ui.row().classes("w-full items-center"):
                            ui.label(t("Arbeitszeit läuft")).classes("text-xs text-gray-500")
                            ui.space()
                            if not complete:
                                ui.button(t("Beenden"), icon="stop_circle", on_click=_do_out) \
                                    .props("outline dense no-caps color=negative")
                        tl = ui.label("0:00:00").classes("text-3xl font-bold text-primary")

                        def tick(cd=checkin_dt, lbl=tl):
                            lbl.text = str(datetime.now().replace(microsecond=0) - cd.replace(microsecond=0))
                        tick()
                        ui.timer(1.0, tick)
                    with ui.row().classes("w-full items-center"):
                        ui.label(t("Checkliste")).classes("font-medium text-sm")
                        ui.space()
                        ui.label(f"{dprog}/{tprog} erledigt").classes("text-xs text-gray-500")
                    ui.linear_progress(value=(dprog / tprog if tprog else 0), show_value=False) \
                        .props(f"color={'green' if complete else 'primary'} rounded track-color=grey-3").classes("w-full")
                    if not complete:
                        ui.button(t("Weiter zur Checkliste"), icon="checklist",
                                  on_click=lambda: _open_checkliste(job, activate)) \
                            .props("unelevated no-caps size=lg").classes("w-full")
                    else:
                        with ui.row().classes("w-full items-center gap-1 text-sm text-green-700"):
                            ui.icon("check_circle").classes("text-base")
                            ui.label(t("Alle Aufgaben abgeschlossen"))
                        ui.label(t("Nächste Schritte")).classes("text-xs font-semibold text-gray-400 mt-1")
                        with ui.column().classes("w-full gap-1"):
                            _step_button("Fotos & Schäden prüfen", "photo_camera",
                                         lambda: open_damage_dialog(job["apartment_id"], job["apartment_name"], user, booking_id=job["id"]))
                            _step_button("Notiz hinzufügen", "sticky_note_2",
                                         lambda: _note_dialog(job))
                            _step_button("Verbrauch / Wäsche", "inventory_2",
                                         lambda: _restock_dialog(job, user))
                        ui.button(t("Arbeitszeit beenden"), icon="stop_circle", on_click=_do_out) \
                            .props("unelevated no-caps size=lg color=negative").classes("w-full mt-1")
                elif status == "abgeschlossen":
                    dprog, tprog = _checklist_progress(job, user)
                    with ui.row().classes("w-full items-center gap-2 text-sm text-green-700 bg-green-50 rounded-lg p-2"):
                        ui.icon("check_circle")
                        ui.label(t("Fertig · {dauer} · {done}/{total} erledigt",
                                    dauer=timetrack.fmt_dur(total_min), done=dprog, total=tprog))
                else:
                    if total_min:
                        ui.label(t("Erfasst {dauer}", dauer=timetrack.fmt_dur(total_min))).classes("text-xs text-gray-500")
                    ui.button(t("Arbeitszeit starten"), icon="play_arrow", on_click=_do_in) \
                        .props("unelevated no-caps size=lg").classes("w-full")
    render()


def _cleaning_compact(job, user, admin, staff, activate):
    nxt = job.get("next")
    card = ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100 p-3 cursor-pointer")
    card.on("click", lambda: open_booking_dialog(job, user, admin, staff, activate))
    with card:
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            ui.icon("home").classes("text-primary shrink-0")
            with ui.column().classes("gap-0 min-w-0 flex-grow"):
                ui.label(job["apartment_name"]).classes("font-medium truncate")
                ui.label(f"{t('Check-out')} {job['checkout_time'] or '—'} → "
                         f"{t('Check-in')} {nxt['checkin_time'] if nxt else '—'}") \
                    .classes("text-xs text-gray-500")
                # Nur die Anreise-Zahl – die Abreise-Personen stehen im Detail-Dialog,
                # nebeneinander werden sie zu leicht verwechselt.
                if nxt:
                    n = _pers_count(nxt)
                    ui.label(t("Vorbereiten für {n}", n=n) + " "
                             + (t("Person") if n == 1 else t("Personen"))) \
                        .classes("text-xs font-semibold text-green-700 truncate")
                else:
                    ui.label(t("keine Folgebuchung")).classes("text-xs text-gray-400 truncate")
            _status_chip(job)
            ui.icon("chevron_right").classes("text-gray-300 shrink-0")


def _event_card(ev, user, admin, staff, activate):
    is_out = ev["kind"] == "out"
    who = bookings.assignee_of(ev["id"])
    who_name = staff.get(who, who) if who else None
    with ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100 gap-1 p-3"):
        with ui.row().classes("w-full items-center gap-2 flex-wrap"):
            if is_out:
                ui.chip(t("Abreise"), icon="logout").props("color=deep-orange text-color=white dense")
            else:
                ui.chip(t("Anreise"), icon="login").props("color=green text-color=white dense")
            ui.label(ev["apartment_name"]).classes("font-semibold")
            with ui.row().classes("items-center gap-1 text-sm text-gray-500"):
                ui.icon("schedule").classes("text-base")
                ui.label(ev["time"] or "—")
            if ev.get("nights") is not None:
                with ui.row().classes("items-center gap-1 text-sm text-gray-500") \
                        .tooltip(t("Nächte")):
                    ui.icon("dark_mode").classes("text-base")
                    ui.label(f"{ev['nights']}")
            ui.space()
            if is_out:
                if who_name:
                    ui.chip(who_name, icon="person").props("color=primary text-color=white dense")
                else:
                    ui.chip(t("nicht zugewiesen"), icon="person_off").props("color=grey-4 dense")
        with ui.row().classes("w-full items-center gap-2 flex-wrap text-sm text-gray-500"):
            ui.label(f"{ev['guest'] or t('Gast')} · {ev['channel']}")
            ui.label(_persons_text(ev, True))
        with ui.row().classes("w-full items-center gap-2 flex-wrap mt-1"):
            ui.button(t("Öffnen"), icon="open_in_full",
                      on_click=lambda e=ev: open_booking_dialog(e, user, admin, staff, activate)) \
                .props("unelevated dense no-caps")
            if is_out and who != user:
                ui.button(t("Ich übernehme"), icon="how_to_reg",
                          on_click=lambda e=ev: _assign(e, user, user, staff, activate)) \
                    .props("outline dense no-caps")


def _assign(bk, assignee, by, staff, after, note=""):
    bookings.set_assignment(bk["id"], assignee, by, note)
    if assignee != by:   # jemandem anderen zugewiesen → benachrichtigen
        _notify_assignee(bk, assignee, by, staff)
    ui.notify(t("{wohnung} → {name} zugewiesen ✓", wohnung=bk["apartment_name"],
                name=staff.get(assignee, assignee)),
              type="positive")
    if after:
        after()


def _notify_assignee(bk, assignee, by, staff):
    to = _user_email(assignee)
    if not to:
        ui.notify(t("Hinweis: {name} hat keine E-Mail hinterlegt – "
                    "keine Benachrichtigung verschickt.",
                    name=staff.get(assignee, assignee)),
                  type="warning", timeout=8000)
        return
    body = (f"Hallo {staff.get(assignee, assignee)},\n\n"
            f"dir wurde eine Reinigung zugewiesen:\n\n"
            f"Wohnung: {bk['apartment_name']}\n"
            f"Abreise (Reinigung): {bk['departure']}, Check-out {bk['checkout_time'] or '—'}\n"
            f"Anreise nächster Gast: {bk['arrival']}\n"
            f"Personen: {bk['persons']}\n\n"
            f"Zugewiesen von: {staff.get(by, by)}\n\n"
            f"Bitte in der LIVARO-App bestätigen: {_app_url()}\n")
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
            f"App: {_app_url()}  →  Buchungen → Reinigungen\n")
    try:
        mailer.send_notify(CFG, to,
                           f"Bitte nachtragen: {job['apartment_name']} ({job['departure']})", body)
        bookings.set_field(job["id"], nachtragen_notified=bookings.now_iso())
    except mailer.MailError:
        pass   # später erneut versuchen (Flag nicht gesetzt)


def _open_swap(bk, user, staff, on_saved):
    who = bookings.assignee_of(bk["id"])
    others = {u: n for u, n in staff.items() if u != who}
    with ui.dialog() as dlg, ui.card().classes("w-[360px] max-w-full gap-2"):
        ui.label(t("Zuweisen / Tauschen – {wohnung}", wohnung=bk["apartment_name"])).classes("font-bold")
        if not others:
            ui.label(t("Keine weiteren Mitarbeiter.")).classes("text-sm text-gray-500")
        sel = ui.select(others, label=t("Mitarbeiter")).props("dense outlined").classes("w-full")

        def go():
            if not sel.value:
                ui.notify(t("Bitte Mitarbeiter wählen."), type="warning"); return
            dlg.close()
            _assign(bk, sel.value, user, staff, on_saved)
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button(t("Abbrechen"), on_click=dlg.close).props("flat")
            ui.button(t("Zuweisen"), icon="check", on_click=go).props("unelevated")
    dlg.open()


def _reset_dialog(bk, user, admin, staff, activate):
    """Admin: Auftrag zurücksetzen (Zuweisung, Checkliste, erfasste Zeiten)."""
    with ui.dialog() as dlg, ui.card().classes("w-[400px] max-w-full gap-2"):
        ui.label(t("Auftrag zurücksetzen – {wohnung}", wohnung=bk["apartment_name"])).classes("font-bold")
        ui.label(t("Setzt Zuweisung und Checklisten-Abschluss zurück und entfernt die für "
                   "diese Buchung erfassten Arbeitszeiten. Status wird wieder Nicht "
                   "zugewiesen. Die interne Notiz bleibt erhalten.")) \
            .classes("text-sm text-gray-500")

        def do():
            bookings.reset(bk["id"])
            n = timetrack.delete_for_booking(bk["id"])
            dlg.close()
            ui.notify(t("Auftrag zurückgesetzt (entfernte Zeiteinträge: {n}).", n=n), type="warning")
            open_booking_dialog(bk, user, admin, staff, activate)
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button(t("Abbrechen"), on_click=dlg.close).props("flat")
            ui.button(t("Zurücksetzen"), icon="restart_alt", on_click=do).props("unelevated color=negative")
    dlg.open()


def _run_photo_count(apt_id):
    """Anzahl aufgenommener Ist-Fotos im letzten Durchgang dieser Wohnung."""
    run = next((r for r in housekeeping.list_runs()
                if str(r["apartment_id"]) == str(apt_id)), None)
    if not run:
        return 0
    return sum(1 for v in run["tasks"].values() if v.get("ist_photo"))


def _booking_log(bk):
    """Protokoll: was für diese Buchung schon erledigt/gemeldet wurde."""
    bid = bk["id"]
    entries = [e for e in timetrack.entries_for_booking(bid) if e.get("checkout")]
    total_min = sum(timetrack.duration_minutes(e) or 0 for e in entries)
    dprog, tprog = _checklist_progress(bk, _cur_user())
    photos = _run_photo_count(bk["apartment_id"])
    dmgs = housekeeping.damages_for_booking(bid)
    rst = housekeeping.restock_for_booking(bid)
    something = entries or dprog or photos or dmgs or rst

    # Arbeitszeit
    with ui.row().classes("w-full items-center gap-2"):
        ui.icon("schedule").classes("text-primary")
        ui.label(t("Arbeitszeit: {dauer}",
                   dauer=timetrack.fmt_dur(total_min) if total_min else "0:00 h")
                 + (t(" ({n} Einträge)", n=len(entries)) if entries else "")).classes("text-sm font-medium")
    for e in entries:
        ui.label(f"· {_d(e['checkin'])} {_t(e['checkin'])}–{_t(e['checkout'])}"
                 + (t(" (nachgetragen)") if e.get("manual") else "")).classes("text-xs text-gray-500 pl-6")
    # Checkliste
    with ui.row().classes("w-full items-center gap-2 mt-1"):
        ui.icon("checklist").classes("text-primary")
        ui.label(t("Checkliste: {done}/{total} erledigt · {fotos} Foto(s)",
                   done=dprog, total=tprog, fotos=photos)).classes("text-sm font-medium")
    # Schäden
    with ui.row().classes("w-full items-center gap-2 mt-1"):
        ui.icon("report_problem").classes("text-red-600")
        ui.label(t("Schäden gemeldet: {n}", n=len(dmgs))).classes("text-sm font-medium")
    for d in dmgs:
        with ui.row().classes("w-full items-start gap-2 pl-6 no-wrap"):
            if d.get("photo"):
                _photo_thumb(f"/media/{d['photo']}", "w-12 h-12")
            ui.label(f"{d.get('room') or '—'} · {d['desc']} ({d['urgency']})"
                     + ("" if d["status"] == "offen" else " ✓")).classes("text-xs text-gray-600")
    # Verbrauch / Wäsche
    with ui.row().classes("w-full items-center gap-2 mt-1"):
        ui.icon("inventory_2").classes("text-primary")
        ui.label(t("Nachbestellt: {n}", n=len(rst))).classes("text-sm font-medium")
    for r in rst:
        ui.label(f"· {r['menge']}× {r['item']}" + ("" if r["status"] == "offen" else " ✓")) \
            .classes("text-xs text-gray-600 pl-6")

    if not something:
        ui.label(t("Für diese Buchung wurde noch nichts erfasst.")).classes("text-sm text-gray-400 mt-2")


def _msg_time(s):
    """Smoobu-Zeitstempel '2026-04-07 19:09:46' -> '07.04. 19:09'."""
    from datetime import datetime
    s = (s or "").strip()
    try:
        return datetime.strptime(s[:16], "%Y-%m-%d %H:%M").strftime("%d.%m. %H:%M")
    except Exception:
        return s


def _confirm_send_guest(bk, textarea, reload_cb):
    """Bestätigungsdialog vor dem Live-Versand einer Gast-Antwort über Smoobu."""
    text = (textarea.value or "").strip()
    if not text:
        ui.notify(t("Bitte zuerst eine Antwort eingeben."), type="warning")
        return
    with ui.dialog() as cd, ui.card().classes("w-[420px] max-w-full gap-2"):
        ui.label(t("Nachricht an den Gast senden?")).classes("text-lg font-bold")
        ui.label(t("Gast: {name}", name=bk.get("guest") or "—")).classes("text-sm text-gray-500")
        with ui.column().classes("w-full bg-gray-50 rounded p-2 max-h-[30vh] overflow-auto"):
            ui.label(text).classes("text-sm whitespace-pre-wrap")
        ui.label(t("Die Nachricht wird sofort über Smoobu an den Gast zugestellt.")) \
            .classes("text-xs text-amber-700")

        async def _do():
            from nicegui import run
            api_key = (CFG.get("smoobu_api_key") or "").strip()
            if not api_key:
                ui.notify(t("Kein Smoobu-API-Key konfiguriert."), type="negative")
                return
            try:
                await run.io_bound(smoobu.send_message, api_key, bk["id"], text)
            except Exception as ex:
                ui.notify(t("Senden fehlgeschlagen: {fehler}", fehler=ex), type="negative")
                return
            cd.close()
            textarea.value = ""
            ui.notify(t("Nachricht an den Gast gesendet."), type="positive")
            await reload_cb(True)

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button(t("Abbrechen"), on_click=cd.close).props("flat no-caps")
            ui.button(t("Senden"), icon="send", on_click=_do).props("unelevated no-caps color=primary")
    cd.open()


def _render_guest_thread(box, msgs, err, reload_cb, bk):
    """Nachrichtenverlauf (type 1 = Gast, type 2 = wir) als Chat + Antwortfeld.

    box ist eine Spalte mit fester Höhe: Kopf + Antwortfeld bleiben fix, nur der
    Verlauf in der Mitte scrollt (WhatsApp-/Smoobu-Stil)."""
    box.clear()
    with box:
        # --- Kopf (fix) -----------------------------------------------------
        with ui.row().classes("w-full items-center shrink-0 pb-1"):
            ui.label(t("Gästekommunikation")).classes("text-xs font-semibold text-gray-400")
            ui.space()
            ui.button(icon="refresh", on_click=lambda: reload_cb(True)) \
                .props("flat round dense size=sm").tooltip(t("Aktualisieren"))
        # --- Verlauf (scrollt) ---------------------------------------------
        thread = ui.column().classes(
            "w-full gap-2 flex-grow overflow-auto min-h-0 py-1 pr-1")
        with thread:
            if err:
                with ui.row().classes("w-full items-center gap-2 bg-red-50 rounded p-2"):
                    ui.icon("error_outline").classes("text-red-500")
                    ui.label(t("Nachrichten konnten nicht geladen werden: {fehler}", fehler=err)) \
                        .classes("text-xs text-red-700")
            elif not msgs:
                ui.label(t("Noch keine Nachrichten zu dieser Buchung.")) \
                    .classes("text-sm text-gray-400 m-auto")
            for m in msgs:
                mine = m.get("type") == 2
                with ui.row().classes("w-full no-wrap "
                                      + ("justify-end" if mine else "justify-start")):
                    with ui.column().classes(
                            "gap-0 rounded-2xl px-3 py-2 max-w-[82%] "
                            + ("bg-primary text-white rounded-br-sm" if mine
                               else "bg-gray-100 rounded-bl-sm")):
                        subj = (m.get("subject") or "").strip()
                        if subj:
                            ui.label(subj).classes(
                                "text-xs font-semibold "
                                + ("text-white/90" if mine else "text-gray-600"))
                        ui.label((m.get("message") or "").strip() or "—") \
                            .classes("text-sm whitespace-pre-wrap break-words")
                        ui.label(_msg_time(m.get("createdAt"))).classes(
                            "text-[10px] self-end "
                            + ("text-white/70" if mine else "text-gray-400"))
        # neueste Nachricht sichtbar: Verlauf ans Ende scrollen
        if msgs:
            thread_id = thread.id
            ui.timer(0.05, lambda: ui.run_javascript(
                f"const e=document.getElementById('c{thread_id}');"
                f" if(e) e.scrollTop=e.scrollHeight;"), once=True)
        # --- Antwortfeld (fix, unten) --------------------------------------
        if not err:
            with ui.column().classes("w-full gap-1 shrink-0 pt-2 border-t border-gray-100"):
                ta = ui.textarea(placeholder=t("Antwort an den Gast …")) \
                    .props("outlined autogrow dense").classes("w-full") \
                    .style("max-height:96px;overflow-y:auto")
                with ui.row().classes("w-full items-center gap-2"):
                    ui.label(t("Wird direkt über Smoobu an den Gast gesendet.")) \
                        .classes("text-[11px] text-gray-400 flex-grow")
                    ui.button(t("Senden"), icon="send",
                              on_click=lambda: _confirm_send_guest(bk, ta, reload_cb)) \
                        .props("unelevated no-caps")


def open_booking_dialog(bk, user, admin, staff, activate):
    who = bookings.assignee_of(bk["id"])
    nxt = bk.get("next")
    same_day = bool(nxt and nxt["arrival"] == bk["departure"])
    # Nach einer Aktion wieder in dieser Detailübersicht landen:
    reopen = lambda: open_booking_dialog(bk, user, admin, staff, activate)
    with ui.dialog() as dlg, ui.card().classes("w-[460px] max-w-full gap-0 p-0 max-h-[92vh] overflow-auto"):
        with ui.row().classes("w-full items-center gap-2 p-3 pb-1"):
            ui.icon("home").classes("text-primary text-2xl")
            ui.label(bk["apartment_name"]).classes("text-xl font-bold")
            ui.space()
            # Schließen aktualisiert die dahinterliegende Liste
            ui.button(icon="close", on_click=lambda: (dlg.close(), activate("buchungen"))) \
                .props("flat round dense")
        mgr = _cur_role() in ("admin", "manager")   # Nachrichten nur Admin/Manager
        _hooks = {}
        with ui.tabs().props("dense no-caps align=left inline-label").classes("w-full px-2") as tabs:
            t_b = ui.tab(t("Buchung"))
            t_log = ui.tab(t("Protokoll"))
            t_g = ui.tab(t("Gast"))
            t_n = ui.tab(t("Notizen"))
            if mgr:
                t_msg = ui.tab(t("Nachrichten"))
        with ui.tab_panels(tabs, value=t_b).classes("w-full"):
            with ui.tab_panel(t_b):
                with ui.grid(columns=2).classes("w-full gap-x-4 gap-y-1 text-sm"):
                    ui.label(t("Anreise")).classes("text-gray-500")
                    ui.label(f"{_dfmt(bk['arrival'])} · {bk['checkin_time'] or '—'}")
                    ui.label(t("Abreise")).classes("text-gray-500")
                    ui.label(f"{_dfmt(bk['departure'])} · {bk['checkout_time'] or '—'}")
                    ui.label(t("Personen")).classes("text-gray-500")
                    ui.label(_persons_text(bk, True))
                    ui.label(t("Gast")).classes("text-gray-500")
                    ui.label(bk["guest"] or "—")
                    ui.label(t("Buchungskanal")).classes("text-gray-500")
                    ui.label(bk["channel"] or "—")
                if nxt:
                    with ui.column().classes("w-full gap-0 rounded-lg p-2 mt-2 "
                                             + ("bg-red-50" if same_day else "bg-green-50")):
                        ui.label(t("Anreise vorbereiten für")).classes(
                            "text-xs " + ("text-red-500" if same_day else "text-gray-500"))
                        ui.label(_guest_persons(nxt, True)).classes(
                            "text-sm font-semibold " + ("text-red-700" if same_day else "text-green-700"))
                        ui.label(t("Nächste Anreise: {datum} · {zeit}",
                                    datum=_dfmt(nxt["arrival"]), zeit=nxt["checkin_time"] or "")
                                 + (f" ({t('Wechseltag')})" if same_day else "")).classes("text-xs text-gray-500")
            with ui.tab_panel(t_log):
                _booking_log(bk)
            with ui.tab_panel(t_g):
                with ui.grid(columns=2).classes("w-full gap-x-4 gap-y-1 text-sm"):
                    ui.label(t("Name")).classes("text-gray-500")
                    ui.label(bk["guest"] or "—")
                    ui.label(t("E-Mail")).classes("text-gray-500")
                    ui.label(bk.get("email") or "—")
                    ui.label(t("Telefon")).classes("text-gray-500")
                    ui.label(bk.get("phone") or "—")
            with ui.tab_panel(t_n):
                intern = bookings.get_record(bk["id"]).get("note", "")
                if intern:
                    ui.label(t("Interne Notiz")).classes("text-xs text-gray-500")
                    ui.label(intern).classes("text-sm whitespace-pre-wrap")
                    ui.separator().classes("my-1")
                ui.label(t("Buchungsdetails (Smoobu)")).classes("text-xs text-gray-500")
                ui.label(bk["notice"] or "—").classes("text-sm whitespace-pre-wrap")
            if mgr:
                with ui.tab_panel(t_msg).classes("p-2"):
                    # feste Höhe: Verlauf scrollt intern, Antwortfeld bleibt unten sichtbar
                    _mbox = ui.column().classes("w-full gap-0 h-[68vh] no-wrap")
                    _mstate = {"loaded": False, "busy": False}

                    async def load_msgs(force=False):
                        if _mstate["busy"] or (_mstate["loaded"] and not force):
                            return
                        _mstate["busy"] = True
                        _mbox.clear()
                        with _mbox:
                            ui.spinner(size="lg").classes("m-auto")
                        from nicegui import run
                        api_key = (CFG.get("smoobu_api_key") or "").strip()
                        err, msgs = None, []
                        if not api_key:
                            err = "Kein Smoobu-API-Key konfiguriert."
                        else:
                            try:
                                msgs = await run.io_bound(smoobu.get_messages, api_key, bk["id"])
                            except Exception as ex:
                                err = str(ex)
                        _mstate["loaded"], _mstate["busy"] = True, False
                        _render_guest_thread(_mbox, msgs, err, load_msgs, bk)

                    _hooks["load"] = load_msgs

        footer_box = ui.column().classes("w-full gap-0 p-0")
        with footer_box:
            ui.separator()
            ui.label(t("Aktionen")).classes("text-xs font-semibold text-gray-400 px-3 pt-1")

            def action(label, icon, cb, color="primary"):
                b = ui.button(on_click=cb).props("flat no-caps align=left").classes("w-full")
                with b:
                    with ui.row().classes("w-full items-center gap-3 no-wrap"):
                        ui.icon(icon).classes(f"text-{color}")
                        ui.label(label).classes("flex-grow text-left normal-case text-slate-700")
                        ui.icon("chevron_right").classes("text-gray-300")
            if who != user:
                action(t("Ich übernehme diesen Auftrag"), "how_to_reg",
                       lambda: (dlg.close(), _assign(bk, user, user, staff, reopen)))
            action(t("Tauschen / Zuweisen"), "swap_horiz",
                   lambda: (dlg.close(), _open_swap(bk, user, staff, reopen)))
            action(t("Zeit nachtragen"), "more_time",
                   lambda: (dlg.close(), _add_time_dialog(bk, user, on_saved=reopen)))
            action(t("Notiz hinzufügen"), "sticky_note_2",
                   lambda: (dlg.close(), _note_dialog(bk, on_saved=reopen)))
            action(t("Verbrauch / Wäsche"), "inventory_2",
                   lambda: (dlg.close(), _restock_dialog(bk, user, on_close=reopen)))
            action(t("Schaden melden"), "report_problem",
                   lambda: (dlg.close(), open_damage_dialog(bk["apartment_id"], bk["apartment_name"], user, on_saved=reopen, booking_id=bk["id"])),
                   color="negative")
            action(t("Checkliste & Fotos"), "checklist",
                   lambda: (dlg.close(), _open_checkliste(bk, activate)))
            if admin:
                action(t("Zurücksetzen (Admin)"), "restart_alt",
                       lambda: (dlg.close(), _reset_dialog(bk, user, admin, staff, activate)), color="negative")

        if mgr:
            async def _on_tab(e):
                # Im Nachrichten-Tab die Aktionsliste ausblenden (mehr Platz für den Chat)
                footer_box.set_visibility(e.value != "Nachrichten")
                if e.value == "Nachrichten":
                    await _hooks["load"]()
            tabs.on_value_change(_on_tab)
    dlg.open()


def _beleg_mirror():
    return CFG.get("belege_ordner") or None


# Client-Scanner: Foto aufnehmen, dann Ecken von Hand ziehen.
#
# Die automatische Kantenerkennung (OpenCV.js + jscanify) traf Belege zu
# unzuverlässig – Kassenbons auf hellem Untergrund liefern kaum Kanten. Der
# Ablauf ist deshalb zweistufig und kommt ohne Fremdbibliothek aus:
#
#   1. Kamera -> "Foto aufnehmen" friert das Bild ein
#   2. Vier Eckpunkte liegen als Rechteck auf dem Bild und lassen sich per
#      Finger/Maus ziehen; eine Lupe zeigt den Bereich unter dem Finger
#   3. Beim Speichern gehen Bild + Ecken (als Anteile 0..1) an Python, das
#      serverseitig perspektivisch entzerrt und die A4-PDF baut
#
# Kein OpenCV.js (10 MB) und kein jscanify mehr – reines Canvas.
_SCAN_JS = r"""
(function(){
  let tries=0;
  function start(){
    const wrap=document.getElementById('beleg-scan');
    if(!wrap){ if(tries++<30){setTimeout(start,100);} return; }
    if(wrap.dataset.init) return; wrap.dataset.init='1';

    const video=wrap.querySelector('video');
    const cv2=wrap.querySelector('canvas.edit');      // Bearbeitungsflaeche
    const status=wrap.querySelector('.scan-status');
    const ctx=cv2.getContext('2d');
    const M=k=>wrap.dataset[k]||'';

    const shot=document.createElement('canvas');      // Originalaufloesung
    let stream=null, img=null, pts=null, drag=-1, dpr=window.devicePixelRatio||1;

    function setStatus(t){ if(status) status.textContent=t; }
    function phase(p){
      wrap.dataset.phase=p;
      video.style.display   = p==='cam'  ? 'block':'none';
      cv2.style.display     = p==='edit' ? 'block':'none';
      document.querySelectorAll('.beleg-cam').forEach(e=>e.style.display = p==='cam' ?'':'none');
      document.querySelectorAll('.beleg-edit').forEach(e=>e.style.display = p==='edit'?'':'none');
    }

    async function init(){
      try{
        setStatus(M('msgCam'));
        stream=await navigator.mediaDevices.getUserMedia(
          {video:{facingMode:{ideal:'environment'},
                  width:{ideal:2560},height:{ideal:1440}},audio:false});
        video.srcObject=stream; await video.play();
        phase('cam'); setStatus(M('msgAim'));
      }catch(err){
        phase('cam');
        setStatus(M('msgNoCam')+' ('+((err&&err.message)||err)+')');
      }
    }

    function stopCam(){
      if(stream){ try{stream.getTracks().forEach(t=>t.stop());}catch(e){} stream=null; }
    }

    // ---- Schritt 1: Foto einfrieren -------------------------------------
    function capture(){
      const w=video.videoWidth,h=video.videoHeight;
      if(!w||!h){ setStatus(M('msgNoFrame')); return; }
      shot.width=w; shot.height=h;
      shot.getContext('2d').drawImage(video,0,0,w,h);
      stopCam();
      img=new Image();
      img.onload=()=>{ resetPts(); layout(); phase('edit'); setStatus(M('msgDrag')); };
      img.src=shot.toDataURL('image/jpeg',0.95);
    }

    // Startrechteck mit 8 % Rand – bewusst grosszuegig, damit alle vier
    // Griffe sichtbar im Bild liegen und nicht am Rand kleben.
    function resetPts(){ const a=0.08,b=1-a; pts=[[a,a],[b,a],[b,b],[a,b]]; }

    function layout(){
      const maxW=wrap.clientWidth||360, maxH=Math.round(window.innerHeight*0.52);
      const s=Math.min(maxW/img.width, maxH/img.height);
      const w=Math.round(img.width*s), h=Math.round(img.height*s);
      cv2.style.width=w+'px'; cv2.style.height=h+'px';
      cv2.width=Math.round(w*dpr); cv2.height=Math.round(h*dpr);
      draw();
    }

    function P(i){ return [pts[i][0]*cv2.width, pts[i][1]*cv2.height]; }

    function draw(){
      if(!img) return;
      ctx.clearRect(0,0,cv2.width,cv2.height);
      ctx.drawImage(img,0,0,cv2.width,cv2.height);
      // Bereich ausserhalb der Auswahl abdunkeln
      ctx.save();
      ctx.beginPath(); ctx.rect(0,0,cv2.width,cv2.height);
      ctx.moveTo(...P(0)); for(let i=3;i>=1;i--) ctx.lineTo(...P(i));
      ctx.closePath();
      ctx.fillStyle='rgba(0,0,0,.45)'; ctx.fill('evenodd');
      ctx.restore();
      // Auswahlkanten
      ctx.beginPath(); ctx.moveTo(...P(0));
      for(let i=1;i<4;i++) ctx.lineTo(...P(i));
      ctx.closePath();
      ctx.lineWidth=Math.max(2,cv2.width/300); ctx.strokeStyle='#16a34a'; ctx.stroke();
      // Griffe
      const r=Math.max(10,cv2.width/45);
      for(let i=0;i<4;i++){
        const [x,y]=P(i);
        ctx.beginPath(); ctx.arc(x,y,r,0,6.2832);
        ctx.fillStyle= drag===i ? 'rgba(22,163,74,.95)' : 'rgba(255,255,255,.9)';
        ctx.fill(); ctx.lineWidth=Math.max(2,r/5); ctx.strokeStyle='#16a34a'; ctx.stroke();
      }
      if(drag>=0) magnifier(P(drag));
    }

    // Lupe: der Finger verdeckt die Ecke, deshalb den Ausschnitt daneben zeigen
    function magnifier(p){
      const R=Math.min(cv2.width,cv2.height)*0.16, Z=2.5;
      const cx = p[0] < cv2.width/2 ? cv2.width-R-8 : R+8;
      const cy = R+8;
      ctx.save();
      ctx.beginPath(); ctx.arc(cx,cy,R,0,6.2832); ctx.clip();
      ctx.fillStyle='#000'; ctx.fillRect(cx-R,cy-R,2*R,2*R);
      ctx.drawImage(img, 0,0, img.width,img.height,
                    cx-p[0]*Z, cy-p[1]*Z, cv2.width*Z, cv2.height*Z);
      ctx.beginPath(); ctx.moveTo(cx-R,cy); ctx.lineTo(cx+R,cy);
      ctx.moveTo(cx,cy-R); ctx.lineTo(cx,cy+R);
      ctx.strokeStyle='rgba(22,163,74,.9)'; ctx.lineWidth=1.5; ctx.stroke();
      ctx.restore();
      ctx.beginPath(); ctx.arc(cx,cy,R,0,6.2832);
      ctx.strokeStyle='#16a34a'; ctx.lineWidth=2; ctx.stroke();
    }

    function pos(ev){
      const r=cv2.getBoundingClientRect();
      const t=(ev.touches&&ev.touches[0])||ev;
      return [(t.clientX-r.left)/r.width, (t.clientY-r.top)/r.height];
    }
    function nearest(q){
      let best=-1,bd=1e9;
      for(let i=0;i<4;i++){
        const d=Math.hypot(pts[i][0]-q[0], pts[i][1]-q[1]);
        if(d<bd){ bd=d; best=i; }
      }
      return bd<0.12 ? best : -1;          // nur greifen, wenn nah genug
    }
    function down(ev){ if(!img) return; drag=nearest(pos(ev)); if(drag>=0){ ev.preventDefault(); draw(); } }
    function move(ev){
      if(drag<0) return;
      ev.preventDefault();
      const q=pos(ev);
      pts[drag]=[Math.min(1,Math.max(0,q[0])), Math.min(1,Math.max(0,q[1]))];
      draw();
    }
    function up(){ if(drag>=0){ drag=-1; draw(); } }

    cv2.addEventListener('mousedown',down);   cv2.addEventListener('touchstart',down,{passive:false});
    window.addEventListener('mousemove',move); cv2.addEventListener('touchmove',move,{passive:false});
    window.addEventListener('mouseup',up);     cv2.addEventListener('touchend',up);
    window.addEventListener('resize',()=>{ if(img) layout(); });

    // ---- Schritt 2: Datei waehlen statt Kamera --------------------------
    function fromFile(file){
      if(!file) return;
      const fr=new FileReader();
      fr.onload=()=>{
        stopCam();
        img=new Image();
        img.onload=()=>{
          shot.width=img.width; shot.height=img.height;
          shot.getContext('2d').drawImage(img,0,0);
          resetPts(); layout(); phase('edit'); setStatus(M('msgDrag'));
        };
        img.src=fr.result;
      };
      fr.readAsDataURL(file);
    }

    window.__belegCapture=capture;
    window.__belegRetake=function(){ img=null; phase('cam'); init(); };
    window.__belegReset=function(){ if(img){ resetPts(); draw(); } };
    window.__belegFile=function(){
      const inp=document.createElement('input');
      inp.type='file'; inp.accept='image/*';
      inp.onchange=()=>fromFile(inp.files&&inp.files[0]);
      inp.click();
    };
    window.__belegStop=stopCam;
    window.__belegSave=function(){
      if(!img||!pts) return;
      setStatus(M('msgWork'));
      emitEvent('beleg_scan', {image: shot.toDataURL('image/jpeg',0.92), corners: pts});
    };
    init();
  }
  start();
})();
"""


def render_belege():
    user = _cur_user()
    admin = _is_admin()
    with ui.row().classes("w-full items-center gap-3"):
        ui.icon("receipt").classes("text-3xl text-primary")
        with ui.column().classes("gap-0"):
            ui.label(t("Belege")).classes("text-2xl font-bold text-slate-800 leading-tight")
            ui.label(t("Rechnungen scannen, ablegen & per OCR auslesen")) \
                .classes("text-sm text-gray-500")

    apts = _apts()
    sc = {"apt": None, "dlg": None}

    def _process_and_add(data, ext, crop, corners=None):
        """Beleg-Bytes -> Dokument/PDF + OCR + Datensatz (blockierender Teil).

        corners: die im Scanner gesetzten Ecken (Anteile 0..1); sie haben
        Vorrang vor der automatischen Erkennung."""
        doc = receipts.save_document(data, ext, _beleg_mirror(), crop, corners)
        try:
            text = receipts.ocr_image(os.path.join(housekeeping.MEDIA_DIR, doc["photo"]))
        except Exception:
            text = ""
        aid = sc["apt"]
        receipts.add_receipt(user, doc["photo"], ocr_text=text,
                             amount=receipts.guess_amount(text),
                             merchant=receipts.guess_merchant(text), pdf=doc.get("pdf"),
                             apartment_id=aid, apartment_name=apts.get(aid, ""))
        return doc

    def _open_scanner():
        """Zweistufig: erst Foto aufnehmen, dann die vier Ecken von Hand ziehen.
        Die automatische Kantenerkennung war auf Belegen zu unzuverlaessig."""
        state = {"busy": False}

        def js(code):
            ui.run_javascript(code)

        with ui.dialog().props("persistent") as dlg, \
                ui.card().classes("w-[560px] max-w-full gap-2").mark("scan-dialog"):
            with ui.row().classes("w-full items-center"):
                ui.label(t("Beleg scannen")).classes("font-bold")
                ui.space()
                ui.button(icon="close",
                          on_click=lambda: (js("window.__belegStop&&window.__belegStop()"),
                                            dlg.close())).props("flat round dense")

            msgs = {
                "msg-cam": t("Kamera wird gestartet …"),
                "msg-no-cam": t("Kamera nicht verfügbar – wähle ein Foto aus."),
                "msg-aim": t("Beleg fotografieren – Ränder müssen mit aufs Bild."),
                "msg-drag": t("Ecken auf die Belegkanten ziehen."),
                "msg-no-frame": t("Kamerabild noch nicht bereit – kurz warten."),
                "msg-work": t("Beleg wird verarbeitet (PDF, OCR) …"),
            }
            attrs = " ".join(f'data-{k}="{_esc_attr(v)}"' for k, v in msgs.items())
            ui.html(
                f'<div id="beleg-scan" style="width:100%" {attrs}>'
                '<video autoplay playsinline muted '
                'style="width:100%;border-radius:12px;background:#000;display:block"></video>'
                '<canvas class="edit" style="display:none;border-radius:12px;'
                'background:#000;margin:0 auto;touch-action:none"></canvas>'
                '<div class="scan-status" style="font-size:12px;color:#6b7280;'
                'margin-top:6px;text-align:center;min-height:18px"></div></div>',
                # Selbst erzeugtes Markup; die Texte sind per _esc_attr entschaerft.
                # Ohne sanitize=False entfernt NiceGUI <video>/<canvas>.
                sanitize=False)

            async def _on_scan(e):
                """Bild + Ecken aus dem Browser entgegennehmen."""
                if state["busy"]:
                    return
                state["busy"] = True
                try:
                    from nicegui import run
                    payload = e.args or {}
                    url = payload.get("image") or ""
                    corners = payload.get("corners") or None
                    try:
                        raw = base64.b64decode(url.split(",", 1)[1])
                    except Exception:
                        ui.notify(t("Scan konnte nicht verarbeitet werden."), type="negative")
                        return
                    dlg.close()
                    ui.notify(t("Beleg wird verarbeitet (PDF, OCR) …"), type="info", timeout=3000)
                    await run.io_bound(_process_and_add, raw, "jpg", False, corners)
                    ui.notify(t("Beleg gescannt ✓"), type="positive")
                    render()
                finally:
                    state["busy"] = False
            ui.on("beleg_scan", _on_scan)

            # --- Schritt 1: Kamera ---
            with ui.row().classes("w-full items-center gap-2 beleg-cam"):
                ui.button(t("Foto aufnehmen"), icon="photo_camera",
                          on_click=lambda: js("window.__belegCapture&&window.__belegCapture()")) \
                    .props("unelevated no-caps size=lg").classes("flex-grow")
                ui.button(icon="folder_open",
                          on_click=lambda: js("window.__belegFile&&window.__belegFile()")) \
                    .props("outline").tooltip(t("Vorhandenes Foto wählen"))

            # --- Schritt 2: Ecken ziehen ---
            with ui.column().classes("w-full gap-2 beleg-edit").style("display:none"):
                ui.label(t("Ziehe die vier Punkte auf die Ecken des Belegs. Der Bereich "
                           "wird geradegezogen und als PDF gespeichert.")) \
                    .classes("text-[11px] text-gray-500 text-center")
                with ui.row().classes("w-full items-center gap-2"):
                    ui.button(t("Neu aufnehmen"), icon="replay",
                              on_click=lambda: js("window.__belegRetake&&window.__belegRetake()")) \
                        .props("outline no-caps")
                    ui.button(t("Ecken zurücksetzen"), icon="crop_free",
                              on_click=lambda: js("window.__belegReset&&window.__belegReset()")) \
                        .props("flat no-caps")
                ui.button(t("Zuschneiden & speichern"), icon="check",
                          on_click=lambda: js("window.__belegSave&&window.__belegSave()")) \
                    .props("unelevated no-caps size=lg").classes("w-full")
        sc["dlg"] = dlg
        dlg.open()
        ui.run_javascript(_SCAN_JS)

    box = ui.column().classes("w-full gap-3")

    def render():
        box.clear()
        with box:
            # Upload-Karte
            with ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100 gap-2 p-4"):
                ui.label(t("Neuen Beleg hinzufügen")).classes("font-medium")
                ui.label(t("Live scannen (Rand wird erkannt) oder Foto/Datei wählen. "
                   "Das Dokument wird als PDF abgelegt und per OCR ausgelesen.")) \
                    .classes("text-xs text-gray-500")
                apt_sel = ui.select({None: t("— keine Wohnung —"), **apts}, value=sc["apt"],
                                    label=t("Für welche Wohnung?")).props("outlined dense") \
                    .classes("min-w-[220px]")
                apt_sel.on_value_change(lambda e: sc.update(apt=e.value))

                async def handle(e):
                    try:
                        content, name = await _read_upload(e)
                    except Exception as ex:
                        ui.notify(t("Upload fehlgeschlagen: {fehler}", fehler=ex), type="negative"); return
                    ext = (name.rsplit(".", 1)[-1] if "." in name else "jpg").lower()[:4] or "jpg"
                    ui.notify(t("Beleg wird verarbeitet (Zuschnitt, PDF, OCR) …"), type="info", timeout=4000)
                    from nicegui import run
                    doc = await run.io_bound(_process_and_add, content, ext, True)
                    ui.notify(t("Beleg erfasst ✓") + (t(" (als PDF)") if doc.get("pdf") else ""),
                              type="positive")
                    render()

                with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                    ui.button(t("Beleg scannen"), icon="document_scanner", on_click=_open_scanner) \
                        .props("unelevated no-caps").mark("scan-open")
                    ui.upload(auto_upload=True, on_upload=handle, label=t("Foto / Datei")) \
                        .props('accept="image/*"').classes("hk-upload max-w-[220px]")
                if not receipts.ocr_available():
                    ui.label(t("Hinweis: OCR (Tesseract) ist auf dem Server nicht installiert – "
                       "Belege werden gespeichert, aber nicht automatisch ausgelesen.")) \
                        .classes("text-xs text-amber-700")

            items = receipts.list_receipts()
            if not items:
                ui.label(t("Noch keine Belege abgelegt.")).classes("text-gray-500 mt-2")
                return
            cur_month = None
            for r in items:
                month = r["ts"][:7]
                if month != cur_month:
                    cur_month = month
                    ym = f"{_MONATE[int(month[5:7]) - 1]} {month[:4]}"
                    ui.label(ym).classes("text-sm font-semibold text-primary mt-3")
                _beleg_card(r, apts, user, admin, render)
    render()


_MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
           "August", "September", "Oktober", "November", "Dezember"]


def _beleg_card(r, apts, user, admin, rerender):
    with ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100 gap-2 p-3"):
        with ui.row().classes("w-full items-start gap-3 no-wrap"):
            if r.get("photo"):
                _photo_thumb(f"/media/{r['photo']}", "w-20 h-20")
            with ui.column().classes("gap-1 min-w-0 flex-grow"):
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    merch = ui.input(placeholder=t("Händler"), value=r.get("merchant", "")) \
                        .props("dense borderless").classes("font-semibold flex-grow min-w-0")
                    merch.on("blur", lambda e, i=r["id"], f=merch:
                             receipts.update_receipt(i, merchant=f.value or ""))
                    amount = ui.input(placeholder="€", value=r.get("amount", "")) \
                        .props("dense borderless").classes("w-20 text-right")
                    amount.on("blur", lambda e, i=r["id"], f=amount:
                              receipts.update_receipt(i, amount=f.value or ""))
                    ui.label("€").classes("text-sm text-gray-400")
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    ui.icon("home").classes("text-gray-400 text-sm shrink-0")
                    apt_sel = ui.select({None: "— keine Wohnung —", **apts},
                                        value=r.get("apartment_id")).props("dense borderless") \
                        .classes("min-w-0")
                    apt_sel.on_value_change(lambda e, i=r["id"]:
                                            receipts.update_receipt(i, apartment_id=e.value,
                                                                    apartment_name=apts.get(e.value, "")))
                ui.label(f"{_d(r['ts'])} · {r.get('uploader', '')}").classes("text-xs text-gray-400")
                note = ui.input(placeholder=t("Notiz (z. B. wofür)"),
                                value=r.get("note", "")).props("dense borderless").classes("w-full")
                note.on("blur", lambda e, i=r["id"], f=note:
                        receipts.update_receipt(i, note=f.value or ""))
            with ui.column().classes("items-center gap-1 shrink-0"):
                if r.get("pdf"):
                    ui.button(icon="picture_as_pdf",
                              on_click=lambda p=r["pdf"]: ui.navigate.to(f"/media/{p}", new_tab=True)) \
                        .props("flat round dense color=primary").tooltip(t("PDF öffnen"))
                if admin:
                    ui.button(icon="delete", on_click=lambda i=r["id"]: _del_beleg(i, rerender)) \
                        .props("flat round dense color=negative").tooltip(t("Beleg löschen"))
        if r.get("ocr_text"):
            with ui.expansion(t("Erkannter Text (OCR)"), icon="document_scanner").classes("w-full"):
                ui.label(r["ocr_text"]).classes("text-xs whitespace-pre-wrap text-gray-600")


def _del_beleg(receipt_id, rerender):
    with ui.dialog() as dlg, ui.card().classes("gap-2"):
        ui.label(t("Beleg wirklich löschen?")).classes("font-medium")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button(t("Abbrechen"), on_click=dlg.close).props("flat")
            ui.button(t("Löschen"), on_click=lambda: (receipts.delete_receipt(receipt_id),
                                                   dlg.close(),
                                                   ui.notify(t("Beleg gelöscht."), type="warning"),
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
                _zeit_list(timetrack.entries(user), apts, admin, staff, render, t("Meine Zeiten"), False)
                if admin:
                    ui.separator()
                    ui.label("Auswertung (Admin)").classes("text-lg font-semibold")
                    _admin_zeiten(apts, staff, render)
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
                ui.label(t("Willkommen, {name}!", name=_cur_user())).classes("text-lg font-medium text-slate-700")
                ui.label(t("Für deinen Zugang sind noch keine Bereiche freigeschaltet.")) \
                    .classes("text-gray-500")


def run():
    ui.run(host="127.0.0.1", port=int(CFG.get("port", 3001)),
           title="LIVARO Suites", reload=False, show=False,
           storage_secret=STORAGE_SECRET)


if __name__ in {"__main__", "__mp_main__"}:
    run()
