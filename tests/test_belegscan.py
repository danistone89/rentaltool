"""Tests für den Belegscanner: ausgelieferte Bibliothek und PDF-Erzeugung."""
import os

import pytest

from app import receipts, web

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_jscanify_wird_mitgeliefert():
    """Der CDN-Pfad war 404 – die Bibliothek muss lokal vorliegen."""
    p = os.path.join(HERE, "static", "jscanify.js")
    assert os.path.exists(p), "static/jscanify.js fehlt"
    src = open(p, encoding="utf-8").read()
    assert "class jscanify" in src
    for fn in ("findPaperContour", "getCornerPoints", "extractPaper"):
        assert fn in src, f"{fn} fehlt in jscanify.js"


def test_scanner_laedt_lokal_zuerst():
    js = web._SCAN_JS
    assert "'/static/jscanify.js'" in js
    assert "'/static/opencv.js'" in js
    # der tote Pfad darf nicht zurueckkommen
    assert "dist/jscanify.min.js" not in js


def test_scanner_hat_automatik_und_aufraeumen():
    js = web._SCAN_JS
    assert "emitEvent('beleg_scan'" in js
    assert "__belegShoot" in js and "__belegAuto" in js
    assert "img.delete()" in js, "cv.Mat muss je Frame freigegeben werden"
    assert "findPaperContour" in js and "extractPaper" in js


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
