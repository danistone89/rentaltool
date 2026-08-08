#!/usr/bin/env python3
"""Betriebsdaten in einer SQLite-Datei statt in vielen JSON-Dateien.

Warum überhaupt? Die JSON-Dateien wurden bei jeder Änderung **komplett** neu
geschrieben. Das ist bei acht Zeiteinträgen egal und bei ein paar tausend nicht
mehr: jeder Klick schreibt die ganze Datei, und eine Auswertung über mehrere
Bestände (Zeiten × Buchungen × Belege) muss alles in den Speicher holen. Dazu
kommt, dass sich mehrere Dateien nicht gemeinsam ändern lassen – eine Zuweisung
löschen und die zugehörigen Zeiten entfernen war bisher zwei Schreibvorgänge
mit einer Lücke dazwischen.

**Der Datensatz bleibt ein Python-Dict.** Jede Zeile speichert den vollständigen
Satz als JSON in der Spalte `daten`; die Felder, nach denen gesucht oder
sortiert wird, hängen als **generierte Spalten** daran. Generiert heißt: SQLite
leitet sie aus `daten` ab, sie können also gar nicht auseinanderlaufen. Damit
bleibt der Code der Fachmodule so, wie er war (Dicts rein, Dicts raus), und
Auswertungen bekommen trotzdem echte Indizes.

Nicht hier drin:

* `config.json` – Konten und Zugangsdaten. Bleibt eine Datei, die man im Notfall
  mit einem Texteditor reparieren kann (`tools/useradmin.py` arbeitet darauf).
* `archive/ledger.jsonl` – die Hash-Kette der Steuerablage. Sie ist absichtlich
  eine anhängende Textdatei: revisionssicher heißt auch, dass ein Prüfer sie
  ohne unsere Software lesen kann.
* Fotos unter `media/` – Dateien bleiben Dateien.
"""
import json
import os
import sqlite3
import threading

from app import paths

DATEI = paths.p("rentaltool.db")
SCHEMA = 8      # 2: push_abos (AP7), 3: abwesenheiten (AP8),
                # 4: abschluesse (AP10), 5: meldungen (AP11),
                # 6: protokoll (AP12), 7: produkte+kreditoren (AP13),
                # 8: rechnungen (AP14)

# Tabelle -> generierte Spalten {Spaltenname: JSON-Pfad}. Die Spalten sind
# ableitbar und werden nie selbst geschrieben; sie existieren nur, damit man
# ohne Voll-Durchlauf filtern und sortieren kann.
TABELLEN = {
    "zeiten": {"benutzer": "$.user", "beginn": "$.checkin", "ende": "$.checkout",
               "buchung": "$.booking_id", "abgerechnet": "$.abgerechnet"},
    "zuweisungen": {"mitarbeiter": "$.assignee"},
    "belege": {"hochgeladen_von": "$.uploader", "erfasst": "$.ts",
               "wohnung": "$.apartment_id"},
    "checklisten": {},
    "bestand": {},
    "durchgaenge": {"wohnung": "$.apartment_id", "benutzer": "$.user",
                    "fertig": "$.finished"},
    "schaeden": {"wohnung": "$.apartment_id", "status": "$.status"},
    "nachkauf": {"wohnung": "$.apartment_id", "status": "$.status"},
    "push_abos": {"benutzer": "$.user", "endpunkt": "$.endpoint"},
    "abwesenheiten": {"benutzer": "$.user", "von": "$.von", "bis": "$.bis"},
    "abschluesse": {"monat": "$.monat"},
    "meldungen": {"periode": "$.periode"},
    "protokoll": {"wann": "$.ts", "wer": "$.wer", "was": "$.was"},
    "produkte": {"art": "$.art"},
    "kreditoren": {"kreditor": "$.name"},
    "rechnungen": {"nummer": "$.nummer", "buchung": "$.buchung",
                   "rstatus": "$.status", "rdatum": "$.datum"},
    # Kontobewegungen (AP16). Der Satzschlüssel ist der Fingerabdruck aus
    # `kontoauszug.schluessel` – damit ist ein zweiter Import derselben Wochen
    # ein Überschreiben desselben Satzes statt einer Dublette.
    "bewegungen": {"bdatum": "$.datum", "bkonto": "$.konto"},
    # Zuordnungen (B1). Eine Bewegung kann viele haben – eine Portal-Auszahlung
    # deckt mehrere Rechnungen ab und trägt den Provisionsbeleg dagegen.
    "zuordnungen": {"bewegung": "$.bewegung_id", "zart": "$.art",
                    "ziel": "$.ziel_id"},
}

_lokal = threading.local()


# ------------------------------------------------------------------ Verbindung
def _verbindung():
    """Verbindung dieses Threads (NiceGUI arbeitet mit Hintergrund-Threads).

    Eine sqlite3-Verbindung gehört genau einem Thread. Statt sie mit
    `check_same_thread=False` freizugeben – und sich um die Folgen selbst zu
    kümmern – bekommt jeder Thread seine eigene. Im WAL-Modus ist das
    ausdrücklich vorgesehen.
    """
    con = getattr(_lokal, "con", None)
    if con is not None and getattr(_lokal, "datei", None) == DATEI:
        return con
    if con is not None:
        con.close()
    os.makedirs(os.path.dirname(os.path.abspath(DATEI)) or ".", exist_ok=True)
    con = sqlite3.connect(DATEI, timeout=15, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")     # Lesen blockiert Schreiben nicht
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=15000")
    _lokal.con, _lokal.datei = con, DATEI
    anlegen_schema(con)
    return con


def zuruecksetzen():
    """Verbindung dieses Threads schließen – nach einem Wechsel von `DATEI`."""
    con = getattr(_lokal, "con", None)
    if con is not None:
        con.close()
    _lokal.con = None
    _lokal.datei = None


def anlegen_schema(con=None):
    con = con or _verbindung()
    for tabelle, spalten in TABELLEN.items():
        erzeugt = "".join(
            f",\n  {name} GENERATED ALWAYS AS (json_extract(daten, '{pfad}')) VIRTUAL"
            for name, pfad in spalten.items())
        con.execute(f"CREATE TABLE IF NOT EXISTS {tabelle} (\n"
                    f"  id TEXT PRIMARY KEY,\n"
                    f"  daten TEXT NOT NULL{erzeugt}\n)")
        for name in spalten:
            con.execute(f"CREATE INDEX IF NOT EXISTS i_{tabelle}_{name} "
                        f"ON {tabelle}({name})")
    con.execute(f"PRAGMA user_version={SCHEMA}")
    return con


class transaktion:
    """Mehrere Änderungen gemeinsam – oder gar nicht.

        with db.transaktion():
            db.loeschen("zuweisungen", bid)
            for e in db.finden("zeiten", buchung=bid):
                db.loeschen("zeiten", e["id"])

    Schachtelt sich selbst: die innere Verwendung öffnet keine zweite
    Transaktion, sonst würde ein `COMMIT` in der Mitte alles vorzeitig
    festschreiben.
    """

    def __enter__(self):
        con = _verbindung()
        self.aeussere = getattr(_lokal, "in_transaktion", False)
        if not self.aeussere:
            # IMMEDIATE: der Schreibplatz wird sofort reserviert. Sonst merkt
            # SQLite erst beim Schreiben, dass ein anderer schneller war, und
            # bricht mitten in der Änderung ab.
            con.execute("BEGIN IMMEDIATE")
            _lokal.in_transaktion = True
        return con

    def __exit__(self, art, wert, spur):
        if self.aeussere:
            return False
        con = _verbindung()
        _lokal.in_transaktion = False
        con.execute("ROLLBACK" if art else "COMMIT")
        return False


# ------------------------------------------------------------------ Lesen
def _satz(zeile):
    return json.loads(zeile["daten"])


def alle(tabelle, neueste_zuerst=False):
    """Alle Sätze in Anlegereihenfolge (rowid) – wie bisher die Liste in der Datei."""
    con = _verbindung()
    ordnung = "DESC" if neueste_zuerst else "ASC"
    return [_satz(z) for z in con.execute(
        f"SELECT daten FROM {tabelle} ORDER BY rowid {ordnung}")]


def als_dict(tabelle):
    """{id: satz} – für Bestände, die als Zuordnung geführt werden."""
    con = _verbindung()
    return {z["id"]: _satz(z) for z in con.execute(f"SELECT id, daten FROM {tabelle}")}


def holen(tabelle, sid):
    con = _verbindung()
    z = con.execute(f"SELECT daten FROM {tabelle} WHERE id = ?", (str(sid),)).fetchone()
    return _satz(z) if z else None


def finden(tabelle, neueste_zuerst=False, **bedingungen):
    """Nach den generierten Spalten filtern, z. B. `finden("zeiten", benutzer="vale")`."""
    spalten = TABELLEN[tabelle]
    for name in bedingungen:
        if name not in spalten:
            raise KeyError(f"{tabelle} hat keine Spalte {name} "
                           f"(vorhanden: {', '.join(spalten) or 'keine'})")
    # `None` heißt „Feld ist leer" (z. B. ein Zeiteintrag ohne Check-out) und
    # wird zu `IS NULL` – ohne Platzhalter, sonst passt die Anzahl nicht.
    wo = " AND ".join(f"{n} IS NULL" if w is None else f"{n} = ?"
                      for n, w in bedingungen.items())
    werte = [w for w in bedingungen.values() if w is not None]
    ordnung = "DESC" if neueste_zuerst else "ASC"
    con = _verbindung()
    return [_satz(z) for z in con.execute(
        f"SELECT daten FROM {tabelle}" + (f" WHERE {wo}" if wo else "")
        + f" ORDER BY rowid {ordnung}", werte)]


def anzahl(tabelle):
    return _verbindung().execute(f"SELECT COUNT(*) c FROM {tabelle}").fetchone()["c"]


# ------------------------------------------------------------------ Schreiben
def anlegen(tabelle, satz, sid=None):
    """Neuen Satz anhängen. `sid` sonst aus satz["id"]."""
    sid = str(sid if sid is not None else satz["id"])
    _verbindung().execute(f"INSERT INTO {tabelle} (id, daten) VALUES (?, ?)",
                          (sid, json.dumps(satz, ensure_ascii=False)))
    return satz


def speichern(tabelle, sid, satz):
    """Satz schreiben – vorhandenen ändern, sonst anhängen.

    Bewusst UPDATE statt `INSERT OR REPLACE`: letzteres löscht die Zeile und legt
    sie neu an, damit bekäme sie eine neue rowid und würde in der Liste ans Ende
    springen. Die Reihenfolge ist aber sichtbar (neueste Zeiten zuerst).
    """
    con = _verbindung()
    roh = json.dumps(satz, ensure_ascii=False)
    if con.execute(f"UPDATE {tabelle} SET daten = ? WHERE id = ?",
                   (roh, str(sid))).rowcount == 0:
        con.execute(f"INSERT INTO {tabelle} (id, daten) VALUES (?, ?)", (str(sid), roh))
    return satz


def loeschen(tabelle, sid):
    return _verbindung().execute(f"DELETE FROM {tabelle} WHERE id = ?",
                                 (str(sid),)).rowcount > 0


def leeren(tabelle):
    _verbindung().execute(f"DELETE FROM {tabelle}")


# ------------------------------------------------------------------ Betrieb
def pruefen():
    """(ok, meldung) – Selbsttest der Datei, für Wächter und Sicherung."""
    try:
        con = _verbindung()
        ergebnis = con.execute("PRAGMA integrity_check").fetchone()[0]
        if ergebnis != "ok":
            return False, f"integrity_check: {ergebnis}"
        stand = {t: anzahl(t) for t in TABELLEN}
        return True, ", ".join(f"{t}: {n}" for t, n in stand.items() if n)
    except sqlite3.Error as ex:
        return False, f"{type(ex).__name__}: {ex}"


def sichern_nach(zieldatei):
    """Sauberen Abzug der Datenbank schreiben (auch während des Betriebs).

    Eine WAL-Datenbank besteht aus mehreren Dateien; sie einfach zu kopieren kann
    einen Stand ergeben, der so nie existiert hat. `VACUUM INTO` erzeugt einen in
    sich stimmigen Abzug.
    """
    if os.path.exists(zieldatei):
        os.remove(zieldatei)
    _verbindung().execute("VACUUM INTO ?", (zieldatei,))
    return zieldatei
