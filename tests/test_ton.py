"""AP-D3: die Farb- und Abstandsrollen halten.

Ein Design-System, das nur einmal aufgeräumt wurde, ist nach drei Bereichen
wieder unaufgeräumt. Diese Tests sind der Grund, warum es hält: sie lesen den
Quelltext und melden, sobald jemand wieder eine Farbe von Hand hinschreibt, für
die es einen Namen gibt.

Sie prüfen bewusst den **Quelltext**, nicht die Oberfläche. Eine Regel über das
Aussehen lässt sich nicht an einem einzelnen Bildschirm festmachen – sie gilt
für alles, was noch kommt.
"""
import pathlib
import re

import pytest

from app.ui import ton

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
MODULE = sorted(p for p in APP.rglob("*.py") if p.name != "ton.py")


def _quelle(p):
    return p.read_text(encoding="utf-8")


@pytest.mark.parametrize("modul", MODULE, ids=lambda p: p.name)
def test_nur_eine_neutrale_skala(modul):
    """`gray` und `slate` sind beides Grautöne, aber `slate` ist blaustichig.
    Untereinander in derselben Karte sieht man den Bruch – vorher stand die
    helle Hälfte der Skala in `gray`, die dunkle in `slate`."""
    treffer = re.findall(r"[\w-]*gray-\d{2,3}", _quelle(modul))
    assert not treffer, (
        f"{modul.name} benutzt wieder die zweite Grau-Skala: {sorted(set(treffer))}. "
        f"Es gibt nur `slate`, und dafür Namen in app/ui/ton.py.")


@pytest.mark.parametrize("modul", MODULE, ids=lambda p: p.name)
def test_bedeutungsfarben_nur_in_einer_stufe(modul):
    """„Hinweis" war je nach Fundstelle amber-600, -700 oder -800. Erlaubt sind
    die Stufe 700 (auf Weiß) und 800 (auf getönter Fläche) – und die haben
    Namen. Die helleren Stufen sagen dasselbe, nur zufällig anders."""
    verboten = re.findall(r"text-(?:amber|orange|green|red)-(?:400|500|600)",
                          _quelle(modul))
    assert not verboten, (
        f"{modul.name}: {sorted(set(verboten))} – für Bedeutungen gibt es "
        f"HINWEIS/DRINGEND/ERFOLG/STOERUNG in app/ui/ton.py.")


@pytest.mark.parametrize("modul", MODULE, ids=lambda p: p.name)
def test_das_kartenrezept_steht_nur_an_einer_stelle(modul):
    """Die Karte ist die Grundform der Oberfläche und stand an achtzehn Stellen
    Wort für Wort neu geschrieben – mit Innenabständen zwischen p-3 und p-4."""
    assert "rounded-xl shadow-sm border border-slate-100" not in _quelle(modul), (
        f"{modul.name} baut die Karte selbst nach – ton.KARTE_ENG / "
        f"ton.KARTE_WEIT / ton.KARTENFLAECHE nehmen.")


def test_die_rollen_sind_vollstaendig_und_eindeutig():
    """Jede Bedeutung genau einmal, und keine zwei Namen für dieselbe Klasse."""
    bedeutungen = {"HINWEIS": ton.HINWEIS, "DRINGEND": ton.DRINGEND,
                   "ERFOLG": ton.ERFOLG, "STOERUNG": ton.STOERUNG}
    assert len(set(bedeutungen.values())) == 4, bedeutungen

    neutral = [ton.TITEL, ton.TEXT, ton.GEDECKT, ton.LEISE, ton.STILL, ton.ZART]
    assert len(set(neutral)) == len(neutral), "zwei Namen für denselben Ton"
    assert all(n.startswith("text-slate-") for n in neutral), neutral


def test_getoente_flaeche_bekommt_die_dunklere_stufe():
    """Auf `bg-amber-50` trägt amber-700 den Kontrast nicht mehr. Das ist keine
    zweite Bedeutung, sondern dieselbe im anderen Zusammenhang."""
    for hell, dunkel in [(ton.HINWEIS, ton.AUF_HINWEIS),
                         (ton.DRINGEND, ton.AUF_DRINGEND),
                         (ton.ERFOLG, ton.AUF_ERFOLG),
                         (ton.STOERUNG, ton.AUF_STOERUNG)]:
        assert hell.endswith("-700") and dunkel.endswith("-800")
        assert hell.rsplit("-", 1)[0] == dunkel.rsplit("-", 1)[0], (hell, dunkel)


def test_tap_ziel_ist_gross_genug():
    """44 Punkte ist die kleinste Fläche, die ein Daumen zuverlässig trifft."""
    groesse = int(re.search(r"\[(\d+)px\]", ton.TAP).group(1))
    assert groesse >= 44, ton.TAP
