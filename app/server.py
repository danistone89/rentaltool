#!/usr/bin/env python3
"""Lokaler Webserver für die Beherbergungssteuer-Anmeldung (nur stdlib).

Start:  python3 app/server.py    (Port aus config.json, Default 3001)
Öffnen: http://localhost:3001/

Routen:
  GET  /                      Dashboard + Berechnung + druckbares Formular
  POST /api/smoobu/webhook    Smoobu-Push: invalidiert den Buchungs-Cache
  GET  /healthz               Health-Check
"""
import json
import os
import sys
import time
import urllib.parse
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import smoobu, steuer, render  # noqa: E402
try:
    from app import pdf_form  # benötigt PyMuPDF
except Exception:  # pragma: no cover - PDF optional, App läuft auch ohne
    pdf_form = None

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))

# Einfacher In-Memory-Cache: {(from,to): (timestamp, bookings)}
_CACHE = {}
_CACHE_TTL = 300  # Sekunden


def _apartments():
    return smoobu.get_apartments(CFG["smoobu_api_key"])


def _reservations(date_from, date_to):
    key = (date_from, date_to)
    hit = _CACHE.get(key)
    if hit and (time.time() - hit[0]) < _CACHE_TTL:
        return hit[1]
    data = smoobu.get_reservations(CFG["smoobu_api_key"], date_from, date_to)
    _CACHE[key] = (time.time(), data)
    return data


def _save_settings(form):
    """Einstellungen aus dem Formular in CFG übernehmen und config.json schreiben."""
    def g(key, default=""):
        return form.get(key, [default])[0]

    betr = CFG.setdefault("betreiber", {})
    for key, _lbl in render._SETTINGS_BETREIBER:
        betr[key] = g("betreiber." + key, betr.get(key, ""))

    val = g("unterschrift_x", "")
    if val:
        f = float(val.replace(",", "."))
        CFG["unterschrift_x"] = int(f) if f == int(f) else f

    pct = g("steuersatz_pct", "")
    if pct:
        CFG["steuersatz"] = round(float(pct.replace(",", ".")) / 100, 4)

    ch = g("airbnb_channel_name", "").strip()
    if ch:
        CFG["airbnb_channel_name"] = ch

    api = g("smoobu_api_key", "").strip()
    if api:
        CFG["smoobu_api_key"] = api
        _CACHE.clear()

    with open(os.path.join(HERE, "config.json"), "w", encoding="utf-8") as fh:
        json.dump(CFG, fh, ensure_ascii=False, indent=2)


def _selection(q):
    today = date.today()
    return {
        "year": int(q.get("year", [today.year])[0]),
        "month": int(q.get("month", [today.month])[0]),
        "apt_ids": [int(x) for x in q.get("apt", [])],
        "airbnb": (q.get("airbnb", [""])[0] or "").strip(),
        "befreit": float(q.get("befreit", ["0"])[0] or 0),
    }


def _compute(q):
    """Reservierungen ziehen und Steuer für die Query berechnen."""
    sel = _selection(q)
    year, month = sel["year"], sel["month"]
    first = date(year, month, 1)
    d_from = (first - timedelta(days=92)).isoformat()
    nxt = date(year + (month == 12), (month % 12) + 1, 1)
    d_to = (nxt - timedelta(days=1)).isoformat()
    bookings = _reservations(d_from, d_to)
    if sel["apt_ids"]:
        ids = set(sel["apt_ids"])
        bookings = [b for b in bookings if (b.get("apartment") or {}).get("id") in ids]
    airbnb = int(sel["airbnb"]) if sel["airbnb"] else None
    return steuer.compute(
        bookings, year, month,
        steuersatz=CFG.get("steuersatz", 0.06),
        airbnb_channel=CFG.get("airbnb_channel_name", "Airbnb"),
        steuerbefreite_umsaetze=sel["befreit"],
        airbnb_overnights_override=airbnb)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        sys.stderr.write("[bhs] " + (a[0] % a[1:]) + "\n")

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/healthz":
            return self._send(200, "ok", "text/plain")
        if parsed.path == "/pdf":
            return self._serve_pdf(urllib.parse.parse_qs(parsed.query))
        if parsed.path == "/settings":
            saved = "saved" in urllib.parse.parse_qs(parsed.query)
            return self._send(200, render.settings_page(CFG, saved))
        if parsed.path != "/":
            return self._send(404, "Not found", "text/plain")

        q = urllib.parse.parse_qs(parsed.query)
        sel = _selection(q)
        try:
            apartments = _apartments()
        except smoobu.SmoobuError as ex:
            return self._send(502, render.dashboard(CFG, [], sel, None, error=str(ex)))

        result = None
        error = None
        if parsed.query:
            try:
                result = _compute(q)
            except smoobu.SmoobuError as ex:
                error = str(ex)

        return self._send(200, render.dashboard(CFG, apartments, sel, result, error))

    def _serve_pdf(self, q):
        if pdf_form is None:
            return self._send(503, "PDF-Erzeugung benötigt PyMuPDF "
                              "(pip install -r requirements.txt).", "text/plain; charset=utf-8")
        if not os.path.exists(pdf_form.TEMPLATE):
            return self._send(503, "Blanko-Vorlage fehlt. Bitte einmalig erzeugen: "
                              "python3 tools/make_blank.py <eingereichte.pdf> "
                              "(siehe templates/README.md).", "text/plain; charset=utf-8")
        try:
            result = _compute(q)
        except smoobu.SmoobuError as ex:
            return self._send(502, str(ex), "text/plain; charset=utf-8")
        datum = date.today().strftime("%d.%m.%Y")
        pdf = pdf_form.render_pdf(result, CFG, datum=datum)
        fname = f"Beherbergungssteuer_{result['year']}-{result['month']:02d}.pdf"
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Disposition", f'inline; filename="{fname}"')
        self.send_header("Content-Length", str(len(pdf)))
        self.end_headers()
        self.wfile.write(pdf)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/settings":
            length = int(self.headers.get("Content-Length", 0) or 0)
            form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
            _save_settings(form)
            self.send_response(303)
            self.send_header("Location", "/settings?saved=1")
            self.end_headers()
            return
        if parsed.path == "/api/smoobu/webhook":
            length = int(self.headers.get("Content-Length", 0) or 0)
            _ = self.rfile.read(length)  # Payload aktuell nur als Trigger genutzt
            _CACHE.clear()
            self.log_message("Webhook empfangen – Cache geleert")
            return self._send(200, json.dumps({"ok": True}), "application/json")
        return self._send(404, "Not found", "text/plain")


def main():
    port = int(CFG.get("port", 3001))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    sys.stderr.write(f"[bhs] Beherbergungssteuer-App läuft auf http://localhost:{port}/\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\n[bhs] beendet\n")


if __name__ == "__main__":
    main()
