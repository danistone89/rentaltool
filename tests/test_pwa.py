"""Die App als Handy-App: Manifest, Icons, Service Worker, Anleitung.

Der teure Fehler wäre hier nicht ein hässliches Icon, sondern ein Service
Worker, der die Anwendung zwischenspeichert: dann liefe nach einem Deploy noch
tagelang der alte Stand, und ohne Netz sähe man eine leere Hülle, die aussieht
wie die App. Deshalb wird vor allem geprüft, was er **nicht** tut.
"""
import json
import os
import sys

from nicegui.testing import User

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ui import pwa  # noqa: E402
from tests.test_web import _login, mock_backend  # noqa: E402,F401


# ------------------------------------------------------------------ Manifest
def test_manifest_startet_ohne_adressleiste():
    m = pwa.manifest()
    assert m["display"] == "standalone"
    assert m["start_url"] == "/" and m["scope"] == "/"
    assert m["name"] and m["short_name"]


def test_manifest_hat_die_noetigen_icon_groessen():
    groessen = {(i["sizes"], i["purpose"]) for i in pwa.manifest()["icons"]}
    assert ("192x192", "any") in groessen
    assert ("512x512", "any") in groessen
    # Android beschneidet zum Kreis – ohne maskable wird der Turm angeschnitten.
    assert ("512x512", "maskable") in groessen


def test_icons_liegen_wirklich_da():
    for name in ("icon-192.png", "icon-512.png", "icon-maskable-512.png",
                 "apple-touch-icon.png"):
        pfad = os.path.join(pwa.STATISCH, name)
        assert os.path.exists(pfad), f"{name} fehlt"
        with open(pfad, "rb") as f:
            assert f.read(8) == b"\x89PNG\r\n\x1a\n", f"{name} ist kein PNG"


# ------------------------------------------------------------------ Service Worker
def test_service_worker_speichert_die_anwendung_nicht():
    """Der wichtigste Test dieser Datei.

    Würde der Service Worker Dokumente oder das NiceGUI-JavaScript aus dem
    Zwischenspeicher liefern, liefe nach einem Deploy weiter der alte Stand –
    und ohne Netz erschiene eine leere Hülle, die aussieht wie die App.
    """
    js = pwa.SW_JS
    # Navigationen: erst das Netz, Zwischenspeicher nur als Rückfall.
    assert "fetch(e.request).catch(() => caches.match('/offline'))" in js
    # Zwischengespeichert werden ausschließlich eigene statische Dateien.
    assert "url.pathname.startsWith('/static/')" in js
    assert "_nicegui" not in js


def test_service_worker_raeumt_alte_staende_weg():
    assert "caches.delete" in pwa.SW_JS and "VERSION" in pwa.SW_JS


def test_kopf_meldet_manifest_icon_und_service_worker():
    kopf = pwa.KOPF_HTML % {"purple": "#5E2A84"}
    assert 'rel="manifest" href="/manifest.webmanifest"' in kopf
    assert 'rel="apple-touch-icon"' in kopf
    assert "serviceWorker" in kopf
    # Ohne apple-mobile-web-app-capable öffnet iOS die Seite mit Adressleiste.
    assert 'name="apple-mobile-web-app-capable" content="yes"' in kopf
    # Kamera-Insel oben, Balken unten: sonst klebt der Kopf unter der Uhr.
    assert "env(safe-area-inset-top)" in kopf


# ------------------------------------------------------------------ Routen (echte Abrufe)
async def test_manifest_wird_ausgeliefert(user: User):
    antwort = await user.http_client.get("/manifest.webmanifest")
    assert antwort.status_code == 200
    assert antwort.headers["content-type"].startswith("application/manifest+json")
    assert json.loads(antwort.text)["display"] == "standalone"


async def test_service_worker_wird_als_javascript_ausgeliefert(user: User):
    antwort = await user.http_client.get("/sw.js")
    assert antwort.status_code == 200
    assert "javascript" in antwort.headers["content-type"]
    # Ohne no-cache hinge ein alter Service Worker fest – ausgerechnet der Teil,
    # der sich selbst erneuern soll.
    assert "no-cache" in antwort.headers.get("cache-control", "")


async def test_offlineseite_erklaert_die_lage(user: User):
    antwort = await user.http_client.get("/offline")
    assert antwort.status_code == 200
    assert "Keine Verbindung" in antwort.text
    assert "No connection" in antwort.text        # Gabriel arbeitet auf Englisch


async def test_icons_und_manifest_sind_ohne_login_erreichbar(user: User):
    """Das Handy holt Manifest und Icon, bevor irgendwer angemeldet ist – landen
    sie auf der Anmeldeseite, bleibt das Symbol grau."""
    for pfad in ("/manifest.webmanifest", "/static/icon-192.png",
                 "/apple-touch-icon.png"):
        antwort = await user.http_client.get(pfad)
        assert antwort.status_code == 200, f"{pfad} -> {antwort.status_code}"
        assert "<title>" not in antwort.text[:200], f"{pfad} liefert eine HTML-Seite"


# ------------------------------------------------------------------ Anleitung
async def test_anleitung_steht_in_mein_konto(user: User, mock_backend):  # noqa: F811
    await _login(user)
    user.find(marker="nav-konto").click()
    await user.should_see("Als App einrichten")
    await user.should_see("Zum Home-Bildschirm")      # iPhone-Weg
    await user.should_see("App installieren")          # Android-Weg
