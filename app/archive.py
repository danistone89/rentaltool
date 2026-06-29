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
import hashlib
import json
import os
from datetime import datetime

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
