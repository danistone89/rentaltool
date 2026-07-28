"""Tests für den Belegscanner: ausgelieferte Bibliothek und PDF-Erzeugung."""
import os

import pytest

from app import receipts, web

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_scanner_braucht_keine_fremdbibliothek():
    """Die automatische Kantenerkennung (OpenCV.js + jscanify) ist raus – der
    Scanner arbeitet mit reinem Canvas und von Hand gesetzten Ecken."""
    js = web._SCAN_JS
    assert "opencv" not in js.lower()
    assert "jscanify" not in js.lower()
    assert not os.path.exists(os.path.join(HERE, "static", "jscanify.js"))


def test_scanner_hat_beide_schritte():
    js = web._SCAN_JS
    for fn in ("__belegCapture", "__belegSave", "__belegRetake",
               "__belegReset", "__belegFile", "__belegStop"):
        assert fn in js, f"{fn} fehlt"
    assert "emitEvent('beleg_scan'" in js
    assert "corners: pts" in js, "Ecken muessen mitgeschickt werden"
    assert "touchstart" in js and "touchmove" in js, "muss auf dem Handy ziehbar sein"


def _bild(tmp_path, w, h):
    import fitz
    p = str(tmp_path / f"{w}x{h}.jpg")
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h))
    pix.set_rect(pix.irect, (240, 240, 235))
    pix.save(p)
    return p


@pytest.mark.parametrize("w,h,erwartet", [(800, 1200, (595, 842)), (1200, 800, (842, 595))])
def test_pdf_ist_a4(tmp_path, w, h, erwartet):
    import fitz
    pdf = str(tmp_path / "out.pdf")
    assert receipts.image_to_pdf(_bild(tmp_path, w, h), pdf)
    d = fitz.open(pdf)
    r = d[0].rect
    assert (round(r.width), round(r.height)) == erwartet
    assert len(d[0].get_images()) == 1
    d.close()


def test_pdf_ohne_a4_behaelt_das_bildformat(tmp_path):
    """Ohne A4-Vorgabe entspricht die Seite dem Bild (PyMuPDF rechnet 96 dpi
    in 72 pt um, daher Seitenverhaeltnis statt Pixelmass pruefen)."""
    import fitz
    pdf = str(tmp_path / "raw.pdf")
    assert receipts.image_to_pdf(_bild(tmp_path, 800, 1200), pdf, page=None)
    d = fitz.open(pdf)
    r = d[0].rect
    assert round(r.height / r.width, 3) == round(1200 / 800, 3)
    d.close()


def test_pdf_bei_kaputter_datei(tmp_path):
    p = tmp_path / "kaputt.jpg"
    p.write_bytes(b"kein bild")
    assert receipts.image_to_pdf(str(p), str(tmp_path / "x.pdf")) is False


def test_scanner_html_wird_nicht_saniert():
    """Ohne sanitize=False entfernt NiceGUI <video>/<canvas> aus dem ui.html –
    der Scanner bliebe schwarz. NiceGUI 3.6 verlangt das Argument sogar."""
    import inspect
    src = inspect.getsource(web.render_belege)
    assert 'id="beleg-scan"' in src
    assert "sanitize=False" in src


# ------------------------------------------------- Zuschnitt aus vier Ecken
def _foto(tmp_path, w=1000, h=1400):
    """Bild mit hellem 'Beleg' auf dunklem Grund."""
    import fitz
    p = str(tmp_path / "foto.jpg")
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h))
    pix.set_rect(pix.irect, (30, 30, 30))
    pix.set_rect(fitz.IRect(int(w * .2), int(h * .2), int(w * .8), int(h * .8)),
                 (250, 250, 245))
    pix.save(p)
    return p


def test_crop_quad_schneidet_auf_die_ecken(tmp_path):
    import fitz
    src, dst = _foto(tmp_path), str(tmp_path / "out.jpg")
    ecken = [(.2, .2), (.8, .2), (.8, .8), (.2, .8)]
    assert receipts.crop_quad(src, dst, ecken)
    d = fitz.open(dst)
    r = d[0].rect
    # 60 % von 1000x1400 -> Seitenverhaeltnis 600:1120
    assert 0.5 < (r.width / r.height) / (600 / 1120) < 2.0
    d.close()


@pytest.mark.parametrize("ecken", [
    None, [], [(0, 0)], [(0, 0), (1, 0), (1, 1)],            # falsche Anzahl
    [(0, 0), (1, 0), (1, 1), ("x", 1)],                       # nicht numerisch
    [(0, 0), (1, 0), (1, 1), (0, 9)],                         # ausserhalb 0..1
])
def test_crop_quad_weist_unsinn_ab(tmp_path, ecken):
    assert receipts.crop_quad(_foto(tmp_path), str(tmp_path / "x.jpg"), ecken) is False


def test_crop_quad_zu_kleiner_ausschnitt(tmp_path):
    winzig = [(.50, .50), (.505, .50), (.505, .505), (.50, .505)]
    assert receipts.crop_quad(_foto(tmp_path), str(tmp_path / "x.jpg"), winzig) is False


def test_save_document_nutzt_die_ecken(tmp_path, monkeypatch):
    """Mit Ecken wird zugeschnitten, ohne bleibt das Original."""
    from app import housekeeping as hk
    monkeypatch.setattr(hk, "MEDIA_DIR", str(tmp_path / "media"))
    raw = open(_foto(tmp_path), "rb").read()
    mit = receipts.save_document(raw, "jpg", None, True,
                                 [(.2, .2), (.8, .2), (.8, .8), (.2, .8)])
    assert mit["photo"].endswith("_doc.jpg"), "Zuschnitt haette greifen muessen"
    ohne = receipts.save_document(raw, "jpg", None, False)
    assert ohne["photo"].endswith(".jpg") and not ohne["photo"].endswith("_doc.jpg")
