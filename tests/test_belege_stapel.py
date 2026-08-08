"""Mehrere Belege auf einmal hochladen.

Der Stapel ist der Alltag: man sammelt Quittungen und laedt sie einmal die
Woche gemeinsam hoch. Vorher ging nur eine Datei je Auswahl.
"""
import asyncio

from app.ui import belege


def _lauf(dateien, einzeln):
    return asyncio.get_event_loop().run_until_complete(
        belege._stapel_verarbeiten(dateien, einzeln))


def test_alle_dateien_werden_verarbeitet():
    gesehen = []

    async def einzeln(datei, nr, gesamt):
        gesehen.append((datei, nr, gesamt))
        return {"photo": datei}, None

    fertig, fehler = _lauf(["a.jpg", "b.jpg", "c.pdf"], einzeln)
    assert (fertig, fehler) == (3, [])
    assert gesehen == [("a.jpg", 1, 3), ("b.jpg", 2, 3), ("c.pdf", 3, 3)]


def test_ein_fehler_stoppt_den_stapel_nicht():
    """Sonst verhinderte eine unlesbare Datei in der Mitte alles Nachfolgende –
    und man wuesste hinterher nicht, welche Belege angekommen sind."""
    async def einzeln(datei, nr, gesamt):
        if datei == "kaputt.jpg":
            return None, "nicht lesbar"
        return {"photo": datei}, None

    fertig, fehler = _lauf(["a.jpg", "kaputt.jpg", "c.pdf"], einzeln)
    assert fertig == 2 and fehler == ["nicht lesbar"]


def test_auch_eine_ausnahme_bricht_den_stapel_nicht_ab():
    """Nicht jeder Fehler kommt als Rueckgabewert – eine kaputte PDF wirft."""
    async def einzeln(datei, nr, gesamt):
        if datei == "bombe.pdf":
            raise ValueError("kein PDF")
        return {"photo": datei}, None

    fertig, fehler = _lauf(["a.jpg", "bombe.pdf", "c.pdf"], einzeln)
    assert fertig == 2 and fehler == ["kein PDF"]


def test_die_reihenfolge_bleibt_erhalten():
    """Nacheinander, nicht gleichzeitig: OCR im Thread-Pool parallel zu starten
    braeuchte mehr Speicher und brachte keine Zeit."""
    reihenfolge = []

    async def einzeln(datei, nr, gesamt):
        reihenfolge.append(datei)
        await asyncio.sleep(0)
        reihenfolge.append(f"{datei}-fertig")
        return {}, None

    _lauf(["a", "b"], einzeln)
    assert reihenfolge == ["a", "a-fertig", "b", "b-fertig"]


def test_ohne_dateien_passiert_nichts():
    async def einzeln(datei, nr, gesamt):
        raise AssertionError("darf nicht aufgerufen werden")

    assert _lauf([], einzeln) == (0, [])
