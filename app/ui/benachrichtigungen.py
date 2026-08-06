#!/usr/bin/env python3
"""Benachrichtigungen einschalten, prüfen und feinjustieren (Mein Konto).

Der Ablauf ist von den Browsern vorgegeben und lässt sich nicht abkürzen:

1. Der Nutzer tippt auf einen Knopf – die Erlaubnis darf **nur** aus einem
   echten Fingertipp heraus abgefragt werden, sonst lehnen Safari und Chrome
   sofort ab.
2. Der Browser fragt nach der Erlaubnis.
3. Der Browser meldet sich beim Push-Dienst an (Apple bzw. Google) und liefert
   eine Anmeldung zurück: Endpunkt plus zwei Schlüssel.
4. Diese Anmeldung wandert zum Server und wird dort dem angemeldeten Benutzer
   zugeordnet.

Schritt 4 läuft bewusst **über die bestehende Sitzung** (`ui.run_javascript`
gibt das Ergebnis nach Python zurück) und nicht über eine eigene API-Route: eine
solche Route müsste ohne Login erreichbar sein – und dann könnte jeder fremde
Geräte auf fremde Konten anmelden.

Auf iOS kommt vorher noch eine Hürde: **ohne App auf dem Home-Bildschirm gibt es
keine Benachrichtigungen.** Deshalb steht dort statt des Knopfes ein Hinweis auf
die Einricht-Anleitung.
"""
import json

from nicegui import ui

from app import data, push
from app.ui import pwa
from app.ui.basis import USERS, _cur_user, t

# Beschriftung der Meldearten. Reihenfolge = Anzeige-Reihenfolge.
ARTEN_TEXT = [
    ("zuweisung", "Neue Reinigung für mich", "Wenn mir jemand eine Reinigung zuweist"),
    ("erinnerung", "Erinnerung am Vorabend", "Abends: was morgen ansteht"),
    ("nachtragen", "Arbeitszeit fehlt", "Wenn zu einer Reinigung keine Zeit erfasst wurde"),
    ("schaden", "Schaden gemeldet", "Nur für Verwaltung: wenn jemand einen Schaden meldet"),
]

# Ergebnis-Kennungen aus dem Browser (siehe ANMELDEN_JS).
_ABGELEHNT = "abgelehnt"
_NICHT_UNTERSTUETZT = "nicht-unterstuetzt"

ANMELDEN_JS = """
(async () => {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    return {fehler: '%(nicht)s'};
  }
  try {
    const erlaubnis = await Notification.requestPermission();
    if (erlaubnis !== 'granted') return {fehler: '%(abgelehnt)s'};
    const reg = await navigator.serviceWorker.ready;
    let abo = await reg.pushManager.getSubscription();
    if (!abo) {
      abo = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: Uint8Array.from(
          atob('%(schluessel)s'.replace(/-/g, '+').replace(/_/g, '/')),
          (c) => c.charCodeAt(0)),
      });
    }
    return {abo: abo.toJSON(), geraet: navigator.userAgent};
  } catch (e) {
    return {fehler: String(e)};
  }
})()
"""


def _geraetename(ua):
    """Aus der Browser-Kennung etwas machen, das man wiedererkennt."""
    ua = ua or ""
    if "iPhone" in ua:
        return "iPhone"
    if "iPad" in ua:
        return "iPad"
    if "Android" in ua:
        return "Android-Handy"
    if "Macintosh" in ua:
        return "Mac"
    if "Windows" in ua:
        return "Windows-Rechner"
    return "Gerät"


def block():
    """Der Abschnitt „Benachrichtigungen“ in „Mein Konto“."""
    benutzer = _cur_user()
    rumpf = ui.column().classes("w-full gap-2")

    def neu_zeichnen():
        rumpf.clear()
        with rumpf:
            _inhalt(benutzer, neu_zeichnen)
    neu_zeichnen()
    return rumpf


def _inhalt(benutzer, neu_zeichnen):
    geraete = push.abos(benutzer)
    with ui.row().classes("w-full items-center gap-2 no-wrap"):
        ui.icon("notifications_active" if geraete else "notifications_off") \
            .classes(("text-green-600" if geraete else "text-gray-400") + " text-xl")
        ui.label(t("Benachrichtigungen")).classes("font-medium text-slate-700")
        ui.space()
        if geraete:
            ui.label(t("{n} Gerät", n=len(geraete)) if len(geraete) == 1
                     else t("{n} Geräte", n=len(geraete))) \
                .classes("text-xs text-gray-500")

    # Auf iOS ohne Home-Bildschirm-App ist der Knopf sinnlos: Safari meldet die
    # Erlaubnis zwar, zugestellt wird trotzdem nichts.
    hinweis = ui.column().classes("w-full gap-1")
    hinweis.set_visibility(False)
    with hinweis:
        with ui.row().classes("w-full items-start gap-2 no-wrap bg-amber-50 border "
                              "border-amber-200 rounded-lg px-3 py-2"):
            ui.icon("info").classes("text-amber-700 text-base shrink-0 mt-0.5")
            ui.label(t("Auf dem iPhone kommen Benachrichtigungen erst an, wenn die "
                       "App auf dem Home-Bildschirm liegt.")).classes("text-sm")
        pwa.einrichten_hinweis()
    kennung = f"push-hinweis-{hinweis.id}"
    hinweis.props(f'id={kennung}')
    ui.add_body_html(f"""
    <script>
      (() => {{
        const alsApp = {pwa.als_app_gestartet()};
        const apple = /iPhone|iPad|iPod/.test(navigator.userAgent);
        if (apple && !alsApp) {{
          const zeigen = () => {{
            const el = document.getElementById('{kennung}');
            if (el) {{ el.style.display = 'flex'; }} else {{ setTimeout(zeigen, 200); }}
          }};
          zeigen();
        }}
      }})();
    </script>
    """)

    async def einschalten():
        js = ANMELDEN_JS % {"schluessel": push.oeffentlicher_schluessel(),
                            "abgelehnt": _ABGELEHNT, "nicht": _NICHT_UNTERSTUETZT}
        try:
            ergebnis = await ui.run_javascript(js, timeout=90.0)
        except Exception as ex:
            ui.notify(t("Einschalten fehlgeschlagen: {fehler}", fehler=ex),
                      type="negative", timeout=9000)
            return
        ergebnis = ergebnis or {}
        fehler = ergebnis.get("fehler")
        if fehler == _ABGELEHNT:
            ui.notify(t("Ohne Erlaubnis geht es nicht. Du kannst sie in den "
                        "Einstellungen deines Handys wieder freigeben."),
                      type="warning", timeout=9000)
            return
        if fehler == _NICHT_UNTERSTUETZT:
            ui.notify(t("Dieser Browser kann keine Benachrichtigungen."),
                      type="warning", timeout=9000)
            return
        if fehler or not ergebnis.get("abo"):
            ui.notify(t("Einschalten fehlgeschlagen: {fehler}",
                        fehler=fehler or "unbekannt"), type="negative", timeout=9000)
            return
        abo = ergebnis["abo"]
        if isinstance(abo, str):
            abo = json.loads(abo)
        push.anmelden(_cur_user(), abo, _geraetename(ergebnis.get("geraet")))
        ui.notify(t("Benachrichtigungen sind an ✓"), type="positive")
        neu_zeichnen()

    async def probe():
        # Der Versand geht über das Netz zu Apple bzw. Google – das gehört nicht
        # in den Ereignis-Thread, sonst steht die Oberfläche solange.
        from nicegui import run
        n = await run.io_bound(
            push.senden, benutzer, t("Test"),
            t("Wenn du das siehst, kommen Benachrichtigungen an."), "/", "test")
        ui.notify(t("An {n} Gerät(e) geschickt.", n=n) if n
                  else t("Kein Gerät erreicht – Anmeldung erneuern?"),
                  type="positive" if n else "warning")
        neu_zeichnen()

    with ui.row().classes("w-full gap-2 flex-wrap"):
        ui.button(t("Auf diesem Gerät einschalten"), icon="notifications_active",
                  on_click=einschalten).props("unelevated no-caps")
        if geraete:
            ui.button(t("Testnachricht"), icon="send", on_click=probe) \
                .props("outline no-caps")

    for g in geraete:
        with ui.row().classes("w-full items-center gap-2 no-wrap text-sm"):
            ui.icon("smartphone").classes("text-gray-400 text-base")
            ui.label(g.get("geraet") or "Gerät").classes("flex-grow truncate")
            ui.label((g.get("erstellt") or "")[:10]).classes("text-xs text-gray-400")
            ui.button(icon="delete", on_click=lambda _e=None, sid=g["id"]: (
                push.abmelden(sid), neu_zeichnen())) \
                .props("flat round dense size=sm color=negative")

    if geraete:
        _arten(benutzer)


def _arten(benutzer):
    """Welche Meldearten will dieser Mitarbeiter?"""
    u = USERS.get(benutzer, {})
    eigene = u.setdefault("push_arten", {})
    ui.label(t("Wobei möchtest du Bescheid bekommen?")) \
        .classes("text-xs font-semibold text-gray-400 mt-2")
    for schluessel, titel, erklaerung in ARTEN_TEXT:
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            with ui.column().classes("gap-0 min-w-0 flex-grow"):
                ui.label(t(titel)).classes("text-sm")
                ui.label(t(erklaerung)).classes("text-xs text-gray-500 truncate")

            def umschalten(e, k=schluessel):
                eigene[k] = bool(e.value)
                data.save_config()
            ui.switch(value=push.will(u, schluessel), on_change=umschalten) \
                .props("dense")
