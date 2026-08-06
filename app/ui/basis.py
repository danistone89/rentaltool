"""Gemeinsame Grundlage der Oberflaeche: Konfiguration, Sprache, Rollen.

Alles, was mehrere Bereiche brauchen und was selbst keinen Bereich kennt –
Konfiguration und Benutzerkonten, Sprachwahl, Rollen und sichtbare Bereiche,
Logo, kleine Format- und Foto-Helfer.

`basis` importiert bewusst **kein** anderes Oberflaechen-Modul. Damit ist es die
Wurzel des Abhaengigkeitsbaums und kann von jedem Bereich gefahrlos geladen
werden.
"""

import base64
from nicegui import app, ui
from datetime import date
from app import auth, data, housekeeping, i18n, mode, smoobu, timetrack

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


def _checklisten_an():
    """Sind die Reinigungs-Checklisten (samt Soll-/Ist-Fotos) eingeschaltet?

    Für den Start bewusst AUS: Checklisten müssen je Wohnung gepflegt werden und
    verlangen Foto-Disziplin – beim Einführen ist das zu viel auf einmal. Der
    Schalter steht in den Einstellungen (Reinigung); Code und bereits erfasste
    Daten bleiben erhalten. Ausgeblendet werden: der Checklisten-Durchgang,
    „Checkliste & Fotos“, der Fortschrittsbalken sowie in der Übersicht der Tab
    „Durchgänge“ und die Checklisten-Konfiguration.
    """
    return bool(CFG.get("checklisten_aktiv", False))


def _cur_area(default="buchungen"):
    """Bereich, in dem der Nutzer gerade ist.

    Aktionen aus einem Buchungs-Dialog heraus bauen die Liste dahinter neu auf.
    Ohne diesen Merker landeten sie immer in „Buchungen“ – auch wenn man aus
    der „Übersicht“ kam. Steht in der Sitzung, nicht global: sonst würden sich
    mehrere angemeldete Nutzer gegenseitig umschalten.
    """
    return app.storage.user.get("area") or default


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


def _probe_hinweis():
    """Unuebersehbares Kennzeichen der Probe-Instanz.

    Die Probe laeuft mit einer Kopie der echten Daten und sieht deshalb genau
    aus wie der Echtbetrieb. Wer das verwechselt, sucht spaeter Eintraege, die
    er auf der falschen Instanz gemacht hat.
    """
    if not mode.STAGING:
        return
    ui.chip(mode.LABEL, icon="science") \
        .props("color=deep-orange text-color=white dense square") \
        .classes("text-xs font-bold")

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


# ---------------------------------------------------------------- Reinigung
def _apts():
    return dict(_load_apartments())


def _photo_mirror():
    # Kein Spiegel auf der Probe-Instanz – sonst lägen Testfotos in der echten
    # Nextcloud (siehe app/mode.py).
    if mode.STAGING:
        return None
    return CFG.get("reinigung_ordner") or None


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
    r = housekeeping.get_run(run_id)
    return r["tasks"].get(task_id, {}).get("ist_photo") if r else None


_MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
           "August", "September", "Oktober", "November", "Dezember"]
