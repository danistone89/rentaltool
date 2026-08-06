#!/usr/bin/env python3
"""Probe-Instanz mit einer Kopie der echten Daten auffrischen.

    python3 tools/staging_refresh.py                       # Probelauf
    python3 tools/staging_refresh.py --jetzt                # wirklich kopieren

Auf einer Probe-Instanz will man mit **echten** Daten arbeiten – nur so fällt
auf, was mit zwei Buchungen am selben Tag oder mit 300 Zeiteinträgen passiert.
Genau das macht sie aber gefährlich: echte Gäste, echte Mitarbeiter, echte
E-Mail-Adressen.

Beim Kopieren werden deshalb alle Wege nach draußen aus der Konfiguration
entfernt. Zusätzlich blockiert `app/mode.py` diese Wege im Code – wer die
Konfiguration von Hand wieder füllt, kommt trotzdem nicht raus.

Die **Zugangsdaten der Benutzer bleiben**: man will sich mit dem eigenen
Passwort anmelden können. Wer das nicht will, nimmt `--ohne-konten`.
"""
import argparse
import json
import os
import shutil
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import paths  # noqa: E402

ECHT = "/var/lib/rentaltool"
PROBE = "/var/lib/rentaltool-staging"
PROBE_URL = "http://127.0.0.1:3002"


def entschaerfen(cfg, url=PROBE_URL, konten=True):
    """Alle Wege nach draußen aus der Konfiguration nehmen.

    Reine Funktion – damit im Test nachweisbar ist, dass nichts übrig bleibt.
    """
    cfg = json.loads(json.dumps(cfg))          # tiefe Kopie

    # Mailversand: ohne App-Passwort geht bei Gmail nichts raus.
    for schluessel in ("email", "notify_email"):
        if isinstance(cfg.get(schluessel), dict):
            cfg[schluessel]["app_password"] = ""

    # Spiegel in die echte Nextcloud-Buchhaltung.
    for schluessel in ("archiv_spiegel", "belege_ordner", "reinigung_ordner"):
        cfg[schluessel] = ""
    cfg["archiv_webdav"] = {}

    # Das Sicherungsziel MUSS weg: sonst überschriebe eine Sicherung der
    # Probe-Instanz die echten Sicherungen am selben Ort.
    cfg["backup_ziel"] = ""

    # Links in Mails/Einladungen zeigen sonst auf den Echtbetrieb.
    cfg["app_url"] = url
    cfg["port"] = 3002

    if not konten:
        cfg.setdefault("auth", {})["users"] = {}
    return cfg


def _leeren(ordner):
    for name in os.listdir(ordner):
        pfad = os.path.join(ordner, name)
        if os.path.isdir(pfad):
            shutil.rmtree(pfad)
        else:
            os.remove(pfad)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--echt", default=ECHT, help=f"Quelle (Vorgabe {ECHT})")
    ap.add_argument("--probe", default=PROBE, help=f"Ziel (Vorgabe {PROBE})")
    ap.add_argument("--url", default=PROBE_URL)
    ap.add_argument("--ohne-konten", action="store_true",
                    help="Benutzerkonten nicht mitkopieren")
    ap.add_argument("--jetzt", action="store_true", help="wirklich kopieren")
    args = ap.parse_args(argv)

    echt, probe = os.path.abspath(args.echt), os.path.abspath(args.probe)
    if echt == probe:
        print("Quelle und Ziel sind derselbe Ordner – das wäre der Echtbetrieb.")
        return 1
    if not os.path.isdir(echt):
        print(f"Quelle {echt} gibt es nicht.")
        return 1

    quellen = [n for n in paths.DATEIEN + paths.ORDNER
               if os.path.exists(os.path.join(echt, n))]
    print(f"Quelle: {echt}")
    print(f"Ziel:   {probe}   (wird VORHER geleert)")
    for n in quellen:
        print(f"   → {n}")
    print("\nEntschärft wird: Mail-App-Passwörter, Spiegel-Ordner, WebDAV, "
          "Sicherungsziel, App-Adresse, Port"
          + (", Benutzerkonten" if args.ohne_konten else ""))
    if not args.jetzt:
        print("\nProbelauf – nichts verändert. Mit --jetzt wirklich kopieren.")
        return 0

    os.makedirs(probe, exist_ok=True)
    _leeren(probe)
    for n in quellen:
        q = os.path.join(echt, n)
        z = os.path.join(probe, n)
        if os.path.isdir(q):
            shutil.copytree(q, z)
        elif n.endswith(".db"):
            # Eine laufende SQLite-Datenbank besteht aus mehreren Dateien; eine
            # Dateikopie kann einen Stand ergeben, den es nie gab.
            con = sqlite3.connect(f"file:{q}?mode=ro", uri=True, timeout=15)
            try:
                con.execute("VACUUM INTO ?", (z,))
            finally:
                con.close()
        else:
            shutil.copy2(q, z)
        print(f"   kopiert: {n}")

    cfg_pfad = os.path.join(probe, "config.json")
    with open(cfg_pfad, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg = entschaerfen(cfg, url=args.url, konten=not args.ohne_konten)
    tmp = cfg_pfad + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, cfg_pfad)
    print("   entschärft: config.json")
    print(f"\nFertig. Probe-Instanz neu starten:\n"
          f"  systemctl restart rentaltool-staging")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
