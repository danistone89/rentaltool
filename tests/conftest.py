import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Nur das headless User-Plugin (das volle plugin.py zieht Selenium nach)
pytest_plugins = ["nicegui.testing.user_plugin"]


@pytest.fixture(autouse=True)
def eigene_datenbank(tmp_path, monkeypatch):
    """Jeder Test bekommt eine eigene, leere Datenbank.

    Vorher zeigte jeder Test die Dateipfade der Module einzeln auf `tmp_path`
    um – dabei wurde regelmäßig einer vergessen, und der Test schrieb in den
    echten Bestand. Mit einer Datei für alles genügt ein Griff, und er passiert
    hier automatisch für jeden Test.
    """
    from app import db
    monkeypatch.setattr(db, "DATEI", str(tmp_path / "test.db"))
    db.zuruecksetzen()
    yield
    db.zuruecksetzen()
