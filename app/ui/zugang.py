"""Zugang: Anmelden, Einladung, Passwort vergessen, Mein Konto, Benutzer.

Enthaelt die Seiten `/login` und `/invite` sowie die Dialoge zur
Benutzerverwaltung. Die Regeln dahinter (Einmal-Links, 2FA, Rollen) stehen im
README unter "Login, Benutzer & Rollen".
"""
import time as _time

from nicegui import app, ui
from app import auth, data, i18n, mailer
from app.ui import benachrichtigungen, pwa
from app import planung as _planung
from app.ui import planung as ui_planung
from app.ui.basis import (CFG, ROLES, USERS, _app_url, _cur_user, _is_admin, _lang, _lang_select, _probe_hinweis, _role_label, logo, t)

# ---------------------------------------------------------------- Login
def _finish_login(username, role):
    """Session anlegen und zur Startseite (bzw. zur ursprünglich gewünschten Seite)."""
    app.storage.user["authenticated"] = True
    app.storage.user["user"] = username
    app.storage.user["role"] = role
    # Beim Start immer auf der Startseite landen ("Meine Reinigungen"), nicht
    # dort, wo die letzte Sitzung aufgehört hat. Der gemerkte Bereich gilt nur
    # innerhalb einer Sitzung, z. B. beim Neuladen nach einer Aktion.
    app.storage.user.pop("area", None)
    # Profilsprache schlägt die am Login-Schirm gewählte Sprache
    profil = (USERS.get(username, {}) or {}).get("lang")
    if profil:
        app.storage.user["lang"] = profil
    ui.navigate.to(app.storage.user.get("referrer") or "/")


def login_page():
    pwa.kopf()
    ui.colors(primary="#5E2A84", secondary="#8A5CC2", accent="#C8A96E",
              positive="#16a34a", negative="#dc2626")
    ui.query("body").classes("bg-[#F5F2EB]")
    if app.storage.user.get("authenticated"):
        ui.navigate.to("/")
        return

    finish2 = _finish_login

    with ui.column().classes("absolute-center items-center gap-4"):
        logo(60)
        _probe_hinweis()
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


def invite_page(token: str = ""):
    pwa.kopf()
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
        ui.separator().classes("my-1")
        benachrichtigungen.block()
        ui.separator().classes("my-1")
        ui_planung.abwesenheiten_block()
        ui.separator().classes("my-1")
        # Die Anleitung gehört hierher: „Wie kriege ich das aufs Handy?“ sucht
        # man beim eigenen Konto, nicht in den Einstellungen des Betreibers.
        pwa.einrichten_hinweis()

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
        # Steuert, wem die Planung Reinigungen vorschlägt (app/planung.py).
        mr = ui.switch("Übernimmt Reinigungen",
                       value=_planung.macht_reinigungen(u)).props("dense")

        def _toggle_mr(e):
            USERS[uname]["macht_reinigungen"] = bool(e.value)
            data.save_config()
        mr.on_value_change(_toggle_mr)

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


def seiten_registrieren():
    """Die Seiten dieses Bereichs an die Anwendung hängen.

    Bewusst ein Aufruf und kein Dekorator: `app/web.py` wird im Testlauf **je
    Test erneut ausgeführt**, während die Bereichsmodule geladen bleiben. Ein
    Dekorator hier liefe nur beim allerersten Import – ab dem zweiten Test wäre
    `/login` nicht mehr registriert (404). Im Betrieb läuft das genau einmal.
    """
    ui.page("/login")(login_page)
    ui.page("/invite")(invite_page)
