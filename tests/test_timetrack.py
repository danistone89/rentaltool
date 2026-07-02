"""Tests für die Arbeitszeit-Erfassung."""
from datetime import datetime

from app import timetrack


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(timetrack, "LOG", str(tmp_path / "worklog.json"))


def test_checkin_checkout(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    loc = {"lat": 51.05, "lon": 13.74, "acc": 12}
    e = timetrack.check_in("putzi", loc, now=datetime(2026, 7, 2, 8, 0, 0))
    assert e and timetrack.get_open("putzi")
    # zweiter Check-in blockiert
    assert timetrack.check_in("putzi", loc, now=datetime(2026, 7, 2, 8, 5)) is None
    c = timetrack.check_out("putzi", {"error": "denied"}, now=datetime(2026, 7, 2, 10, 30))
    assert c and not timetrack.get_open("putzi")
    assert timetrack.duration_minutes(c) == 150
    assert timetrack.fmt_dur(150) == "2:30 h"


def test_getrennte_benutzer(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    timetrack.check_in("a", {}, now=datetime(2026, 7, 2, 8))
    timetrack.check_in("b", {}, now=datetime(2026, 7, 2, 9))
    assert timetrack.get_open("a") and timetrack.get_open("b")
    assert len(timetrack.entries("a")) == 1
    assert len(timetrack.entries()) == 2


def test_offene_dauer(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    e = timetrack.check_in("a", {}, now=datetime(2026, 7, 2, 8))
    assert timetrack.duration_minutes(e) is None
    assert timetrack.fmt_dur(None) == "läuft…"
