"""Tests für die abschaltbare Standorterfassung der Zeiterfassung."""
import pytest

from app import web


@pytest.fixture
def geo(monkeypatch):
    def _set(on):
        monkeypatch.setitem(web.CFG, "standort_erfassung", on)
    return _set


def test_standard_ist_aus(monkeypatch):
    monkeypatch.delitem(web.CFG, "standort_erfassung", raising=False)
    assert web._geo_enabled() is False


def test_schalter_wirkt(geo):
    geo(True); assert web._geo_enabled() is True
    geo(False); assert web._geo_enabled() is False


async def test_get_location_fragt_nicht_wenn_aus(geo, monkeypatch):
    geo(False)
    gerufen = []
    monkeypatch.setattr(web.ui, "run_javascript",
                        lambda *a, **k: gerufen.append(1))
    r = await web.get_location()
    assert r == {"error": "deaktiviert"}
    assert not gerufen, "es darf kein Geolocation-JS an den Browser gehen"


async def test_get_ip_fragt_nicht_wenn_aus(geo, monkeypatch):
    geo(False)
    gerufen = []
    monkeypatch.setattr(web.ui, "run_javascript", lambda *a, **k: gerufen.append(1))
    assert await web.get_ip() == ""
    assert not gerufen


def test_geofence_liefert_nichts_wenn_aus(geo, monkeypatch):
    monkeypatch.setitem(web.CFG, "arbeitsorte",
                        [{"name": "Cottaer", "lat": 51.05, "lon": 13.72, "radius_m": 150}])
    loc = {"lat": 51.05, "lon": 13.72}
    geo(True)
    assert web._match_geofence(loc) == ("Cottaer", 0)
    geo(False)
    assert web._match_geofence(loc) == (None, None)


def test_presence_bleibt_leer_wenn_aus(geo):
    geo(False)
    assert web._presence("Cottaer", 10, {"lat": 1, "lon": 2}, "1.2.3.4") == ""
    geo(True)
    assert web._presence("Cottaer", 10, {"lat": 1, "lon": 2}, "1.2.3.4") == "✓ Cottaer (10 m)"
