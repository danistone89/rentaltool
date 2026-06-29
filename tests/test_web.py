"""Headless-UI-Test der NiceGUI-Oberfläche (ohne Browser).

Prüft, dass die Seite lädt und „Berechnen" das Ergebnis (KPIs + Tabelle)
rendert. Netzwerk (Smoobu) wird gemockt, Ergebnis aus der Dezember-Fixture.
"""
import json
import os
from datetime import date

import pytest
from nicegui.testing import User

from app import data, steuer, web  # noqa: F401

FIXTURE = os.path.join(os.path.dirname(__file__), "fixture_2025-12.json")


@pytest.fixture
def mock_backend(monkeypatch):
    bookings = json.load(open(FIXTURE, encoding="utf-8"))
    result = steuer.compute(bookings, 2025, 12, today=date(2026, 6, 29))
    monkeypatch.setattr(data, "get_apartments", lambda: [
        {"id": 2748963, "name": "Cottaer Straße"},
        {"id": 2960031, "name": "Wernerstraße"},
    ])
    monkeypatch.setattr(data, "compute", lambda *a, **k: result)
    web._APARTMENTS.clear()


async def test_seite_laedt(user: User, mock_backend):
    await user.open("/")
    await user.should_see("Beherbergungssteuer Dresden")
    await user.should_see("Berechnen")


async def test_berechnen_zeigt_ergebnis(user: User, mock_backend):
    await user.open("/")
    user.find("Berechnen").click()
    await user.should_see("341,90")          # Steuer-KPI
    await user.should_see("Buchungen")        # Tabellen-Überschrift
    await user.should_see("revisionssicher ablegen")  # Festschreiben-Button
