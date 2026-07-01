#!/usr/bin/env python3
"""Revisionssichere Ablage erzeugter Steueranmeldungen.

Sobald ein amtliches PDF „festgeschrieben" wird, landet es unveränderbar im
Archiv:

* Datei wird unter archive/<jahr>/Beherbergungssteuer_<periode>_v<rev>.pdf
  gespeichert und auf **schreibgeschützt** (0444) gesetzt.
* Es wird NIE überschrieben – eine erneute Erstellung legt eine neue Revision an
  (v2, v3 …), die alte bleibt erhalten (entspricht der „berichtigten Anmeldung").
* Jede Ablage wird in einer **append-only Hash-Kette** (archive/ledger.jsonl)
  protokolliert: jeder Eintrag enthält den SHA-256 der PDF und verkettet sich
  über `prev_hash` mit dem vorigen Eintrag. Jede nachträgliche Änderung an einer
  Datei oder einem Eintrag bricht die Kette und ist damit nachweisbar.

Hinweis: Das ist pragmatische Revisionssicherheit (Integrität, Unveränderbarkeit,
lückenloser Nachweis). Für volle GoBD-Konformität gehört das Archiv zusätzlich auf
ein WORM-/Backup-Medium außerhalb dieses Rechners.
"""
import base64
import hashlib
import json
import os
import shutil
import urllib.error
import urllib.request
from datetime import datetime
from urllib.parse import quote

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVE_DIR = os.path.join(HERE, "archive")
LEDGER_PATH = os.path.join(ARCHIVE_DIR, "ledger.jsonl")
GENESIS = "GENESIS"


def _sha256(b):
    return hashlib.sha256(b).hexdigest()


def _entry_hash(prev_hash, core):
    payload = prev_hash + "\n" + json.dumps(core, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def list_entries():
    if not os.path.exists(LEDGER_PATH):
        return []
    out = []
    with open(LEDGER_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _next_revision(period, entries):
    return 1 + sum(1 for e in entries if e["period"] == period)


def archive_pdf(pdf_bytes, period, values, *, now=None):
    """PDF unveränderbar ablegen und Ledger-Eintrag (Hash-Kette) anhängen.

    period: 'JJJJ-MM'. values: Dict der Formularwerte (für den Nachweis).
    Gibt den Ledger-Eintrag zurück.
    """
    entries = list_entries()
    revision = _next_revision(period, entries)
    year = period.split("-")[0]
    year_dir = os.path.join(ARCHIVE_DIR, year)
    os.makedirs(year_dir, exist_ok=True)

    fname = f"Beherbergungssteuer_{period}_v{revision}.pdf"
    rel = os.path.join(year, fname)
    abspath = os.path.join(ARCHIVE_DIR, rel)

    with open(abspath, "wb") as f:
        f.write(pdf_bytes)
    os.chmod(abspath, 0o444)  # schreibgeschützt

    prev_hash = entries[-1]["entry_hash"] if entries else GENESIS
    core = {
        "seq": len(entries) + 1,
        "ts": (now or datetime.now()).isoformat(timespec="seconds"),
        "period": period,
        "revision": revision,
        "file": rel,
        "sha256": _sha256(pdf_bytes),
        "values": values,
    }
    entry = {**core, "prev_hash": prev_hash, "entry_hash": _entry_hash(prev_hash, core)}

    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    with open(LEDGER_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def verify():
    """Kette + Dateien prüfen. Liefert (gesamt_ok, [pro-Eintrag-Status])."""
    entries = list_entries()
    results = []
    prev = GENESIS
    all_ok = True
    for e in entries:
        issues = []
        core = {k: e[k] for k in ("seq", "ts", "period", "revision", "file", "sha256", "values")}
        if e.get("prev_hash") != prev:
            issues.append("Kette unterbrochen (prev_hash)")
        if _entry_hash(e.get("prev_hash", ""), core) != e.get("entry_hash"):
            issues.append("Eintrag verändert (entry_hash)")
        abspath = os.path.join(ARCHIVE_DIR, e["file"])
        if not os.path.exists(abspath):
            issues.append("Datei fehlt")
        elif _sha256(open(abspath, "rb").read()) != e["sha256"]:
            issues.append("Datei verändert (sha256)")
        ok = not issues
        all_ok = all_ok and ok
        results.append({"seq": e["seq"], "period": e["period"], "revision": e["revision"],
                        "ts": e["ts"], "ok": ok, "issues": issues})
        prev = e.get("entry_hash", "")
    return all_ok, results


def read_pdf(rel_file):
    with open(os.path.join(ARCHIVE_DIR, rel_file), "rb") as f:
        return f.read()


# ============================================ Spiegel (Nextcloud / lokaler Ordner)
# Zwei Ziele möglich:
#   * WebDAV/Nextcloud (cfg["archiv_webdav"]) – für Server-Betrieb (kein Sync-Client)
#   * lokaler Ordner (cfg["archiv_spiegel"]) – für lokalen Betrieb (Nextcloud-Sync)
# WebDAV hat Vorrang, wenn konfiguriert.

def _webdav_cfg(cfg):
    w = (cfg or {}).get("archiv_webdav") or {}
    if w.get("url") and w.get("user") and w.get("password"):
        return w
    return None


def has_mirror(cfg):
    return bool(_webdav_cfg(cfg) or (cfg or {}).get("archiv_spiegel"))


def mirror_label(cfg):
    return "Nextcloud (WebDAV)" if _webdav_cfg(cfg) else "Spiegel-Ordner"


# ---- lokaler Ordner ----
def _copy_ro(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        try:
            os.chmod(dst, 0o644)
        except OSError:
            pass
    shutil.copy2(src, dst)
    try:
        os.chmod(dst, 0o444)
    except OSError:
        pass


# ---- WebDAV (Nextcloud) ----
def _dav_base(w):
    url = w["url"].strip().rstrip("/")
    if "/remote.php/dav/files/" not in url:
        url = f"{url}/remote.php/dav/files/{w['user']}"
    return url.rstrip("/")


def _dav_encode(rel):
    return "/".join(quote(p) for p in rel.split("/") if p)


def _dav_request(method, url, w, data=None, headers=None):
    req = urllib.request.Request(url, data=data, method=method)
    tok = base64.b64encode(f"{w['user']}:{w['password']}".encode()).decode()
    req.add_header("Authorization", "Basic " + tok)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except urllib.error.URLError as e:
        raise RuntimeError(f"Nextcloud nicht erreichbar: {e}")


def _dav_mkcol_path(w, rel_dir):
    base = _dav_base(w)
    cur = base
    for seg in [s for s in rel_dir.split("/") if s]:
        cur = cur + "/" + quote(seg)
        code = _dav_request("MKCOL", cur, w)
        if code not in (201, 405, 301):  # 405 = existiert schon
            raise RuntimeError(f"Nextcloud MKCOL {code} für {cur}")


def _dav_put(w, rel_path, data):
    url = _dav_base(w) + "/" + _dav_encode(rel_path)
    code = _dav_request("PUT", url, w, data=data)
    if code not in (200, 201, 204):
        raise RuntimeError(f"Nextcloud PUT {code} für {rel_path}")


def webdav_test(w):
    """Verbindung/Anmeldung prüfen (PROPFIND). Gibt (ok, meldung)."""
    if not (w.get("url") and w.get("user") and w.get("password")):
        return False, "URL, Benutzer und App-Passwort nötig."
    try:
        code = _dav_request("PROPFIND", _dav_base(w), w, headers={"Depth": "0"})
    except RuntimeError as ex:
        return False, str(ex)
    if code in (207, 200):
        # Zielordner anlegen (idempotent), damit später sicher vorhanden
        try:
            if w.get("folder"):
                _dav_mkcol_path(w, w["folder"])
        except RuntimeError as ex:
            return False, f"Verbunden, aber Ordner-Anlage scheiterte: {ex}"
        return True, "Verbindung OK, Ordner bereit."
    if code in (401, 403):
        return False, "Anmeldung fehlgeschlagen – Benutzer/App-Passwort prüfen."
    return False, f"Unerwartete Antwort: HTTP {code}"


def _webdav_upload_one(entry, w):
    folder = (w.get("folder") or "").strip("/")
    rel_file = (folder + "/" + entry["file"]).strip("/")
    _dav_mkcol_path(w, os.path.dirname(rel_file))
    with open(os.path.join(ARCHIVE_DIR, entry["file"]), "rb") as f:
        _dav_put(w, rel_file, f.read())
    if os.path.exists(LEDGER_PATH):
        with open(LEDGER_PATH, "rb") as f:
            _dav_put(w, (folder + "/ledger.jsonl").strip("/"), f.read())
    return "nextcloud:" + rel_file


# ---- öffentliche API ----
def mirror_entry(entry, cfg):
    """Eine abgelegte PDF + Ledger in den konfigurierten Spiegel bringen."""
    w = _webdav_cfg(cfg)
    if w:
        return _webdav_upload_one(entry, w)
    base = (cfg or {}).get("archiv_spiegel")
    if not base:
        return None
    _copy_ro(os.path.join(ARCHIVE_DIR, entry["file"]),
             os.path.join(base, entry["file"]))
    os.makedirs(base, exist_ok=True)
    if os.path.exists(LEDGER_PATH):
        shutil.copy2(LEDGER_PATH, os.path.join(base, "ledger.jsonl"))
    return os.path.join(base, entry["file"])


def mirror_all(cfg):
    """Alle bisher abgelegten Dokumente + Ledger spiegeln. Anzahl zurück."""
    w = _webdav_cfg(cfg)
    entries = list_entries()
    n = 0
    if w:
        for e in entries:
            if os.path.exists(os.path.join(ARCHIVE_DIR, e["file"])):
                _webdav_upload_one(e, w)
                n += 1
        return n
    base = (cfg or {}).get("archiv_spiegel")
    if not base:
        return 0
    for e in entries:
        src = os.path.join(ARCHIVE_DIR, e["file"])
        if os.path.exists(src):
            _copy_ro(src, os.path.join(base, e["file"]))
            n += 1
    if os.path.exists(LEDGER_PATH):
        os.makedirs(base, exist_ok=True)
        shutil.copy2(LEDGER_PATH, os.path.join(base, "ledger.jsonl"))
    return n
