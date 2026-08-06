#!/usr/bin/env python3
"""Tägliche Sicherung des Datenbestands auf die Nextcloud.

    python3 tools/backup.py sichern     # Paket bauen, prüfen, hochladen, aufräumen
    python3 tools/backup.py pruefen     # jüngste Sicherung HERUNTERLADEN und probeweise
                                        # wiederherstellen – die einzige ehrliche Prüfung
    python3 tools/backup.py liste       # was liegt am Ziel?

Ziel kommt aus `config.json` → `backup_ziel`. Zwei Formen:

  * `nextcloud:Pfad/im/Cloud-Konto`  – direkt über rclone (empfohlen auf dem Server).
    Geht am FUSE-Mount vorbei: rclone prüft die Prüfsumme nach dem Hochladen,
    der Mount tut das nicht.
  * `/ein/lokaler/Ordner`            – für Tests und lokale Installationen.

Gesichert wird der Datenordner (app/paths.DATA_DIR), also Konten, Arbeitszeiten,
Belege, Reinigungsdaten, Fotos und das revisionssichere Steuerarchiv. Nicht
gesichert werden Programmcode (steht im Git) und `.nicegui/` (nur Sitzungen).

Die Datenbank wird **nicht einfach mitkopiert**: eine laufende SQLite-Datenbank
besteht aus mehreren Dateien (WAL), und ein Dateikopie-Schnappschuss davon kann
einen Stand ergeben, den es nie gab. Stattdessen schreibt `db.sichern_nach()`
einen in sich stimmigen Abzug, und der kommt ins Paket.

Scheitert etwas, geht eine Mail an den Benachrichtigungs-Empfänger und der
Exit-Code ist ungleich 0 – daran hängt die systemd-Meldung.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import paths  # noqa: E402

PRAEFIX = "rentaltool-"
ENDUNG = ".tar.gz"
STATUS = "backup-status.json"

# Aufbewahrung: die 14 jüngsten Stände, dazu die letzten 8 Sonntage und die
# letzten 12 Monatsersten. Bewusst „die 14 jüngsten“ und nicht „alles der letzten
# 14 Tage“: bleibt die Sicherung mal zwei Wochen aus, wären nach der zweiten
# Lesart beim nächsten Lauf fast alle Stände auf einen Schlag fällig.
TAEGLICH, WOECHENTLICH, MONATLICH = 14, 8, 12

# Nichts davon gehört in die Sicherung: Sitzungsdateien (~80 MB, wertlos),
# Python-Reste, und der Statusbericht der Sicherung selbst.
AUS = {".nicegui", "__pycache__", ".venv", ".git", STATUS}


# ------------------------------------------------------------------ Namen/Datum
def name_fuer(tag):
    return f"{PRAEFIX}{tag.isoformat()}{ENDUNG}"


def datum_aus(name):
    """date oder None – tolerant, damit fremde Dateien am Ziel nicht stören."""
    if not (name.startswith(PRAEFIX) and name.endswith(ENDUNG)):
        return None
    try:
        return date.fromisoformat(name[len(PRAEFIX):-len(ENDUNG)])
    except ValueError:
        return None


def behalten(namen):
    """(behalten, loeschen) nach der Aufbewahrungsregel.

    Bewusst als reine Funktion: das ist der Teil, der bei einem Denkfehler
    stillschweigend die Historie wegräumt – der gehört getestet, nicht geglaubt.
    """
    datiert = sorted(((datum_aus(n), n) for n in namen if datum_aus(n)), reverse=True)
    keep = set()
    for d, n in datiert[:TAEGLICH]:
        keep.add(n)
    for d, n in [x for x in datiert if x[0].weekday() == 6][:WOECHENTLICH]:
        keep.add(n)
    for d, n in [x for x in datiert if x[0].day == 1][:MONATLICH]:
        keep.add(n)
    # Alles ohne erkennbares Datum bleibt liegen – das ist nicht unseres.
    loeschen = [n for _d, n in datiert if n not in keep]
    return sorted(keep), sorted(loeschen)


# ------------------------------------------------------------------ Ziel (rclone/lokal)
def ist_rclone(ziel):
    """`remote:pfad` ist rclone, `/pfad` und `C:\\pfad` nicht."""
    kopf = ziel.split(":", 1)[0]
    return ":" in ziel and len(kopf) > 1 and not ziel.startswith("/")


def _rclone(*args):
    r = subprocess.run(["rclone", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"rclone {' '.join(args[:2])}: {r.stderr.strip()[:300]}")
    return r.stdout


def vorhandene(ziel):
    if ist_rclone(ziel):
        return [z.strip("/") for z in _rclone("lsf", ziel).splitlines() if z.strip()]
    return sorted(os.listdir(ziel)) if os.path.isdir(ziel) else []


def hochladen(lokal, ziel, name):
    if ist_rclone(ziel):
        # copyto prüft nach dem Übertragen die Prüfsumme.
        _rclone("copyto", lokal, f"{ziel.rstrip('/')}/{name}")
    else:
        os.makedirs(ziel, exist_ok=True)
        shutil.copy2(lokal, os.path.join(ziel, name))


def herunterladen(ziel, name, nach):
    if ist_rclone(ziel):
        _rclone("copyto", f"{ziel.rstrip('/')}/{name}", nach)
    else:
        shutil.copy2(os.path.join(ziel, name), nach)


def entfernen(ziel, name):
    if ist_rclone(ziel):
        _rclone("deletefile", f"{ziel.rstrip('/')}/{name}")
    else:
        os.remove(os.path.join(ziel, name))


# ------------------------------------------------------------------ Paket bauen/prüfen
def json_defekt(ordner):
    """Namen der Dateien, die sich nicht lesen lassen (JSON und Datenbank).

    Bricht die Sicherung NICHT ab: eine kaputte Datei ist der Grund, warum man
    Sicherungen hat. Sie wird gemeldet und mitgesichert.
    """
    kaputt = []
    for name in paths.DATEIEN + paths.ALTE_JSON:
        pfad = os.path.join(ordner, name)
        if not os.path.exists(pfad):
            continue
        if name.endswith(".db"):
            ok, meldung = _db_pruefen(pfad)
            if not ok:
                kaputt.append(f"{name}: {meldung}")
            continue
        try:
            with open(pfad, encoding="utf-8") as f:
                json.load(f)
        except Exception as ex:
            kaputt.append(f"{name}: {ex}")
    return kaputt


def _db_pruefen(pfad):
    """(ok, meldung) – Selbsttest einer Datenbankdatei, ohne sie zu verändern."""
    import sqlite3
    try:
        con = sqlite3.connect(f"file:{pfad}?mode=ro", uri=True, timeout=10)
        try:
            ergebnis = con.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            con.close()
        return (ergebnis == "ok"), ergebnis
    except sqlite3.Error as ex:
        return False, f"{type(ex).__name__}: {ex}"


def _filter(ti):
    teile = set(ti.name.split("/"))
    return None if teile & AUS else ti


def paket_bauen(ordner, zieldatei, abzug=None):
    """tar.gz des Datenordners. Gibt die Größe in Bytes zurück.

    `abzug`: Pfad eines sauberen Datenbank-Abzugs, der anstelle der laufenden
    Datei ins Paket kommt (siehe Kopf).
    """
    with tarfile.open(zieldatei, "w:gz") as tar:
        for name in paths.DATEIEN + paths.ALTE_JSON + paths.ORDNER:
            if name.endswith(".db") and abzug:
                tar.add(abzug, arcname=name)
                continue
            pfad = os.path.join(ordner, name)
            if os.path.exists(pfad):
                tar.add(pfad, arcname=name, filter=_filter)
    return os.path.getsize(zieldatei)


def _entpacken(tarpfad, nach):
    with tarfile.open(tarpfad, "r:gz") as tar:
        try:
            tar.extractall(nach, filter="data")      # Python ≥ 3.12
        except TypeError:
            tar.extractall(nach)


def paket_pruefen(tarpfad):
    """Paket auspacken und den Inhalt wirklich lesen.

    Prüft drei Dinge, die ein „tar hat 0 zurückgegeben" nicht abdeckt:
    lässt sich jede JSON-Datei parsen, sind Konten enthalten, und ist die
    Hash-Kette des Steuerarchivs unversehrt. Liefert (ok, [Meldungen]).
    """
    meldungen = []
    with tempfile.TemporaryDirectory() as tmp:
        _entpacken(tarpfad, tmp)
        for m in json_defekt(tmp):
            meldungen.append(f"defekt im Paket – {m}")
        cfg = os.path.join(tmp, "config.json")
        if not os.path.exists(cfg):
            meldungen.append("config.json fehlt im Paket")
        else:
            with open(cfg, encoding="utf-8") as f:
                konten = ((json.load(f).get("auth") or {}).get("users") or {})
            if not konten:
                meldungen.append("keine Benutzerkonten im Paket")
        datenbank = os.path.join(tmp, "rentaltool.db")
        if os.path.exists(datenbank):
            ok, meldung = _db_pruefen(datenbank)
            if not ok:
                meldungen.append(f"Datenbank im Paket: {meldung}")
        if os.path.isdir(os.path.join(tmp, "archive")):
            meldungen += _archiv_pruefen(tmp)
    return not meldungen, meldungen


def _archiv_pruefen(datenordner):
    """Hash-Kette des Steuerarchivs im ausgepackten Paket prüfen.

    Als eigener Prozess, weil app.archive seine Pfade beim Import festlegt –
    im laufenden Prozess zeigten sie auf den echten Datenordner.
    """
    code = ("from app import archive;"
            "ok, res = archive.verify();"
            "print('OK' if ok else 'FEHLER: ' + '; '.join("
            "f\"{e['period']} v{e['revision']}: {', '.join(e['issues'])}\""
            " for e in res if not e['ok']))")
    r = subprocess.run([sys.executable, "-c", code], cwd=paths.ROOT, text=True,
                       capture_output=True,
                       env={**os.environ, "RENTALTOOL_DATA": datenordner})
    if r.returncode != 0:
        return [f"Archivprüfung nicht möglich: {r.stderr.strip()[:200]}"]
    aus = r.stdout.strip()
    return [] if aus == "OK" else [f"Steuerarchiv: {aus}"]


# ------------------------------------------------------------------ Status & Meldung
def status_schreiben(ergebnis):
    pfad = paths.p(STATUS)
    tmp = pfad + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(ergebnis, f, ensure_ascii=False, indent=1)
    os.replace(tmp, pfad)


def melden(betreff, text):
    """Fehlermeldung per Mail – best effort, darf die Sicherung nicht sprengen."""
    try:
        from app import data, mailer
        empf = ((data.CONFIG.get("notify_email") or {}).get("absender")
                or (data.CONFIG.get("email") or {}).get("absender") or "")
        if empf:
            mailer.send_notify(data.CONFIG, empf, betreff, text)
            return True
    except Exception as ex:
        print(f"   (Meldung konnte nicht gesendet werden: {ex})")
    return False


def _ziel_aus_config():
    try:
        from app import data
        return (data.CONFIG.get("backup_ziel") or "").strip()
    except Exception:
        return ""


# ------------------------------------------------------------------ Befehle
def cmd_sichern(args):
    ziel = args.ziel or _ziel_aus_config()
    if not ziel:
        print("Kein Sicherungsziel. In config.json `backup_ziel` setzen, z. B.\n"
              '  "backup_ziel": "nextcloud:03 Immobilien/.../Backups/rentaltool"')
        return 2

    start = datetime.now()
    ordner = paths.DATA_DIR
    name = name_fuer(date.today())
    print(f"Datenordner: {ordner}")
    print(f"Ziel:        {ziel}")

    warnungen = json_defekt(ordner)
    for w in warnungen:
        print(f"   ! {w}")

    with tempfile.TemporaryDirectory() as tmp:
        lokal = os.path.join(tmp, name)
        abzug = None
        if os.path.exists(os.path.join(ordner, "rentaltool.db")):
            from app import db
            abzug = db.sichern_nach(os.path.join(tmp, "abzug.db"))
        groesse = paket_bauen(ordner, lokal, abzug=abzug)
        print(f"   Paket gebaut: {groesse / 1024 / 1024:.1f} MB")

        ok, meldungen = paket_pruefen(lokal)
        for m in meldungen:
            print(f"   ! {m}")
        if not ok:
            fehler = "Sicherung abgebrochen – das Paket ist nicht in Ordnung:\n\n" \
                     + "\n".join(f"· {m}" for m in meldungen)
            status_schreiben({"zeit": start.isoformat(timespec="seconds"), "ok": False,
                              "ziel": ziel, "fehler": meldungen})
            print(fehler)
            melden("Sicherung FEHLGESCHLAGEN – rentaltool", fehler)
            return 1
        print("   Paket geprüft: JSON lesbar, Konten vorhanden, Archivkette heil")

        hochladen(lokal, ziel, name)
        print(f"   Hochgeladen: {name}")

    da = vorhandene(ziel)
    if name not in da:
        fehler = f"Nach dem Hochladen liegt {name} nicht am Ziel."
        status_schreiben({"zeit": start.isoformat(timespec="seconds"), "ok": False,
                          "ziel": ziel, "fehler": [fehler]})
        melden("Sicherung FEHLGESCHLAGEN – rentaltool", fehler)
        print(f"   ! {fehler}")
        return 1

    _keep, weg = behalten(da)
    for alt in weg:
        entfernen(ziel, alt)
    if weg:
        print(f"   Aufgeräumt: {len(weg)} alte Sicherung(en) entfernt")

    status_schreiben({"zeit": start.isoformat(timespec="seconds"), "ok": True,
                      "ziel": ziel, "datei": name, "bytes": groesse,
                      "sicherungen": len(da) - len(weg),
                      "warnungen": warnungen,
                      "dauer_s": int((datetime.now() - start).total_seconds())})
    if warnungen:
        melden("Sicherung ok, aber mit Warnung – rentaltool",
               "Die Sicherung lief durch. Diese Dateien sind aber defekt:\n\n"
               + "\n".join(f"· {w}" for w in warnungen))
    print(f"Fertig in {int((datetime.now() - start).total_seconds())} s · "
          f"{len(da) - len(weg)} Sicherung(en) am Ziel")
    return 0


def cmd_pruefen(args):
    """Wiederherstellung üben: jüngstes Paket holen, auspacken, Inhalt lesen."""
    ziel = args.ziel or _ziel_aus_config()
    da = [n for n in vorhandene(ziel) if datum_aus(n)]
    if not da:
        print(f"Keine Sicherung am Ziel {ziel}.")
        return 1
    name = sorted(da)[-1]
    print(f"Prüfe {name} von {ziel} …")
    with tempfile.TemporaryDirectory() as tmp:
        lokal = os.path.join(tmp, name)
        herunterladen(ziel, name, lokal)
        print(f"   heruntergeladen: {os.path.getsize(lokal) / 1024 / 1024:.1f} MB")
        ok, meldungen = paket_pruefen(lokal)
        ausgepackt = os.path.join(tmp, "wiederhergestellt")
        _entpacken(lokal, ausgepackt)
        inhalt = sorted(os.listdir(ausgepackt))
        print(f"   ausgepackt: {', '.join(inhalt)}")
    for m in meldungen:
        print(f"   ! {m}")
    print("Ergebnis: " + ("wiederherstellbar ✓" if ok else "NICHT in Ordnung ✗"))
    return 0 if ok else 1


def cmd_liste(args):
    ziel = args.ziel or _ziel_aus_config()
    da = vorhandene(ziel)
    datiert = sorted((n for n in da if datum_aus(n)), reverse=True)
    keep, weg = behalten(da)
    print(f"Ziel: {ziel}  ({len(datiert)} Sicherung(en))")
    for n in datiert:
        print(f"   {n}{'' if n in keep else '   (fällig zum Aufräumen)'}")
    if weg:
        print(f"\n{len(weg)} würde die nächste Sicherung entfernen.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("befehl", nargs="?", default="sichern",
                    choices=["sichern", "pruefen", "liste"])
    ap.add_argument("--ziel", default="", help="überschreibt config.backup_ziel")
    args = ap.parse_args(argv)
    try:
        return {"sichern": cmd_sichern, "pruefen": cmd_pruefen,
                "liste": cmd_liste}[args.befehl](args)
    except Exception as ex:
        print(f"FEHLER: {ex}")
        if args.befehl == "sichern":
            status_schreiben({"zeit": datetime.now().isoformat(timespec="seconds"),
                              "ok": False, "fehler": [str(ex)]})
            melden("Sicherung FEHLGESCHLAGEN – rentaltool",
                   f"Die tägliche Sicherung ist abgebrochen:\n\n{ex}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
