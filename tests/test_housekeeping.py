"""Tests für Reinigung & Qualität (Checklisten, Durchgänge, Schäden, Bestand)."""
import os

from app import housekeeping as hk


def _setup(tmp_path, monkeypatch):
    for attr in ("CHECKLISTS", "INVENTORY", "CLEANINGS", "DAMAGES", "RESTOCK"):
        monkeypatch.setattr(hk, attr, str(tmp_path / (attr.lower() + ".json")))
    monkeypatch.setattr(hk, "MEDIA_DIR", str(tmp_path / "media"))


def test_checkliste_default(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    cl = hk.get_checklist("apt1")
    assert cl["rooms"] and cl["rooms"][0]["tasks"]
    assert all("id" in t for r in cl["rooms"] for t in r["tasks"])


def test_durchgang_flow(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    cl = hk.get_checklist("apt1")
    tid = cl["rooms"][0]["tasks"][0]["id"]
    r = hk.start_run("apt1", "Cottaer Straße", "putzi")
    assert hk.start_run("apt1", "Cottaer Straße", "putzi")["id"] == r["id"]  # kein Duplikat
    hk.update_task(r["id"], tid, done=True, ist_photo="cleanings/x.jpg")
    hk.finish_run(r["id"])
    assert hk.get_open_run("apt1", "putzi") is None
    run = hk.list_runs()[0]
    assert run["tasks"][tid]["done"] and run["finished"]


def test_schaden_und_bestand(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    d = hk.add_damage("apt1", "Cottaer Straße", "Bad", "Spiegel gerissen", "hoch",
                      None, "putzi")
    assert len(hk.list_damages(only_open=True)) == 1
    hk.set_damage_status(d["id"], "erledigt")
    assert hk.list_damages(only_open=True) == []
    hk.add_restock("apt1", "Cottaer Straße", "Toilettenpapier", "2 Packungen",
                   "verbrauch", "putzi")
    assert len(hk.list_restock()) == 1


def test_foto_speichern(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    rel = hk.save_photo("ist", b"%JPGdata")
    assert os.path.exists(os.path.join(hk.MEDIA_DIR, rel))
    assert rel.startswith("ist/")
