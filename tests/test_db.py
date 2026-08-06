"""Datenschicht und die einmalige Übernahme aus den JSON-Dateien.

Die Übernahme läuft genau einmal über echte Betriebsdaten – Arbeitszeiten sind
Lohnbelege, Belege sind Buchhaltung. Deshalb wird hier nicht nur geprüft, dass
sie „durchläuft", sondern dass jeder Satz **unverändert** und in derselben
Reihenfolge zurückkommt.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import bookings, db, housekeeping, receipts, timetrack  # noqa: E402
from tools import migrate_db  # noqa: E402


# ------------------------------------------------------------ Datenschicht
def test_reihenfolge_bleibt_beim_aendern_erhalten():
    """„Neueste zuerst" hängt an der Anlegereihenfolge. Ein Satz, der geändert
    wird, darf deshalb nicht ans Ende springen – genau das täte ein
    INSERT OR REPLACE."""
    for i in range(3):
        db.anlegen("zeiten", {"id": f"e{i}", "user": "vale", "checkin": f"2026-08-0{i+1}"})
    satz = db.holen("zeiten", "e0")
    satz["apartment"] = "Cottaer"
    db.speichern("zeiten", "e0", satz)
    assert [s["id"] for s in db.alle("zeiten")] == ["e0", "e1", "e2"]


def test_finden_ueber_generierte_spalten():
    db.anlegen("zeiten", {"id": "a", "user": "vale", "checkout": None})
    db.anlegen("zeiten", {"id": "b", "user": "vale", "checkout": "2026-08-05T10:00:00"})
    db.anlegen("zeiten", {"id": "c", "user": "gabriel", "checkout": None})
    assert [s["id"] for s in db.finden("zeiten", benutzer="vale")] == ["a", "b"]
    assert [s["id"] for s in db.finden("zeiten", ende=None)] == ["a", "c"]
    assert [s["id"] for s in db.finden("zeiten", benutzer="vale", ende=None)] == ["a"]


def test_generierte_spalte_folgt_dem_inhalt():
    """Die Spalten sind abgeleitet und können deshalb gar nicht veralten."""
    db.anlegen("zeiten", {"id": "a", "user": "vale", "checkout": None})
    assert len(db.finden("zeiten", ende=None)) == 1
    satz = db.holen("zeiten", "a")
    satz["checkout"] = "2026-08-05T10:00:00"
    db.speichern("zeiten", "a", satz)
    assert db.finden("zeiten", ende=None) == []


def test_transaktion_nimmt_bei_fehler_alles_zurueck():
    db.anlegen("zeiten", {"id": "a", "user": "vale"})
    with pytest.raises(ValueError):
        with db.transaktion():
            db.anlegen("zeiten", {"id": "b", "user": "vale"})
            db.loeschen("zeiten", "a")
            raise ValueError("mittendrin schiefgegangen")
    assert [s["id"] for s in db.alle("zeiten")] == ["a"]


def test_geschachtelte_transaktion_schreibt_nicht_vorzeitig_fest():
    """Innen liegende Aufrufe (get_open_run in start_run) dürfen die äußere
    Klammer nicht aufbrechen."""
    with pytest.raises(ValueError):
        with db.transaktion():
            db.anlegen("zeiten", {"id": "a", "user": "vale"})
            with db.transaktion():
                db.anlegen("zeiten", {"id": "b", "user": "vale"})
            raise ValueError("erst danach schiefgegangen")
    assert db.alle("zeiten") == []


def test_pruefen_meldet_gesunde_datei():
    db.anlegen("zeiten", {"id": "a", "user": "vale"})
    ok, meldung = db.pruefen()
    assert ok and "zeiten: 1" in meldung


def test_abzug_ist_fuer_sich_lesbar(tmp_path):
    """Die Sicherung packt einen Abzug ein, keine Kopie der laufenden Datei."""
    import sqlite3
    db.anlegen("zeiten", {"id": "a", "user": "vale"})
    ziel = str(tmp_path / "abzug.db")
    db.sichern_nach(ziel)
    con = sqlite3.connect(ziel)
    assert con.execute("SELECT COUNT(*) FROM zeiten").fetchone()[0] == 1
    con.close()


# ------------------------------------------------------------ Fachmodule darauf
def test_zeiterfassung_ueber_die_datenbank():
    from datetime import datetime
    e = timetrack.check_in("vale", now=datetime(2026, 8, 5, 9, 0))
    assert timetrack.check_in("vale", now=datetime(2026, 8, 5, 9, 5)) is None
    assert timetrack.get_open("vale")["id"] == e["id"]
    timetrack.check_out("vale", now=datetime(2026, 8, 5, 11, 30))
    assert timetrack.get_open("vale") is None
    assert timetrack.duration_minutes(timetrack.get_entry(e["id"])) == 150


def test_zuweisung_und_zuruecksetzen():
    bookings.set_assignment(501, "vale", "test")
    assert bookings.assignee_of(501) == "vale"
    bookings.set_field(501, note="Schlüssel beim Nachbarn")
    bookings.reset(501)
    assert bookings.assignee_of(501) is None
    assert bookings.get_record(501)["note"] == "Schlüssel beim Nachbarn"


def test_bestand_je_wohnung():
    items = housekeeping.get_inventory(2748963)
    assert items and isinstance(items, list)
    housekeeping.save_inventory(2748963, [{"id": "x", "name": "Kaffee", "kategorie": "verbrauch"}])
    assert housekeeping.get_inventory(2748963) == [
        {"id": "x", "name": "Kaffee", "kategorie": "verbrauch"}]


def test_belege_neueste_zuerst():
    receipts.add_receipt("vale", "beleg/a.jpg", merchant="ALDI")
    receipts.add_receipt("vale", "beleg/b.jpg", merchant="REWE")
    assert [r["merchant"] for r in receipts.list_receipts()] == ["REWE", "ALDI"]


# ------------------------------------------------------------ Übernahme
def _alte_dateien(ordner):
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "worklog.json").write_text(json.dumps([
        {"id": "1", "user": "vale", "checkin": "2026-08-01T09:00:00", "checkout": None},
        {"id": "2", "user": "gabriel", "checkin": "2026-08-02T09:00:00",
         "checkout": "2026-08-02T11:00:00", "abgerechnet": "2026-08-03T10:00:00"},
    ]), encoding="utf-8")
    (ordner / "assignments.json").write_text(json.dumps({
        "501": {"assignee": "vale", "history": [{"to": "vale"}]},
    }), encoding="utf-8")
    (ordner / "inventory.json").write_text(json.dumps({
        "2748963": [{"id": "i1", "name": "Kaffee", "kategorie": "verbrauch"}],
    }), encoding="utf-8")
    (ordner / "receipts.json").write_text(json.dumps([
        {"id": "r1", "uploader": "vale", "ts": "2026-08-01T10:00:00", "merchant": "ALDI"},
    ]), encoding="utf-8")
    return ordner


def test_uebernahme_und_gegenlesen(tmp_path):
    ordner = _alte_dateien(tmp_path / "daten")
    stand = migrate_db.uebernehmen(str(ordner))
    assert stand["zeiten"] == 2 and stand["zuweisungen"] == 1
    assert migrate_db.gegenlesen(str(ordner)) == []
    # …und die Fachmodule sehen dasselbe wie vorher
    assert timetrack.get_open("vale")["id"] == "1"
    assert timetrack.is_billed(timetrack.get_entry("2"))
    assert bookings.assignee_of(501) == "vale"
    assert housekeeping.get_inventory(2748963)[0]["name"] == "Kaffee"


def test_gegenlesen_erkennt_abweichung(tmp_path):
    ordner = _alte_dateien(tmp_path / "daten")
    migrate_db.uebernehmen(str(ordner))
    satz = db.holen("zeiten", "2")
    satz["abgerechnet"] = "verändert"
    db.speichern("zeiten", "2", satz)
    assert any("zeiten/2" in f for f in migrate_db.gegenlesen(str(ordner)))


def test_uebernahme_haelt_die_reihenfolge(tmp_path):
    ordner = _alte_dateien(tmp_path / "daten")
    migrate_db.uebernehmen(str(ordner))
    assert [e["id"] for e in timetrack.entries()] == ["2", "1"]   # neueste zuerst


def test_zweiter_lauf_wird_abgelehnt(tmp_path, capsys):
    """Zweimal übernehmen würde alles doppelt anlegen."""
    ordner = _alte_dateien(tmp_path / "daten")
    assert migrate_db.main(["--ordner", str(ordner), "--jetzt"]) == 0
    assert migrate_db.main(["--ordner", str(ordner), "--jetzt"]) == 1
    assert "nicht leer" in capsys.readouterr().out


def test_alte_dateien_bleiben_als_netz_liegen(tmp_path):
    ordner = _alte_dateien(tmp_path / "daten")
    assert migrate_db.main(["--ordner", str(ordner), "--jetzt"]) == 0
    assert not (ordner / "worklog.json").exists()
    assert (ordner / "worklog.json.vor-sqlite").exists()
