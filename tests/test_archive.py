"""Tests für die revisionssichere Ablage (Hash-Kette + Manipulationserkennung)."""
import os

from app import archive


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "ARCHIVE_DIR", str(tmp_path))
    monkeypatch.setattr(archive, "LEDGER_PATH", os.path.join(str(tmp_path), "ledger.jsonl"))


def test_revisionen_und_kette(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    e1 = archive.archive_pdf(b"PDF-A", "2025-12", {"steuer": 341.90})
    e2 = archive.archive_pdf(b"PDF-B", "2026-05", {"steuer": 429.35})
    e3 = archive.archive_pdf(b"PDF-A2", "2025-12", {"steuer": 350.00})  # Korrektur

    assert e1["revision"] == 1 and e3["revision"] == 2   # neue Revision, nicht überschrieben
    assert e2["prev_hash"] == e1["entry_hash"]            # verkettet
    ok, results = archive.verify()
    assert ok and all(r["ok"] for r in results)

    # Dateien sind schreibgeschützt
    mode = os.stat(os.path.join(str(tmp_path), e1["file"])).st_mode
    assert not (mode & 0o222)


def test_spiegelung(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    mirror = tmp_path / "nextcloud"
    e1 = archive.archive_pdf(b"PDF-A", "2025-12", {"steuer": 341.90})
    archive.mirror_entry(e1, str(mirror))
    assert (mirror / e1["file"]).exists()
    assert (mirror / "ledger.jsonl").exists()
    # zweite Ablage, dann komplette Spiegelung
    archive.archive_pdf(b"PDF-B", "2026-05", {"steuer": 429.35})
    n = archive.mirror_all(str(mirror))
    assert n == 2


def test_manipulation_wird_erkannt(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    e = archive.archive_pdf(b"ORIGINAL", "2025-12", {"steuer": 341.90})
    path = os.path.join(str(tmp_path), e["file"])
    os.chmod(path, 0o644)
    with open(path, "wb") as f:
        f.write(b"GEFAELSCHT")
    ok, results = archive.verify()
    assert not ok
    assert any("verändert" in i for r in results for i in r["issues"])
