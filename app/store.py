#!/usr/bin/env python3
"""Ein Weg für allen Dateizugriff: atomar schreiben, gesperrt ändern.

Vorher machte jedes Modul „ganze Datei lesen → im Speicher ändern → ganze Datei
überschreiben". Zwei Fehler stecken darin:

1. **Nicht atomar.** `open(pfad, "w")` kürzt die Datei sofort auf 0 Bytes. Wer in
   diesem Moment abstürzt (oder dessen Platte volläuft), hinterlässt eine leere
   oder halbe Datei. Bei `config.json` hieße das: alle Konten weg. Hier wird
   deshalb in eine Nachbardatei geschrieben, auf die Platte gezwungen und erst
   dann per `os.replace` umgehängt – ein Schritt, den das Dateisystem entweder
   ganz oder gar nicht macht.

2. **Nicht gesperrt.** Zwischen Lesen und Zurückschreiben liegt eine Lücke.
   Schreibt in dieser Lücke jemand anders, ist dessen Änderung beim
   Zurückschreiben still verloren. `edit()` hält die Sperre über die ganze
   Änderung.

Wer sperrt hier gegen wen? Die App ist ein einzelner Prozess, aber daneben
laufen `tools/useradmin.py`, `tools/backup.py` und Handgriffe auf dem Server –
und innerhalb der App auch Hintergrund-Threads (`run.io_bound`). Genau diese
Überschneidungen fängt die Sperre ab.

Gesperrt wird über eine Beidatei `<name>.lock`, nicht über die Datei selbst:
`os.replace` hängt eine **neue** Datei an den Namen, eine Sperre auf der alten
wäre danach wertlos.
"""
import errno
import json
import os
import threading
import time
from contextlib import contextmanager

try:
    import fcntl                      # POSIX (macOS, Linux)
except ImportError:                   # pragma: no cover - Windows
    fcntl = None

# Wartezeit auf eine fremde Sperre. Lieber ein klarer Fehler als eine Oberfläche,
# die ohne Erklärung stehenbleibt.
TIMEOUT_S = 10.0

_lokal = threading.local()


class SperrFehler(RuntimeError):
    """Datei war zu lange von jemand anderem gesperrt."""


class DatenFehler(RuntimeError):
    """Datei existiert, ist aber nicht lesbar (kaputtes JSON)."""


def _gehaltene():
    d = getattr(_lokal, "gehalten", None)
    if d is None:
        d = _lokal.gehalten = {}
    return d


@contextmanager
def sperre(pfad, timeout=TIMEOUT_S):
    """Exklusive Sperre auf eine Datei (über `<pfad>.lock`).

    Im selben Thread mehrfach betretbar: `set_task_ref_photo` liest über
    `get_checklist` und schreibt über `save_checklist` – schachtelt das jemand
    später ineinander, soll es nicht verklemmen.
    """
    schluessel = os.path.abspath(pfad)
    gehalten = _gehaltene()
    if gehalten.get(schluessel):
        gehalten[schluessel] += 1
        try:
            yield
        finally:
            gehalten[schluessel] -= 1
        return

    if fcntl is None:                 # pragma: no cover - Windows
        gehalten[schluessel] = 1
        try:
            yield
        finally:
            gehalten.pop(schluessel, None)
        return

    os.makedirs(os.path.dirname(schluessel) or ".", exist_ok=True)
    fd = os.open(schluessel + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    ende = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as ex:
                if ex.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if time.monotonic() >= ende:
                    raise SperrFehler(
                        f"{os.path.basename(pfad)} ist seit {timeout:.0f} s von einem "
                        f"anderen Vorgang gesperrt.")
                time.sleep(0.05)
        gehalten[schluessel] = 1
        try:
            yield
        finally:
            gehalten.pop(schluessel, None)
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _lesen(pfad, vorgabe):
    if not os.path.exists(pfad):
        return vorgabe
    try:
        with open(pfad, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as ex:
        # Bewusst KEIN stiller Rückfall auf die Vorgabe: der nächste Schreibvorgang
        # würde den (noch vorhandenen) Bestand mit einer leeren Liste überschreiben
        # und aus einer lesbaren Panne einen Datenverlust machen.
        raise DatenFehler(f"{pfad} ist nicht lesbar: {ex}. Letzte Sicherung "
                          f"einspielen (tools/backup.py pruefen).") from ex


def _schreiben(pfad, obj, indent=1):
    ordner = os.path.dirname(os.path.abspath(pfad))
    os.makedirs(ordner, exist_ok=True)
    tmp = f"{pfad}.tmp-{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=indent)
            f.flush()
            os.fsync(f.fileno())      # sonst steht der Inhalt nur im Cache
        os.replace(tmp, pfad)
    except BaseException:
        # Nicht serialisierbar, Platte voll, Abbruch: die alte Datei ist
        # unangetastet – nur der Rest der Nachbardatei muss weg.
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    try:                              # Umbenennen selbst dauerhaft machen
        d = os.open(ordner, os.O_RDONLY)
        try:
            os.fsync(d)
        finally:
            os.close(d)
    except OSError:                   # pragma: no cover - z. B. Netzlaufwerk
        pass


def read(pfad, vorgabe=None):
    """JSON lesen. Fehlt die Datei, kommt die Vorgabe."""
    with sperre(pfad):
        return _lesen(pfad, vorgabe)


def write(pfad, obj, indent=1):
    """JSON atomar schreiben."""
    with sperre(pfad):
        _schreiben(pfad, obj, indent)


class Aenderung:
    """Der Datenstand innerhalb von `edit()`.

    `wert` ändern und den Block verlassen genügt – geschrieben wird beim
    Verlassen. `verwerfen()` für die Fälle, in denen sich nichts geändert hat.
    """

    __slots__ = ("wert", "speichern")

    def __init__(self, wert):
        self.wert = wert
        self.speichern = True

    def verwerfen(self):
        self.speichern = False


@contextmanager
def edit(pfad, vorgabe=None, indent=1):
    """Lesen, ändern, zurückschreiben – unter durchgehender Sperre.

        with store.edit(LOG, []) as a:
            a.wert.append(eintrag)

    Fliegt im Block eine Ausnahme, wird nichts geschrieben.
    """
    with sperre(pfad):
        a = Aenderung(_lesen(pfad, vorgabe))
        yield a
        if a.speichern:
            _schreiben(pfad, a.wert, indent)
