"""Einstellungen (Zahnrad): Betreiberdaten, Steuer, E-Mail, Archiv, Standorte.

Ein grosser Dialog mit Reitern. Gespeichert wird in `config.json`.
"""

import os
from datetime import date
from nicegui import ui
from app import buchhaltung, data, housekeeping, mailer, rechte, stammdaten
from app.ui.basis import (CFG, DEFAULT_APP_URL, _apts, _checklisten_an,
                          _cur_user, _darf, _read_upload, spaeter, t)
from app.ui import ton
from app.ui.buchungen import (_user_email)
from app.ui.standort import (_geo_enabled, geocode)
from app.ui.steuer import (DEFAULT_BETREFF, DEFAULT_TEXT)

# ---------------------------------------------------------------- Ordner-Browser
def open_folder_picker(start, on_pick):
    state = {"dir": start if (start and os.path.isdir(start)) else os.path.expanduser("~")}
    with ui.dialog() as dlg, ui.card().classes("w-[680px] max-w-full"):
        ui.label("📁 Ordner wählen").classes("text-lg font-bold")
        path_lbl = ui.label().classes("text-xs font-mono text-slate-600 break-all")
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


# ---------------------------------------------------------------- Logo
def _logo_feld(betr):
    """Logo für die Rechnung – hochladen, ansehen, entfernen.

    Das Bild wird sofort gespeichert, nicht erst beim Schließen des Dialogs:
    ein Upload, den man noch bestätigen muss, geht regelmäßig verloren. Der
    Name steht in `betreiber["logo"]`, die Datei im Medienordner – damit zeigt
    dieselbe Angabe das Logo hier unter `/media/…` und im PDF.
    """
    ui.separator().classes("my-2")
    ui.label("Logo (erscheint oben links auf der Rechnung)").classes("text-sm text-slate-500")
    with ui.row().classes("w-full items-center gap-3") as reihe:
        vorschau = ui.column().classes("items-start")

        def zeichnen():
            vorschau.clear()
            with vorschau:
                rel = (betr.get("logo") or "").strip()
                if rel:
                    ui.image(f"/media/{rel}").classes("h-16").props("fit=contain")
                else:
                    ui.label("Noch kein Logo hinterlegt.").classes("text-xs text-slate-400")

        async def hochladen(e):
            try:
                rohdaten, name = await _read_upload(e)
                endung = (name.rsplit(".", 1)[-1] if "." in name else "png").lower()[:4]
                if endung not in ("png", "jpg", "jpeg", "gif"):
                    ui.notify("Bitte PNG, JPG oder GIF.", type="warning")
                    return
                betr["logo"] = housekeeping.save_photo("logo", rohdaten, ext=endung)
                data.save_config()
            except Exception as ex:
                ui.notify(f"Logo konnte nicht gespeichert werden: {ex}", type="negative")
                return
            ui.notify("Logo gespeichert ✓", type="positive")
            zeichnen()

        def entfernen():
            betr.pop("logo", None)
            data.save_config()
            ui.notify("Logo entfernt.")
            zeichnen()

        zeichnen()
        ui.upload(auto_upload=True, on_upload=hochladen, label="Logo wählen") \
            .props('accept="image/*"').classes("hk-upload w-[190px]")
        ui.button("Entfernen", icon="delete", on_click=entfernen).props("flat no-caps")
    return reihe


# ---------------------------------------------------------------- Einstellungen
def open_settings():
    if not _darf(rechte.EINSTELLUNGEN):
        ui.notify("Dafür fehlt dir die Berechtigung.", type="negative"); return
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
            t_rein = ui.tab("Reinigung", icon="cleaning_services")
            t_smoobu = ui.tab("Smoobu", icon="sync")
            t_mail = ui.tab("E-Mail", icon="mail")
            t_stb = ui.tab("Steuerberater", icon="account_balance")
            t_stamm = ui.tab("Produkte & Kreditoren", icon="inventory")

        with ui.tab_panels(tabs, value=t_betr).classes("w-full"):
            with ui.tab_panel(t_betr):
                ui.label("Betreiberdaten (erscheinen im PDF)").classes("text-sm text-slate-500")
                inputs = {}
                with ui.grid(columns=2).classes("w-full gap-3"):
                    for key, lbl in data.BETREIBER_FIELDS:
                        inputs[key] = ui.input(lbl, value=betr.get(key, "")).props("outlined dense").classes("w-full")
                _logo_feld(betr)

            with ui.tab_panel(t_pdf):
                with ui.grid(columns=2).classes("w-full gap-3"):
                    sig_x = ui.number("Unterschrift X (pt, größer = rechts)",
                                      value=float(CFG.get("unterschrift_x", 210)), step=5).props("outlined dense")
                    steuer_pct = ui.number("Steuersatz (%)",
                                           value=CFG.get("steuersatz", 0.06) * 100, step=0.1,
                                           format="%.1f").props("outlined dense")

            with ui.tab_panel(t_arch):
                ui.label("Jede Festschreibung wird revisionssicher abgelegt und zusätzlich "
                         "in diesen Ordner auf dem Computer kopiert.").classes("text-sm text-slate-500")
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
                         "Ordner gespiegelt.").classes("text-sm text-slate-500")
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
                    .classes("text-sm text-slate-500 mt-2")
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

            with ui.tab_panel(t_rein):
                cl_on = ui.switch("Checklisten & Fotonachweis verwenden",
                                  value=_checklisten_an()).props("dense")
                ui.label("Aus: Die Putzkraft startet die Arbeitszeit, meldet bei Bedarf "
                         "Schäden oder Verbrauch und beendet die Zeit – fertig. Das ist "
                         "der einfache Einstieg.").classes("text-xs text-slate-500")
                ui.label("An: Zusätzlich der Checklisten-Durchgang je Wohnung mit Soll-/"
                         "Ist-Fotos, der Fortschrittsbalken auf der Reinigungskarte, die "
                         "Aktion „Checkliste & Fotos“ sowie in der Übersicht der Tab "
                         "„Durchgänge“ und die Checklisten-Konfiguration.") \
                    .classes("text-xs text-slate-500")
                ui.label("Umschalten löscht nichts: bereits erfasste Durchgänge, Fotos "
                         "und angelegte Checklisten bleiben erhalten und sind nach dem "
                         "Wiedereinschalten wieder da.").classes("text-xs text-slate-400 mt-1")
                ui.label("Solange die Checklisten aus sind, gilt eine Reinigung als "
                         "„Fertig“, sobald die Arbeitszeit erfasst und beendet ist.") \
                    .classes("text-xs text-slate-400")
            with ui.tab_panel(t_orte):
                geo_on = ui.switch("Standort bei der Zeiterfassung erfassen",
                                   value=_geo_enabled()).props("dense")
                ui.label("Ist der Schalter aus, wird beim Ein- und Auschecken weder GPS "
                         "noch IP abgefragt oder gespeichert – die Mitarbeiter werden "
                         "nicht nach Ortungsfreigabe gefragt. Bereits erfasste Standorte "
                         "alter Einträge bleiben in worklog.json erhalten.") \
                    .classes("text-xs text-slate-500")
                ui.separator().classes("my-2")
                ui.label("Objekte für die GPS-Standortprüfung der Zeiterfassung. Adresse "
                         "eintragen und Lupe antippen (Koordinaten), Radius in Metern "
                         "(z. B. 150). Check-in außerhalb wird markiert.") \
                    .classes("text-sm text-slate-500")
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
                vorschau = ui.number("Buchungen im Voraus anzeigen (Tage)",
                                     value=int(CFG.get("buchungen_vorschau_tage", 60)),
                                     min=7, max=365, step=7).props("outlined dense") \
                    .classes("w-full").mark("vorschau-tage")
                ui.label("Wie weit die Reinigungsliste und der Kalender nach vorn "
                         "blicken. Zwei Monate sind die Vorgabe – mehr kostet bei "
                         "diesem Buchungsaufkommen praktisch nichts.") \
                    .classes(f"text-xs {ton.LEISE}")
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
                         "{kassenzeichen} {name}").classes("text-xs text-slate-400 mt-2")
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
                        .classes("text-xs text-slate-400")

                ui.separator().classes("my-2")
                nb = CFG.setdefault("notify_email", {})
                ui.label("Benachrichtigungen an Mitarbeiter (Reinigungs-Tausch, Schäden). "
                         "Eigenes Gmail-Konto als Absender, z. B. d.steinhauss@gmail.com "
                         "(Gmail: 2FA + App-Passwort nötig). Leer = Absender oben nutzen.") \
                    .classes("text-sm text-slate-500")
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
                    ui.label("Test-Mail an deine eigene E-Mail-Adresse").classes("text-xs text-slate-400")

                ui.separator().classes("my-2")
                ui.label("Adresse der App – wird für Links in E-Mails benutzt "
                         "(Einladungen, Reinigungs-Hinweise). Muss von außen erreichbar sein.") \
                    .classes("text-sm text-slate-500")
                app_url_in = ui.input("Adresse der App", value=CFG.get("app_url", "") or DEFAULT_APP_URL,
                                      placeholder=DEFAULT_APP_URL) \
                    .props("outlined dense").classes("w-full max-w-[420px]")

            with ui.tab_panel(t_stamm).mark("panel-stammdaten"):
                _stammdaten_panel()

            with ui.tab_panel(t_stb):
                ui.label("Empfänger für den monatlichen Arbeitszeiten-Versand "
                         "(Zeiterfassung → Auswertung → An Steuerberater senden). "
                         "Unabhängig von der E-Mail für die Beherbergungssteuer.") \
                    .classes("text-sm text-slate-500")
                stb = ui.input("E-Mail Steuerberater", value=CFG.get("steuerberater_email", "")) \
                    .props("outlined dense").classes("w-full max-w-[420px]")
                ui.label("E-Mail-Vorlage (Platzhalter {monat}, {jahr}). Die Stunden je "
                         "Mitarbeiter und der Zeitraum werden automatisch eingefügt; eine "
                         "Notiz je Mitarbeiter kommt aus der Benutzerverwaltung.") \
                    .classes("text-xs text-slate-500 mt-2")
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
                    .classes("text-xs text-slate-500")
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
            CFG["checklisten_aktiv"] = bool(cl_on.value)
            for key in inputs:
                betr[key] = inputs[key].value or ""
            v = sig_x.value
            CFG["unterschrift_x"] = int(v) if v == int(v) else v
            CFG["buchungen_vorschau_tage"] = int(vorschau.value or 60)
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


# ------------------------------------------------- Produkte & Kreditoren (AP13)
def _stammdaten_panel():
    """Die Grundlage der Rechnung – gepflegt, nicht geraten.

    Bewusst zwei Listen und kein Assistent: Stammdaten ändert man selten und
    dann genau. Was es hier zu verstehen gibt, steht als Satz daneben, nicht in
    einer Hilfe, die niemand aufschlägt.
    """
    box = ui.column().classes("w-full gap-4")

    def render():
        box.clear()
        with box:
            _produkte_liste(render)
            ui.separator()
            _kreditoren_liste(render)
            ui.separator()
            _kategorien_liste(render)
    render()


def _kategorien_liste(neu_zeichnen):
    """Eigene Kategorien anlegen, umbenennen, entfernen.

    Die Vorgaben sind wörtlich die SUMIF-Kriterien des Workbooks und deshalb
    hier nicht änderbar – sie stehen nur als Zahl daneben, damit klar ist, dass
    es sie gibt. Alles, was der Betrieb darüber hinaus auswerten will, entsteht
    hier: „wie viel ging für Putzmittel drauf" beantwortet man nicht mit einer
    Vorgabeliste.
    """
    eigene = buchhaltung.eigene_kategorien(CFG)
    with ui.row().classes("w-full items-center gap-2"):
        ui.label("Eigene Kategorien").classes("font-semibold")
        ui.space()
        feld = ui.input(placeholder="z. B. Putzmittel") \
            .props("outlined dense").classes("w-56").mark("kategorie-neu")

        def anlegen():
            ok, meldung = buchhaltung.kategorie_anlegen(CFG, feld.value)
            ui.notify(meldung, type="positive" if ok else "warning")
            if ok:
                data.save_config()
                neu_zeichnen()

        feld.on("keydown.enter", anlegen)
        ui.button(icon="add", on_click=anlegen).props("round dense unelevated") \
            .tooltip("Kategorie hinzufügen").mark("kategorie-plus")

    ui.label(f"{len(buchhaltung.VORGABE_KATEGORIEN)} Vorgaben sind fest "
             "hinterlegt (sie müssen wörtlich zum Buchhaltungs-Workbook passen). "
             "Hier kommt dazu, was du selbst auswerten willst.") \
        .classes(f"text-xs {ton.LEISE}")

    if not eigene:
        ui.label("Noch keine eigene Kategorie.").classes("text-xs text-slate-400")
        return
    for name in eigene:
        with ui.row().classes("w-full items-center gap-2 no-wrap").mark(f"kat-{name}"):
            feld = ui.input(value=name).props("dense borderless").classes("flex-grow")

            def umbenennen(_e=None, alt=name, f=None):
                ok, meldung = buchhaltung.kategorie_umbenennen(CFG, alt, f.value)
                ui.notify(meldung, type="positive" if ok else "warning")
                if ok:
                    data.save_config()
                neu_zeichnen()

            feld.on("blur", lambda e, alt=name, f=feld: umbenennen(e, alt, f))

            def loeschen(n=name):
                ok, meldung = buchhaltung.kategorie_loeschen(CFG, n)
                ui.notify(meldung, type="positive" if ok else "warning")
                if ok:
                    data.save_config()
                    neu_zeichnen()

            ui.button(icon="delete", on_click=loeschen) \
                .props("flat dense round color=negative").tooltip("Entfernen")


def _produkte_liste(neu_zeichnen):
    produkte = stammdaten.produkte()
    with ui.row().classes("w-full items-center gap-2"):
        ui.label("Produkte").classes("font-semibold")
        ui.space()
        if not produkte:
            ui.button("Vorgaben anlegen", icon="auto_awesome",
                      on_click=lambda: (stammdaten.erstbefuellung(),
                                        ui.notify("Produkte und bekannte Lieferanten angelegt.",
                                                  type="positive"),
                                        spaeter(neu_zeichnen))) \
                .props("unelevated dense no-caps").mark("stammdaten-vorgaben")
    if not produkte:
        ui.label("Noch nichts angelegt. Die Vorgaben bringen Übernachtung, Endreinigung "
                 "und Beherbergungssteuer mit – dazu die Lieferanten aus dem Kontenjournal.") \
            .classes(f"text-sm {ton.LEISE}")
        return

    apts = _apts()
    for p in produkte:
        with ui.card().classes(ton.KARTE_ENG).mark(f"produkt-{p['id']}"):
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.label(p.get("name", "")).classes("font-medium")
                ui.chip(f"{p.get('steuersatz', 0) * 100:.0f} % USt") \
                    .props("color=grey-4 text-color=black dense square").classes("text-xs")
                ui.space()
                ui.label(_ART_TEXT.get(p.get("art"), p.get("art", ""))) \
                    .classes(f"text-xs {ton.STILL}")
            if p.get("art") != stammdaten.FEST:
                continue
            ui.label("Preis je Wohnung – gefragt wird mit dem Tag, an dem der Gast gebucht "
                     "hat, nicht mit der Anreise.").classes(f"text-xs {ton.LEISE}")
            for wid, wname in (apts or {}).items():
                _preiszeile(p, wid, wname, neu_zeichnen)


_ART_TEXT = {
    stammdaten.BEHERBERGUNG: "Restbetrag der Buchung",
    stammdaten.FEST: "fester Preis je Wohnung",
    stammdaten.DURCHLAUFEND: "durchlaufend, keine USt",
}


def _preiszeile(produkt, wohnung_id, wohnung_name, neu_zeichnen):
    verlauf = stammdaten.preisverlauf(produkt["id"], wohnung_id)
    with ui.row().classes("w-full items-center gap-2 no-wrap flex-wrap"):
        ui.icon("home").classes(f"{ton.STILL} text-sm shrink-0")
        ui.label(wohnung_name).classes("text-sm font-medium min-w-[120px]")
        for eintrag in verlauf:
            ui.chip(f"{eintrag['betrag']:.2f} € ab {eintrag['ab'][8:10]}.{eintrag['ab'][5:7]}."
                    f"{eintrag['ab'][:4]}",
                    removable=True,
                    on_value_change=lambda e, w=wohnung_id, ab=eintrag["ab"]: (
                        None if e.value else
                        (stammdaten.preis_entfernen(produkt["id"], w, ab),
                         spaeter(neu_zeichnen)))) \
                .props("color=deep-purple-1 text-color=deep-purple-10 dense square") \
                .classes("text-xs")
        if not verlauf:
            ui.label("noch kein Preis").classes(f"text-xs {ton.HINWEIS}")
        ui.space()
        # Bewusst ein Textfeld statt ui.number: das Zahlenfeld formatiert beim
        # Tippen mit und schluckt dabei die Eingabe. Gelesen wird mit dem
        # Geld-Parser aus der Buchhaltung, der ohnehin „65,50" und „1.234,56"
        # versteht – eine deutsche Eingabe soll hier nicht scheitern.
        betrag = ui.input(label="Betrag €", placeholder="65,00") \
            .props("outlined dense inputmode=decimal").classes("w-28") \
            .mark(f"preis-betrag-{wohnung_id}")
        ab = ui.input(label="ab Buchung", value=date.today().isoformat()) \
            .props("type=date outlined dense").classes("w-40") \
            .mark(f"preis-ab-{wohnung_id}")

        def setzen(w=wohnung_id, b=betrag, a=ab, still=False):
            """Preis uebernehmen. `still` unterdrueckt die Meckerei – das
            braucht der Blur-Weg, der auch bei leerem Feld ausloest."""
            wert = buchhaltung.betrag_zahl(b.value)
            if not wert:
                if not still:
                    ui.notify("Bitte einen Betrag eintragen, z. B. 65,00.",
                              type="warning")
                return
            if not (a.value or "").strip():
                if not still:
                    ui.notify("Bitte ein Datum wählen, ab dem der Preis gilt.",
                              type="warning")
                return
            stammdaten.preis_setzen(produkt["id"], w, a.value, wert)
            b.value = ""
            ui.notify(f"{wohnung_name}: {wert:.2f} € ab {a.value}", type="positive")
            spaeter(neu_zeichnen)

        # Drei Wege zum selben Ziel, weil dieser Bildschirm in einem Dialog mit
        # eigenem „Speichern" steht: wer den Preis eintippt und dann Speichern
        # drueckt, erwartet zu Recht, dass er gespeichert ist. Der Preis haengt
        # aber an dieser Zeile, nicht am Dialog. Deshalb uebernimmt schon das
        # Verlassen des Feldes – Enter und der Knopf tun dasselbe.
        betrag.on("blur", lambda: setzen(still=True))
        betrag.on("keydown.enter", lambda: setzen())
        ui.button("Übernehmen", icon="add", on_click=lambda: setzen()) \
            .props("flat dense no-caps color=primary") \
            .tooltip("Gilt für Buchungen ab diesem Datum") \
            .mark(f"preis-setzen-{wohnung_id}")


def _kreditoren_liste(neu_zeichnen):
    with ui.row().classes("w-full items-center gap-2"):
        ui.label("Kreditoren").classes("font-semibold")
        ui.space()
    ui.label("Woran ein Lieferant im Beleg erkannt wird, und was er mitbringt: Kategorie "
             "fürs Kontenjournal, Wohnung als Kostenstelle. Ein Dauerbeleg sagt, dass die "
             "monatliche Abbuchung keinen eigenen Beleg braucht.") \
        .classes(f"text-xs {ton.LEISE}")

    apts = _apts()
    for k in stammdaten.kreditoren():
        with ui.row().classes("w-full items-center gap-2 no-wrap flex-wrap py-1 "
                              "border-b border-slate-50").mark(f"kreditor-{k['id']}"):
            ui.label(k.get("name", "")).classes("text-sm font-medium min-w-[150px]")
            ui.label(k.get("kategorie") or "— keine Kategorie —") \
                .classes(f"text-xs {ton.LEISE} flex-grow min-w-0 truncate")
            if k.get("wohnung"):
                ui.chip((apts or {}).get(k["wohnung"], "Wohnung")) \
                    .props("color=grey-4 text-color=black dense square").classes("text-xs")
            if k.get("dauerbeleg"):
                ui.chip("Dauerbeleg", icon="event_repeat") \
                    .props("color=green-7 text-color=white dense square").classes("text-xs") \
                    .tooltip(k["dauerbeleg"])
            ui.button(icon="edit", on_click=lambda kk=k: _kreditor_dialog(kk, neu_zeichnen)) \
                .props("flat dense round").tooltip("Bearbeiten")

    ui.button("Kreditor hinzufügen", icon="add",
              on_click=lambda: _kreditor_dialog(None, neu_zeichnen)) \
        .props("outline no-caps dense").classes("mt-1").mark("kreditor-neu")


def _kreditor_dialog(k, neu_zeichnen):
    from app import buchhaltung
    neu = k is None
    apts = _apts()
    with ui.dialog() as dlg, ui.card().classes("w-[520px] max-w-full gap-2"):
        ui.label("Kreditor anlegen" if neu else "Kreditor bearbeiten").classes("font-bold")
        name = ui.input("Name", value=(k or {}).get("name", "")) \
            .props("outlined dense").classes("w-full").mark("kreditor-name")
        muster = ui.input("Erkennungsmuster (mit Komma getrennt)",
                          value=", ".join((k or {}).get("muster", []))) \
            .props("outlined dense").classes("w-full")
        ui.label("Steht eines davon im Händlernamen eines Belegs, gehört er diesem "
                 "Kreditor. Leer lassen heißt: der Name selbst zählt.") \
            .classes(f"text-xs {ton.LEISE}")
        kategorie = ui.select({"": "— keine —",
                               **{x: x for x in buchhaltung.kategorien(CFG)}},
                              value=(k or {}).get("kategorie", ""), label="Kategorie") \
            .props("outlined dense options-dense").classes("w-full")
        wohnung = ui.select({None: "— keine —", **(apts or {})},
                            value=(k or {}).get("wohnung"), label="Kostenstelle (Wohnung)") \
            .props("outlined dense").classes("w-full")
        dauer = ui.input("Dauerbeleg – z. B. Mietvertrag vom 1.3.2024",
                         value=(k or {}).get("dauerbeleg", "")) \
            .props("outlined dense").classes("w-full")
        # Die Klasse entscheidet, ob eine Zahlung ins Ergebnis eingeht. Sie
        # gehört hierher und nicht ins Programm: wer die eigene Privatentnahme
        # bekommt oder welche Stadtkasse die Steuer einzieht, ist je Betrieb
        # verschieden.
        klasse = ui.select({"": "— aus der Kategorie ableiten —",
                            **{x: x for x in buchhaltung.KLASSEN}},
                           value=(k or {}).get("klasse", ""),
                           label="Wie geht die Zahlung ins Ergebnis?") \
            .props("outlined dense options-dense").classes("w-full") \
            .tooltip("„Privat/prüfen“ für Entnahmen, „Durchlaufend“ für "
                     "abgeführte Steuern – beides ist keine Betriebsausgabe.")

        def sichern():
            if not (name.value or "").strip():
                ui.notify("Name fehlt.", type="warning"); return
            teile = [m.strip() for m in (muster.value or "").split(",") if m.strip()]
            if neu:
                stammdaten.kreditor_anlegen(name.value.strip(), kategorie.value or "",
                                            teile, wohnung.value, dauer.value or "",
                                            klasse=klasse.value or "")
            else:
                stammdaten.kreditor_aendern(k["id"], name=name.value.strip(),
                                            kategorie=kategorie.value or "", muster=teile,
                                            wohnung=wohnung.value,
                                            dauerbeleg=dauer.value or "",
                                            klasse=klasse.value or "")
            dlg.close(); ui.notify("Gespeichert ✓", type="positive"); neu_zeichnen()

        with ui.row().classes("w-full justify-between items-center"):
            if not neu:
                ui.button(icon="delete",
                          on_click=lambda: (stammdaten.kreditor_loeschen(k["id"]), dlg.close(),
                                            ui.notify("Kreditor entfernt.", type="warning"),
                                            neu_zeichnen())) \
                    .props("flat dense round color=negative").tooltip("Löschen")
            else:
                ui.element("div")
            with ui.row().classes("gap-2"):
                ui.button("Abbrechen", on_click=dlg.close).props("flat")
                ui.button("Speichern", on_click=sichern).props("unelevated") \
                    .mark("kreditor-speichern")
    dlg.open()
