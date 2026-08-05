"""Sicherung: Aufbewahrungsregel, Paketbau und die Wiederherstellungs-Probe.

Der gefährliche Teil einer Sicherung ist nicht das Hochladen, sondern (a) die
Regel, die alte Stände wegräumt, und (b) die Annahme, ein Paket sei heil, weil
`tar` keinen Fehler gemeldet hat. Beides wird hier geprüft.
"""
import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import backup  # noqa: E402


def _datenordner(tmp_path, konten=True, kaputt=False):
    """Minimaler Datenbestand, wie er im Betrieb liegt."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    cfg = {"auth": {"users": {"admin": {"role": "admin"}}} if konten else {},
           "steuersatz": 6}
    (tmp_path / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    (tmp_path / "worklog.json").write_text(
        "kein json{" if kaputt else json.dumps([{"id": "1", "user": "vale"}]),
        encoding="utf-8")
    (tmp_path / "assignments.json").write_text(json.dumps({"501": {"assignee": "vale"}}),
                                               encoding="utf-8")
    media = tmp_path / "media"
    media.mkdir()
    (media / "beleg.jpg").write_bytes(b"\xff\xd8foto")
    sitzungen = tmp_path / ".nicegui"
    sitzungen.mkdir()
    (sitzungen / "storage-user-1.json").write_text("{}", encoding="utf-8")
    return tmp_path


# ------------------------------------------------------------ Aufbewahrung
def test_taegliche_sicherungen_bleiben_zwei_wochen():
    heute = date(2026, 8, 5)
    namen = [backup.name_fuer(heute - timedelta(days=i)) for i in range(60)]
    keep, weg = backup.behalten(namen)
    for i in range(backup.TAEGLICH):
        assert backup.name_fuer(heute - timedelta(days=i)) in keep
    assert weg, "nach 60 Tagen muss aufgeräumt werden"


def test_sonntage_und_monatserste_ueberleben_laenger():
    """Nach einem Jahr darf nicht nur der letzte Monat übrig sein – sonst ist ein
    Fehler, der erst nach Wochen auffällt, nicht mehr zurückzuholen."""
    heute = date(2026, 8, 5)
    namen = [backup.name_fuer(heute - timedelta(days=i)) for i in range(365)]
    keep, _weg = backup.behalten(namen)
    alt = date(2026, 2, 1)                      # Monatserster, weit zurück
    assert backup.name_fuer(alt) in keep
    sonntag = date(2026, 7, 5)                  # Sonntag, älter als 14 Tage
    assert sonntag.weekday() == 6
    assert backup.name_fuer(sonntag) in keep
    beliebiger_dienstag = date(2026, 3, 10)
    assert backup.name_fuer(beliebiger_dienstag) not in keep


def test_fremde_dateien_werden_nicht_angefasst():
    """Am Ziel liegen womöglich andere Dateien. Die Sicherung löscht nur ihre eigenen."""
    namen = ["Notizen.txt", "rentaltool-kaputt.tar.gz", "backup-2020-01-01.zip",
             backup.name_fuer(date(2020, 3, 17))]
    keep, weg = backup.behalten(namen)
    assert weg == []                     # zu wenige eigene Stände zum Aufräumen
    assert "Notizen.txt" not in keep      # und fremde tauchen gar nicht erst auf


def test_ziel_erkennt_rclone_und_lokal():
    assert backup.ist_rclone("nextcloud:03 Immobilien/Backups")
    assert not backup.ist_rclone("/var/backups/rentaltool")
    assert not backup.ist_rclone("C:\\Backups")


# ------------------------------------------------------------ Paket
def test_paket_enthaelt_daten_aber_keine_sitzungen(tmp_path):
    quelle = _datenordner(tmp_path / "daten")
    ziel = tmp_path / "paket.tar.gz"
    backup.paket_bauen(str(quelle), str(ziel))
    import tarfile
    with tarfile.open(ziel) as tar:
        namen = tar.getnames()
    assert "config.json" in namen
    assert "worklog.json" in namen
    assert "media/beleg.jpg" in namen
    assert not [n for n in namen if ".nicegui" in n], f"Sitzungen mitgesichert: {namen}"


def test_pruefung_erkennt_heiles_paket(tmp_path):
    quelle = _datenordner(tmp_path / "daten")
    ziel = tmp_path / "paket.tar.gz"
    backup.paket_bauen(str(quelle), str(ziel))
    ok, meldungen = backup.paket_pruefen(str(ziel))
    assert ok, meldungen


def test_pruefung_schlaegt_bei_kaputtem_json_an(tmp_path):
    """Genau der Fall, für den die Sicherung da ist – sie darf ihn nicht als
    'erledigt' melden und die letzte heile Kopie wegräumen."""
    quelle = _datenordner(tmp_path / "daten", kaputt=True)
    ziel = tmp_path / "paket.tar.gz"
    backup.paket_bauen(str(quelle), str(ziel))
    ok, meldungen = backup.paket_pruefen(str(ziel))
    assert not ok
    assert any("worklog.json" in m for m in meldungen), meldungen


def test_pruefung_schlaegt_ohne_konten_an(tmp_path):
    """Ein Paket ohne Benutzerkonten wäre wertlos – daraus lässt sich die App
    nicht wiederherstellen, obwohl alle Dateien formal in Ordnung sind."""
    quelle = _datenordner(tmp_path / "daten", konten=False)
    ziel = tmp_path / "paket.tar.gz"
    backup.paket_bauen(str(quelle), str(ziel))
    ok, meldungen = backup.paket_pruefen(str(ziel))
    assert not ok
    assert any("Benutzerkonten" in m for m in meldungen), meldungen


def test_defekte_datei_wird_gemeldet_aber_mitgesichert(tmp_path):
    quelle = _datenordner(tmp_path / "daten", kaputt=True)
    assert any("worklog.json" in m for m in backup.json_defekt(str(quelle)))


# ------------------------------------------------------------ Ablauf über einen lokalen Ordner
def test_sichern_hochladen_und_aufraeumen(tmp_path, monkeypatch):
    """Kompletter Durchlauf gegen einen lokalen Ordner als Ziel."""
    quelle = _datenordner(tmp_path / "daten")
    ziel = tmp_path / "cloud"
    monkeypatch.setattr(backup.paths, "DATA_DIR", str(quelle))
    monkeypatch.setattr(backup.paths, "p", lambda *t: os.path.join(str(quelle), *t))
    # Bestand wie nach ein paar Wochen Betrieb, plus eine Altlast, die die Regel
    # entfernen muss: weit zurück und weder Sonntag noch Monatserster – sonst
    # wäre sie durch die Wochen-/Monatsregel geschützt.
    ziel.mkdir()
    for i in range(1, 21):
        (ziel / backup.name_fuer(date.today() - timedelta(days=i))).write_bytes(b"alt")
    altes_datum = date.today() - timedelta(days=400)
    while altes_datum.weekday() == 6 or altes_datum.day == 1:
        altes_datum -= timedelta(days=1)
    alt = backup.name_fuer(altes_datum)
    (ziel / alt).write_bytes(b"alt")

    class A:
        pass
    args = A()
    args.ziel = str(ziel)
    assert backup.cmd_sichern(args) == 0

    heute = backup.name_fuer(date.today())
    assert (ziel / heute).exists()
    assert not (ziel / alt).exists(), "alte Sicherung wurde nicht aufgeräumt"

    status = json.loads((quelle / backup.STATUS).read_text(encoding="utf-8"))
    assert status["ok"] and status["datei"] == heute

    # …und die Wiederherstellungs-Probe auf demselben Ziel
    assert backup.cmd_pruefen(args) == 0
