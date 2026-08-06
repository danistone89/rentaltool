#!/usr/bin/env python3
"""Die App als Handy-App: Home-Bildschirm, eigenes Icon, Verhalten ohne Netz.

Die Putzkräfte arbeiten ausschließlich am Handy. Bisher war das eine
Browser-Seite unter einer Adresse: Adressleiste, Safari-Tabs, kein Icon, und
beim Funkloch die Fehlerseite des Browsers.

Was hier dazukommt:

* **Manifest** (`/manifest.webmanifest`) – Name, Icon, Farben, Start ohne
  Adressleiste.
* **Icons** aus der Wortbildmarke (`app/ui/static/`), der Turm allein auf
  Markenviolett – ein Schriftzug ist auf 60 px nicht zu lesen.
* **Service Worker** (`/sw.js`) – ausschließlich für zwei Dinge: Icons/Manifest
  aus dem Zwischenspeicher, und statt der Browser-Fehlerseite eine eigene Seite,
  die auf Deutsch/Englisch sagt, was los ist.
* **Anleitung zum Einrichten**, weil Safari keinen Installations-Dialog kennt.

Bewusst **kein** Zwischenspeichern der Anwendung selbst. NiceGUI baut die
Oberfläche über eine offene Verbindung zum Server auf; eine zwischengespeicherte
Hülle ohne Verbindung sähe aus wie die App, wäre aber leer. Schlimmer noch:
veraltetes JavaScript im Zwischenspeicher bricht die App nach einem Deploy.
Darum gilt für alles außer den eigenen statischen Dateien: **erst das Netz**.

Was auf iOS nicht geht (Stand iOS 26, geprüft an den WebKit-Quellen):

* Kein Installations-Dialog (`beforeinstallprompt` gibt es in Safari nicht) –
  deshalb die Anleitung.
* **Push-Benachrichtigungen nur, wenn die App auf dem Home-Bildschirm liegt.**
  Im Safari-Tab kommt nichts an. Das ist der Grund, warum dieses Paket vor den
  Benachrichtigungen (AP7) kommt.
* Kein verlässlicher Background-Sync: „ohne Netz erfassen und später senden"
  wäre nicht zu halten. Ohne Netz bleibt die App deshalb **lesbar**, nicht
  schreibfähig.
"""
import json
import os

from nicegui import app, ui
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response

from app.ui.basis import GOLD, PURPLE, SAND, t

STATISCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
NAME = "LIVARO Suites"
# Hochzählen, sobald sich die statischen Dateien ändern: der Service Worker
# räumt beim Aktivieren jeden älteren Zwischenspeicher weg.
VERSION = "1"


def manifest():
    return {
        "name": NAME,
        "short_name": "LIVARO",
        "description": "Reinigungen, Zeiterfassung und Belege für die Ferienwohnungen",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": SAND,
        "theme_color": PURPLE,
        "lang": "de",
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png",
             "purpose": "any"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png",
             "purpose": "any"},
            {"src": "/static/icon-maskable-512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
    }


SW_JS = """
// Service Worker der LIVARO-App. Absichtlich klein – siehe app/ui/pwa.py.
const VERSION = '%(version)s';
const SPEICHER = 'livaro-' + VERSION;
const STATISCH = ['/static/icon-192.png', '/static/icon-512.png',
                  '/static/apple-touch-icon.png', '/manifest.webmanifest', '/offline'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SPEICHER).then((c) => c.addAll(STATISCH)));
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  // Alte Stände wegräumen, sonst liefert ein Deploy weiter die alten Dateien.
  e.waitUntil(caches.keys().then((namen) => Promise.all(
    namen.filter((n) => n !== SPEICHER).map((n) => caches.delete(n))
  )).then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;

  // Eigene statische Dateien: aus dem Speicher, das spart Ladezeit am Handy.
  if (url.pathname.startsWith('/static/') || url.pathname === '/manifest.webmanifest') {
    e.respondWith(caches.match(e.request).then((treffer) => treffer || fetch(e.request)));
    return;
  }

  // Alles andere: erst das Netz. Die Oberflaeche kommt ueber eine offene
  // Verbindung zum Server – eine gespeicherte Huelle waere leer.
  if (e.request.mode === 'navigate') {
    e.respondWith(fetch(e.request).catch(() => caches.match('/offline')));
  }
});
"""


OFFLINE_HTML = """<!doctype html>
<html lang="de"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>%(name)s – keine Verbindung</title>
<style>
  body { margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
         background:%(sand)s; color:#2D2D2D;
         font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
  .karte { max-width:22rem; margin:1.5rem; padding:1.75rem; background:#fff; border-radius:1rem;
           box-shadow:0 1px 3px rgba(0,0,0,.08); text-align:center; }
  h1 { font-size:1.15rem; margin:.75rem 0 .5rem; }
  p { font-size:.95rem; line-height:1.5; color:#555; margin:.5rem 0; }
  .en { color:#888; font-size:.85rem; }
  button { margin-top:1.25rem; width:100%%; padding:.8rem; font-size:1rem; border:0;
           border-radius:.6rem; background:%(purple)s; color:#fff; font-weight:600; }
  svg { width:56px; height:56px; }
</style></head>
<body><div class="karte">
  <svg viewBox="0 0 60 72" fill="none" stroke="%(gold)s" stroke-width="3.4"
       stroke-linejoin="round" stroke-linecap="round">
    <path d="M8 60 L8 23 L26 12 L26 60"/><path d="M22 60 L22 33 L38 24 L38 60"/>
    <path d="M34 60 L34 44 L50 35 L50 60"/></svg>
  <h1>Keine Verbindung</h1>
  <p>Die Reinigungsliste kommt vom Server – dafür braucht dein Handy Empfang
     oder WLAN.</p>
  <p class="en">No connection. The cleaning list needs internet access.</p>
  <button onclick="location.replace('/')">Erneut versuchen · Try again</button>
</div></body></html>
"""


def routen_registrieren():
    """Manifest, Service Worker und Offline-Seite anmelden.

    Wie bei den Seiten in `zugang`: ein Aufruf, kein Dekorator – `app/web.py`
    wird im Testlauf je Test erneut ausgeführt, dieses Modul aber nur einmal
    geladen.
    """
    app.add_static_files("/static", STATISCH)

    @app.get("/manifest.webmanifest")
    def _manifest():
        return JSONResponse(manifest(),
                            media_type="application/manifest+json",
                            headers={"Cache-Control": "public, max-age=3600"})

    @app.get("/sw.js")
    def _sw():
        return Response(SW_JS % {"version": VERSION}, media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})

    @app.get("/offline")
    def _offline():
        return HTMLResponse(OFFLINE_HTML % {"name": NAME, "sand": SAND,
                                            "purple": PURPLE, "gold": GOLD})

    @app.get("/apple-touch-icon.png")
    @app.get("/apple-touch-icon-precomposed.png")
    def _apple_icon():
        # iOS sucht das Icon zuerst unter diesen festen Adressen.
        return FileResponse(os.path.join(STATISCH, "apple-touch-icon.png"))


KOPF_HTML = """
    <link rel="manifest" href="/manifest.webmanifest">
    <link rel="apple-touch-icon" href="/static/apple-touch-icon.png">
    <meta name="theme-color" content="%(purple)s">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-title" content="LIVARO">
    <meta name="apple-mobile-web-app-status-bar-style" content="default">
    <style>
      /* Vom Home-Bildschirm gestartet reicht die Seite unter die Kamera-Insel
         und ueber den Balken am unteren Rand. */
      body { padding-bottom: env(safe-area-inset-bottom); }
      .q-header { padding-top: env(safe-area-inset-top); }
    </style>
    <script>
      if ('serviceWorker' in navigator) {
        window.addEventListener('load', () => navigator.serviceWorker
          .register('/sw.js').catch(() => {}));
      }
    </script>
"""


def kopf():
    """Kopfzeilen der Seite: Manifest, Icons, Farben, sichere Raender.

    Muss auf jeder Seite laufen (auch auf der Anmeldeseite) – wer die App vom
    Home-Bildschirm startet und noch nicht angemeldet ist, landet dort.
    """
    ui.add_head_html(KOPF_HTML % {"purple": PURPLE})


def als_app_gestartet():
    """JS-Ausdruck: laeuft die Seite als Home-Bildschirm-App?"""
    return ("(window.navigator.standalone === true) || "
            "window.matchMedia('(display-mode: standalone)').matches")


def einrichten_hinweis():
    """Anleitung „Zum Home-Bildschirm hinzufuegen“ – gefaltet, nicht aufdringlich.

    Safari kennt keinen Installations-Dialog; ohne Anleitung passiert es nie.
    Auf Android gibt es einen eigenen Weg ueber das Browser-Menue, deshalb
    stehen beide Wege da.
    """
    with ui.expansion(t("Als App einrichten"), icon="add_to_home_screen") \
            .classes("w-full border border-slate-200 rounded-xl") as box:
        ui.label(t("Danach startest du die App über ein eigenes Symbol – ohne "
                   "Adressleiste, und Benachrichtigungen sind erst dann möglich.")) \
            .classes("text-sm text-gray-600")
        for titel, schritte in (
                ("iPhone / iPad (Safari)",
                 (t("Unten auf das Teilen-Symbol tippen (Viereck mit Pfeil)"),
                  t("„Zum Home-Bildschirm“ wählen"),
                  t("Oben rechts auf „Hinzufügen“ tippen"))),
                ("Android (Chrome)",
                 (t("Oben rechts auf die drei Punkte tippen"),
                  t("„App installieren“ bzw. „Zum Startbildschirm hinzufügen“ wählen")))):
            with ui.column().classes("gap-1 mt-2 w-full"):
                ui.label(titel).classes("text-xs font-semibold text-gray-400")
                for schritt in schritte:
                    with ui.row().classes("items-start gap-2 no-wrap"):
                        ui.icon("chevron_right") \
                            .classes("text-primary text-base mt-0.5 shrink-0")
                        ui.label(schritt).classes("text-sm")
    return box


BANNER_JS = """
<script>
  (() => {
    const alsApp = %(alsapp)s;
    const handy = window.matchMedia('(max-width: 820px)').matches;
    const weg = localStorage.getItem('livaro-hinweis') === 'weg';
    if (alsApp || !handy || weg) return;
    const zeigen = () => {
      const el = document.getElementById('%(kennung)s');
      if (el) { el.style.display = 'flex'; } else { setTimeout(zeigen, 200); }
    };
    zeigen();
  })();
</script>
"""


def einrichten_banner():
    """Einmaliger Hinweis oben auf der Seite – nur am Handy, nur im Browser.

    Sichtbar wird er erst im Browser: der Server kann nicht wissen, ob die Seite
    gerade als App laeuft. Wer ihn wegtippt, sieht ihn nicht wieder (Merker im
    Browser); die Anleitung bleibt unter „Mein Konto“ erreichbar.
    """
    box = ui.row().classes("w-full items-center gap-2 no-wrap bg-violet-50 border "
                           "border-violet-200 rounded-xl px-3 py-2 mb-1")
    box.set_visibility(False)
    kennung = f"livaro-hinweis-{box.id}"
    box.props(f'id={kennung}')
    with box:
        ui.icon("add_to_home_screen").classes("text-primary text-xl shrink-0")
        with ui.column().classes("gap-0 min-w-0 flex-grow"):
            ui.label(t("Als App einrichten")).classes("text-sm font-medium text-slate-700")
            ui.label(t("Ein Symbol auf dem Home-Bildschirm – so geht es unter „Mein Konto“.")) \
                .classes("text-xs text-gray-500 truncate")
        ui.button(icon="close", on_click=lambda: (
            ui.run_javascript("localStorage.setItem('livaro-hinweis','weg')"),
            box.set_visibility(False))).props("flat round dense size=sm")
    ui.add_body_html(BANNER_JS % {"alsapp": als_app_gestartet(), "kennung": kennung})
    return box
