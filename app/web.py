#!/usr/bin/env python3
"""NiceGUI-Oberfläche für die Beherbergungssteuer-App.

Start:  python3 app/web.py   (Port aus config.json, Default 3001)
Öffnen: http://localhost:3001/

Reines Python-Frontend (NiceGUI). Fachlogik unverändert in
smoobu.py / steuer.py / pdf_form.py; Glue in data.py.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nicegui import app, ui  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from starlette.responses import RedirectResponse  # noqa: E402

from app import data, smoobu, archive, mailer, auth  # noqa: E402
try:
    from app import pdf_form
except Exception:  # PyMuPDF optional
    pdf_form = None

CFG = data.CONFIG
AUTH = CFG.setdefault("auth", {})
_new_secret = not AUTH.get("storage_secret")
STORAGE_SECRET = auth.ensure_storage_secret(AUTH)
if _new_secret:
    data.save_config()  # neu erzeugtes storage_secret persistieren

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


# ---------------------------------------------------------------- Login
@ui.page("/login")
def login_page():
    ui.colors(primary="#1f6feb")
    if app.storage.user.get("authenticated"):
        ui.navigate.to("/")
        return

    def finish():
        app.storage.user["authenticated"] = True
        ui.navigate.to(app.storage.user.get("referrer") or "/")

    with ui.column().classes("absolute-center items-center gap-3"):
        ui.label("Beherbergungssteuer Dresden").classes("text-xl font-bold")
        with ui.card().classes("w-[360px] max-w-full gap-2"):
            if not auth.is_configured(AUTH):
                ui.label("Erst-Einrichtung – Passwort festlegen").classes("font-semibold")
                p1 = ui.input("Neues Passwort", password=True,
                              password_toggle_button=True).classes("w-full")
                p2 = ui.input("Passwort wiederholen", password=True).classes("w-full")

                def setup():
                    if len(p1.value or "") < 6:
                        ui.notify("Mindestens 6 Zeichen.", type="warning"); return
                    if p1.value != p2.value:
                        ui.notify("Passwörter stimmen nicht überein.", type="negative"); return
                    AUTH["password_hash"] = auth.hash_password(p1.value)
                    data.save_config()
                    ui.notify("Passwort gesetzt.", type="positive")
                    finish()
                ui.button("Speichern & anmelden", on_click=setup) \
                    .props("unelevated").classes("w-full")
            else:
                ui.label("Anmelden").classes("font-semibold")
                pw = ui.input("Passwort", password=True,
                              password_toggle_button=True).classes("w-full")
                code = ui.input("6-stelliger Code (Authenticator)").classes("w-full") \
                    if auth.totp_enabled(AUTH) else None

                def do_login():
                    if not auth.verify_password(pw.value or "", AUTH.get("password_hash", "")):
                        ui.notify("Falsches Passwort.", type="negative"); return
                    if auth.totp_enabled(AUTH) and not auth.verify_totp(
                            AUTH.get("totp_secret", ""), code.value if code else ""):
                        ui.notify("Falscher oder fehlender Code.", type="negative"); return
                    finish()
                pw.on("keydown.enter", lambda: do_login())
                if code is not None:
                    code.on("keydown.enter", lambda: do_login())
                ui.button("Anmelden", on_click=do_login).props("unelevated").classes("w-full")


def logout():
    app.storage.user["authenticated"] = False
    ui.navigate.to("/login")


# ---------------------------------------------------------------- 2FA-Einrichtung
def open_2fa_setup():
    secret = auth.generate_totp_secret()
    account = CFG.get("email", {}).get("absender") or "Beherbergungssteuer"
    uri = auth.provisioning_uri(secret, account)
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
            AUTH["totp_secret"] = secret
            data.save_config()
            ui.notify("2FA aktiviert.", type="positive")
            dlg.close()
        with ui.row().classes("w-full justify-end"):
            ui.button("Abbrechen", on_click=dlg.close).props("flat")
            ui.button("Aktivieren", on_click=confirm).props("unelevated")
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
    betr = CFG.setdefault("betreiber", {})
    with ui.dialog() as dialog, ui.card().classes("w-[680px] max-w-full"):
        ui.label("⚙️ Einstellungen").classes("text-xl font-bold")
        ui.label("Betreiberdaten (erscheinen im PDF)").classes("text-sm text-gray-500 mt-2")
        inputs = {}
        with ui.grid(columns=2).classes("w-full gap-3"):
            for key, lbl in data.BETREIBER_FIELDS:
                inputs[key] = ui.input(lbl, value=betr.get(key, "")).classes("w-full")
        ui.label("PDF & Steuer").classes("text-sm text-gray-500 mt-3")
        with ui.grid(columns=2).classes("w-full gap-3"):
            sig_x = ui.number("Unterschrift X (pt, größer = rechts)",
                              value=float(CFG.get("unterschrift_x", 210)), step=5)
            steuer_pct = ui.number("Steuersatz (%)",
                                   value=CFG.get("steuersatz", 0.06) * 100, step=0.1, format="%.1f")
        ui.label("Revisionssicheres Archiv – externer Speicherort").classes("text-sm text-gray-500 mt-3")

        # --- Nextcloud (WebDAV): empfohlen für den Server ---
        wd = CFG.setdefault("archiv_webdav", {})
        ui.label("Nextcloud (WebDAV) – lädt direkt hoch, funktioniert auch auf dem Server") \
            .classes("text-xs text-gray-400")
        with ui.grid(columns=2).classes("w-full gap-3"):
            wd_url = ui.input("Nextcloud-URL (z. B. https://cloud.dstcloud.de)",
                              value=wd.get("url", "")).classes("w-full")
            wd_user = ui.input("Benutzer", value=wd.get("user", "")).classes("w-full")
            wd_pw = ui.input("App-Passwort (leer = unverändert)", password=True,
                             placeholder="•••• unverändert").classes("w-full")
            wd_folder = ui.input("Ziel-Ordner (z. B. Buchhaltung/Beherbergungssteuer)",
                                 value=wd.get("folder", "")).classes("w-full")

        def test_webdav():
            w = {"url": (wd_url.value or "").strip(), "user": (wd_user.value or "").strip(),
                 "password": (wd_pw.value or "").strip() or wd.get("password", ""),
                 "folder": (wd_folder.value or "").strip()}
            ok, msg = archive.webdav_test(w)
            ui.notify(("✓ " if ok else "✗ ") + msg,
                      type=("positive" if ok else "negative"), timeout=9000)
        ui.button("🔌 Nextcloud-Verbindung testen", on_click=test_webdav).props("outline")

        # --- lokaler Ordner: nur für lokalen Betrieb (mit Nextcloud-Sync) ---
        cur = CFG.get("archiv_spiegel", "")
        with ui.row().classes("w-full items-end gap-2"):
            spiegel = ui.input("oder lokaler Ordner (nur lokaler Betrieb)", value=cur) \
                .classes("flex-grow") \
                .tooltip("Nur wenn die App lokal läuft und ein Nextcloud-Sync-Ordner existiert. "
                         "Wird ignoriert, sobald oben Nextcloud/WebDAV gesetzt ist.")

            def browse():
                detected = data.detect_cloud_folders()
                start = spiegel.value or (detected[0] if detected else "")
                open_folder_picker(start, lambda p: spiegel.set_value(p))
            ui.button("📁 Durchsuchen", on_click=browse).props("outline")

        ui.label("Smoobu").classes("text-sm text-gray-500 mt-3")
        with ui.grid(columns=2).classes("w-full gap-3"):
            api = ui.input("API-Key (leer = unverändert)",
                           password=True, placeholder="•••• unverändert").classes("w-full")
            channel = ui.input("Airbnb-Kanalname (steuerfrei)",
                               value=CFG.get("airbnb_channel_name", "Airbnb")).classes("w-full")

        ec = CFG.setdefault("email", {})
        ui.label("E-Mail-Versand (Gmail)").classes("text-sm text-gray-500 mt-3")
        with ui.grid(columns=2).classes("w-full gap-3"):
            m_from = ui.input("Absender (Gmail-Adresse)", value=ec.get("absender", "")).classes("w-full")
            m_pw = ui.input("Gmail App-Passwort (leer = unverändert)", password=True,
                            placeholder="•••• unverändert").classes("w-full")
            m_to = ui.input("Empfänger (fest)", value=ec.get("empfaenger", "")).classes("w-full")
            m_cc = ui.input("Cc (optional)", value=ec.get("cc", "")).classes("w-full")
        ui.label("Vorlage – Platzhalter: {monat} {jahr} {periode} {steuer} {umsatz} "
                 "{kassenzeichen} {name}").classes("text-xs text-gray-400")
        m_subj = ui.input("Betreff-Vorlage",
                          value=ec.get("betreff_vorlage") or DEFAULT_BETREFF) \
            .classes("w-full")
        m_body = ui.textarea("Text-Vorlage", value=ec.get("text_vorlage") or DEFAULT_TEXT) \
            .classes("w-full").props("autogrow outlined")

        def test_email():
            test_cfg = {
                "smtp_host": ec.get("smtp_host", "smtp.gmail.com"),
                "smtp_port": ec.get("smtp_port", 587),
                "absender": (m_from.value or "").strip(),
                "empfaenger": (m_to.value or "").strip(),
                "cc": (m_cc.value or "").strip(),
                # neu eingetipptes Passwort bevorzugen, sonst gespeichertes
                "app_password": (m_pw.value or "").strip() or ec.get("app_password", ""),
            }
            try:
                to = mailer.send_test(test_cfg)
                ui.notify(f"Test-E-Mail an {to} gesendet ✓", type="positive", timeout=8000)
            except mailer.MailError as ex:
                ui.notify(f"Test fehlgeschlagen: {ex}", type="negative", timeout=12000)
        with ui.row().classes("items-center gap-2"):
            ui.button("📧 Test-E-Mail senden", on_click=test_email).props("outline")
            ui.label("sendet eine kurze Test-Mail an den Empfänger (ohne Anhang, "
                     "ohne Ablage)").classes("text-xs text-gray-400")

        ui.label("Sicherheit / Login").classes("text-sm text-gray-500 mt-3")
        with ui.row().classes("w-full items-end gap-3"):
            new_pw = ui.input("Passwort ändern (leer = unverändert)", password=True,
                              placeholder="•••• unverändert").classes("flex-grow")
            if auth.totp_enabled(AUTH):
                def disable_2fa():
                    AUTH["totp_secret"] = ""
                    data.save_config()
                    ui.notify("2FA (Authenticator) deaktiviert.", type="warning")
                    dialog.close()
                ui.button("2FA deaktivieren", on_click=disable_2fa).props("flat")
                ui.label("🔐 2FA aktiv").classes("text-xs text-green-700 self-center")
            else:
                ui.button("🔐 2FA aktivieren", on_click=open_2fa_setup).props("outline")

        def save():
            for key in inputs:
                betr[key] = inputs[key].value or ""
            v = sig_x.value
            CFG["unterschrift_x"] = int(v) if v == int(v) else v
            CFG["steuersatz"] = round((steuer_pct.value or 6) / 100, 4)
            CFG["archiv_spiegel"] = spiegel.value or ""
            wd["url"] = (wd_url.value or "").strip()
            wd["user"] = (wd_user.value or "").strip()
            wd["folder"] = (wd_folder.value or "").strip()
            if (wd_pw.value or "").strip():
                wd["password"] = wd_pw.value.strip()
            CFG["archiv_webdav"] = wd
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
            if (new_pw.value or "").strip():
                if len((new_pw.value or "").strip()) < 6:
                    ui.notify("Passwort zu kurz (min. 6 Zeichen) – nicht geändert.", type="warning")
                else:
                    AUTH["password_hash"] = auth.hash_password(new_pw.value.strip())
                    ui.notify("Passwort geändert.", type="positive")
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
def _kpi(container, label, value, accent=False):
    with container:
        with ui.card().classes("p-4 " + ("bg-green-50" if accent else "bg-blue-50")):
            ui.label(label).classes("text-xs text-gray-500")
            cls = "text-2xl font-bold " + ("text-green-700" if accent else "")
            ui.label(value).classes(cls)


def render_result(container, result):
    container.clear()
    r = result
    with container:
        with ui.row().classes("w-full gap-4"):
            grid = ui.grid(columns=4).classes("w-full gap-4")
        _kpi(grid, "ÜN insgesamt", str(r["uebernachtungen_insgesamt"]))
        _kpi(grid, "verbleibende ÜN", str(r["uebernachtungen_verbleibend"]))
        _kpi(grid, "steuerpfl. Umsatz", data.euro(r["umsatz_steuerpflichtig"]) + " €")
        _kpi(grid, "Beherbergungssteuer", data.euro(r["beherbergungssteuer"]) + " €", accent=True)

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
    ui.colors(primary="#1f6feb")
    today = date.today()
    apts = _load_apartments()

    with ui.header().classes("items-center justify-between"):
        ui.label("Beherbergungssteuer Dresden").classes("text-lg font-bold")
        with ui.row().classes("gap-1"):
            ui.button("📚 Archiv", on_click=open_archive).props("flat color=white")
            ui.button("⚙️ Einstellungen", on_click=open_settings).props("flat color=white")
            ui.button(icon="logout", on_click=logout).props("flat round color=white") \
                .tooltip("Abmelden")

    with ui.column().classes("w-full max-w-5xl mx-auto p-4 gap-4"):
        with ui.card().classes("w-full"):
            with ui.row().classes("items-end gap-4 flex-wrap"):
                year = ui.select(list(range(2023, today.year + 2)), label="Jahr",
                                 value=today.year)
                month = ui.select({m: data.MONATE[m] for m in range(1, 13)}, label="Monat",
                                  value=today.month)
                apt = ui.select(apts or {}, label="Apartments", multiple=True,
                                value=list(apts.keys())).classes("min-w-[220px]").props("use-chips")
                airbnb = ui.number("Airbnb-ÜN (Override)", value=None, format="%d") \
                    .props('placeholder="leer = berechnet" clearable')
                befreit = ui.number("Steuerbefr. Umsatz €", value=0, step=0.01)
                ui.button("Berechnen", on_click=lambda: do_compute()).props("unelevated")
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


def run():
    ui.run(host="127.0.0.1", port=int(CFG.get("port", 3001)),
           title="Beherbergungssteuer Dresden", reload=False, show=False,
           storage_secret=STORAGE_SECRET)


if __name__ in {"__main__", "__mp_main__"}:
    run()
