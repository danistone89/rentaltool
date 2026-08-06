#!/usr/bin/env python3
"""Bildschirmfotos der laufenden Oberfläche – auch hinter dem Login.

    python3 tools/uishot.py --ziel /tmp/bilder
    python3 tools/uishot.py --ziel /tmp/bilder --breit      # zusätzlich am Rechner

Wozu? Eine Oberfläche lässt sich nicht aus dem Quelltext beurteilen. Der
Prüf-Agent (`.claude/agents/ui-design.md`) braucht Bilder von dem, was ein
Mitarbeiter tatsächlich sieht – und die liegen hinter der Anmeldung.

Wie es läuft: Das Werkzeug startet die App mit einem **Wegwerf-Datenordner**
(eigene Konten, eigene Datenbank, erfundene Buchungen), fährt Chrome fern und
klickt sich wie ein Mensch durch: anmelden, Bereich öffnen, auslösen. Der
Echtbetrieb wird dabei nicht angefasst.

Chrome wird über das DevTools-Protokoll gesteuert (WebSocket). Ein einfaches
`--screenshot` reicht nicht: NiceGUI baut die Oberfläche erst über eine offene
Verbindung auf, und ohne Anmeldung sieht man nur die Login-Seite.
"""
import argparse
import asyncio
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CHROME_KANDIDATEN = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
]
BENUTZER, PASSWORT = "pruef", "pruef-pruef"

# Was aufgenommen wird: (Dateiname, [Schritte]) – ein Schritt ist Text zum
# Anklicken oder eine Wartezeit als Zahl.
AUFNAHMEN = [
    ("01-anmeldung", []),
    ("02-buchungen-meine", ["@login"]),
    ("03-buchungen-alle", ["@login", "Alle Reinigungen"]),
    ("04-buchung-dialog", ["@login", "Alle Reinigungen", "Cottaer Straße"]),
    # Seit AP-D1 stehen Bereiche in der Leiste unten; ihre Beschriftung ist
    # anklickbarer Text. Was dort keinen Platz hat, liegt im Menü (@menue:).
    ("05-zeiterfassung", ["@login", "@menue:Zeiterfassung"]),
    ("06-belege", ["@login", "Belege"]),
    ("07-uebersicht", ["@login", "Übersicht"]),
    ("08-kennzahlen", ["@login", "Übersicht", "Kennzahlen"]),
    ("09-mein-konto", ["@login", "@menue:Mein Konto"]),
    ("10-einstellungen", ["@login", "@menue:Einstellungen"]),
    # Das Menü-Blatt gibt es nur am Handy – am Rechner steht alles in der
    # Schublade. Das "?" macht den Schritt freiwillig: fehlt er dort, ist das
    # kein Befund, sondern erwartet.
    ("11-menue", ["@login", "?Menü"]),
]


def chrome_pfad():
    for p in CHROME_KANDIDATEN:
        if os.path.exists(p):
            return p
    raise SystemExit("Kein Chrome gefunden – Pfad in CHROME_KANDIDATEN ergänzen.")


def freier_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ------------------------------------------------------------------ Testdaten
def datenordner_bauen(ordner):
    """Wegwerf-Datenordner: eigene Konten, eigene Datenbank, erfundene Buchungen."""
    from app import auth
    os.makedirs(ordner, exist_ok=True)
    hier = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = json.load(open(os.path.join(hier, "config.example.json"), encoding="utf-8"))
    cfg["auth"] = {"users": {
        BENUTZER: {"password_hash": auth.hash_password(PASSWORT), "role": "admin",
                   "totp_secret": "", "name": "Prüfkonto"},
        "gabriel": {"password_hash": auth.hash_password("x"), "role": "putzkraft",
                    "totp_secret": "", "name": "Gabriel", "lang": "de"},
    }}
    cfg["stundensatz_werktag"] = 15
    json.dump(cfg, open(os.path.join(ordner, "config.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    for name in ("templates", "assets", "media"):
        quelle = os.path.join(hier, name)
        if os.path.isdir(quelle):
            shutil.copytree(quelle, os.path.join(ordner, name), dirs_exist_ok=True)


ERFUNDENE_BUCHUNGEN = '''
import datetime as _dt
from app import data as _data

def _b(bid, apt_id, apt, ab_tage, an_tage, gast, personen=2):
    heute = _dt.date.today()
    return {"id": bid, "type": "reservation", "is-blocked-booking": False,
            "apartment": {"id": apt_id, "name": apt},
            "arrival": (heute + _dt.timedelta(days=an_tage)).isoformat(),
            "departure": (heute + _dt.timedelta(days=ab_tage)).isoformat(),
            "check-in": "15:00", "check-out": "10:00",
            "adults": personen, "children": 0, "guest-name": gast,
            "price": 480.0, "channel": {"name": "Booking.com"},
            "price-details": "Reinigungsgebühr - EUR 65\\nÜbernachtungssteuer - EUR 27.17",
            "notice": ""}

_FAKE = [_b(9001, 2748963, "Cottaer Straße", 0, -4, "Anja Ernst"),
         _b(9002, 2960031, "Wernerstraße", 0, -3, "Jan Peters", 3),
         _b(9003, 2748963, "Cottaer Straße", 2, 0, "Katarina Gockel"),
         _b(9004, 2960031, "Wernerstraße", 4, 2, "Alexander Josan", 4),
         _b(9005, 2748963, "Cottaer Straße", 7, 4, "Kusala Sami")]
_data._reservations = lambda *a, **k: _FAKE
_data.get_apartments = lambda: [{"id": 2748963, "name": "Cottaer Straße"},
                                {"id": 2960031, "name": "Wernerstraße"}]
'''


def app_starten(ordner, port):
    """App mit dem Wegwerf-Ordner starten. Gibt den Prozess zurück."""
    hier = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    start = os.path.join(ordner, "_start.py")
    with open(start, "w", encoding="utf-8") as f:
        f.write(f"import sys; sys.path.insert(0, {hier!r})\n")
        f.write(ERFUNDENE_BUCHUNGEN)
        f.write(f"\nimport json, os\n"
                f"quelle = open({os.path.join(hier, 'app', 'web.py')!r}, encoding='utf-8').read()\n"
                f"quelle = quelle.replace('if __name__ in {{\"__main__\", \"__mp_main__\"}}', 'if True')\n"
                f"exec(compile(quelle, {os.path.join(hier, 'app', 'web.py')!r}, 'exec'))\n")
    umgebung = {**os.environ, "RENTALTOOL_DATA": ordner, "RENTALTOOL_PORT": str(port)}
    # Port steht in der config.json des Wegwerf-Ordners
    cfg_pfad = os.path.join(ordner, "config.json")
    cfg = json.load(open(cfg_pfad, encoding="utf-8"))
    cfg["port"] = port
    json.dump(cfg, open(cfg_pfad, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    python = os.path.join(hier, ".venv", "bin", "python")
    if not os.path.exists(python):
        python = sys.executable
    return subprocess.Popen([python, start], env=umgebung, cwd=hier,
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def warten_auf(url, sekunden=40):
    ende = time.time() + sekunden
    while time.time() < ende:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


# ------------------------------------------------------------------ Chrome fernsteuern
class Browser:
    def __init__(self, port, breite, hoehe):
        self.port, self.breite, self.hoehe = port, breite, hoehe
        self.nr = 0

    async def __aenter__(self):
        import websockets
        self.profil = tempfile.mkdtemp()
        self.proc = subprocess.Popen(
            [chrome_pfad(), "--headless=new", f"--remote-debugging-port={self.port}",
             f"--user-data-dir={self.profil}", "--no-first-run", "--disable-gpu",
             "--hide-scrollbars", "--disable-dev-shm-usage", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ziel = None
        ende = time.time() + 25
        while time.time() < ende and not ziel:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json") as r:
                    for t in json.load(r):
                        if t.get("type") == "page":
                            ziel = t["webSocketDebuggerUrl"]
            except Exception:
                time.sleep(0.4)
        if not ziel:
            raise RuntimeError("Chrome meldet sich nicht.")
        self.ws = await websockets.connect(ziel, max_size=60 * 1024 * 1024)
        await self("Page.enable")
        await self("Runtime.enable")
        # Maßstab 1, nicht 2: Beurteilt wird die Anordnung, nicht die Schärfe –
        # und doppelte Auflösung vervierfacht die Dateigröße. Zehn Bilder in
        # Retina-Größe sprengten den Prüf-Agenten reproduzierbar.
        await self("Emulation.setDeviceMetricsOverride", width=self.breite,
                   height=self.hoehe, deviceScaleFactor=1, mobile=self.breite < 700)
        return self

    async def __aexit__(self, *a):
        try:
            await self.ws.close()
        finally:
            self.proc.terminate()
            shutil.rmtree(self.profil, ignore_errors=True)

    async def __call__(self, methode, **params):
        self.nr += 1
        await self.ws.send(json.dumps({"id": self.nr, "method": methode, "params": params}))
        while True:
            antwort = json.loads(await self.ws.recv())
            if antwort.get("id") == self.nr:
                if "error" in antwort:
                    raise RuntimeError(f"{methode}: {antwort['error']}")
                return antwort.get("result", {})

    async def js(self, ausdruck):
        r = await self("Runtime.evaluate", expression=ausdruck, awaitPromise=True,
                       returnByValue=True)
        return (r.get("result") or {}).get("value")

    async def oeffnen(self, url):
        await self("Page.navigate", url=url)
        await asyncio.sleep(2.5)          # NiceGUI baut über die Verbindung auf

    async def anmelden(self, benutzer, passwort):
        await self.js(f"""(() => {{
            const f = [...document.querySelectorAll('input')];
            const setzen = (el, wert) => {{
              const s = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;
              s.call(el, wert);
              el.dispatchEvent(new Event('input', {{bubbles: true}}));
              el.dispatchEvent(new Event('change', {{bubbles: true}}));
            }};
            setzen(f[0], {benutzer!r}); setzen(f[1], {passwort!r});
            return f.length;
        }})()""")
        await asyncio.sleep(0.6)
        await self.klick("Anmelden")
        await asyncio.sleep(3.0)

    async def klick(self, text):
        """Erstes sichtbares Element mit diesem Text anklicken.

        Ohne Rücksicht auf Groß- und Kleinschreibung: Quasar setzt
        Knopf-Beschriftungen per CSS in Großbuchstaben, `innerText` liefert die
        **gerenderte** Fassung – „Anmelden" findet sonst „ANMELDEN" nicht.
        """
        getroffen = await self.js("""(() => {
            const suche = %s.toLowerCase();
            const alle = [...document.querySelectorAll(
                'button, .q-item, .q-tab, [role=button], .q-card, ' +
                '.q-expansion-item__container, .cursor-pointer')];
            const treffer = alle.filter(e => (e.innerText || '').toLowerCase()
                            .includes(suche) && e.offsetParent !== null);
            if (!treffer.length) return false;
            // Das SPEZIFISCHSTE Element gewinnt: die Karte enthaelt den Text des
            // Knopfes ebenfalls und steht im Dokument davor – ein Klick auf sie
            // loeste gar nichts aus. Klicks blubbern ohnehin nach oben.
            treffer.sort((a, b) => (a.innerText || '').length - (b.innerText || '').length);
            treffer[0].click();
            return true;
        })()""" % json.dumps(text))
        await asyncio.sleep(1.6)
        return getroffen

    async def symbolklick(self, symbol):
        """Knopf über sein Symbol anklicken – der Schubladen-Griff hat keinen Text."""
        return await self.js("""(() => {
            const knopf = [...document.querySelectorAll('button')].find(b =>
                [...b.querySelectorAll('i')].some(i =>
                    (i.innerText || '').trim() === %s) && b.offsetParent !== null);
            if (!knopf) return false;
            knopf.click();
            return true;
        })()""" % json.dumps(symbol))

    async def foto(self, pfad):
        # Genau EIN Bildschirm, nicht die ganze Seite: Die Frage „was sieht man,
        # ohne zu scrollen" ist die wichtigste bei der Beurteilung – ein Bild der
        # kompletten Seite beantwortet sie nicht.
        r = await self("Page.captureScreenshot", format="png", captureBeyondViewport=False)
        with open(pfad, "wb") as f:
            f.write(base64.b64decode(r["data"]))
        return pfad


async def aufnehmen(app_port, ziel, breite, hoehe, suffix=""):
    gemacht = []
    async with Browser(freier_port(), breite, hoehe) as b:
        for name, schritte in AUFNAHMEN:
            await b.oeffnen(f"http://127.0.0.1:{app_port}/login")
            fehlend = []
            for schritt in schritte:
                if schritt == "@login":
                    await b.anmelden(BENUTZER, PASSWORT)
                elif schritt.startswith("@menue:"):
                    # Am Handy liegt der Eintrag im Menü-Blatt, ab Tablet steht
                    # er direkt in der Schublade. Also erst das Blatt öffnen –
                    # gibt es keines, führt der Klick auf „Menü" ins Leere und
                    # der Eintrag wird gleich darauf direkt gefunden.
                    await b.klick("Menü")
                    await asyncio.sleep(0.6)
                    if not await b.klick(schritt[7:]):
                        fehlend.append(schritt)
                else:
                    freiwillig = schritt.startswith("?")
                    if not await b.klick(schritt.lstrip("?")) and not freiwillig:
                        fehlend.append(schritt)
            pfad = os.path.join(ziel, f"{name}{suffix}.png")
            await b.foto(pfad)
            gemacht.append((pfad, fehlend))
            print(f"   {os.path.basename(pfad)}"
                  + (f"   (nicht gefunden: {', '.join(fehlend)})" if fehlend else ""))
    return gemacht


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ziel", required=True, help="Ordner für die Bilder")
    ap.add_argument("--breit", action="store_true", help="zusätzlich in Rechnerbreite")
    ap.add_argument("--breite", type=int, default=390)
    ap.add_argument("--hoehe", type=int, default=844)
    args = ap.parse_args(argv)

    os.makedirs(args.ziel, exist_ok=True)
    ordner = tempfile.mkdtemp(prefix="uishot-")
    port = freier_port()
    print(f"Wegwerf-Daten: {ordner}\nApp auf Port {port}")
    datenordner_bauen(ordner)
    proc = app_starten(ordner, port)
    try:
        if not warten_auf(f"http://127.0.0.1:{port}/login"):
            raise SystemExit("App startet nicht – Wegwerf-Ordner prüfen.")
        print(f"Handy ({args.breite}×{args.hoehe}):")
        asyncio.run(aufnehmen(port, args.ziel, args.breite, args.hoehe))
        if args.breit:
            print("Rechner (1280×900):")
            asyncio.run(aufnehmen(port, args.ziel, 1280, 900, suffix="-breit"))
    finally:
        proc.terminate()
        shutil.rmtree(ordner, ignore_errors=True)
    print(f"\nFertig: {args.ziel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
