"""Speicherschicht: atomar schreiben, gesperrt ändern.

Die beiden Fehler, um die es geht, treten nie beim Ausprobieren auf und immer im
Betrieb: ein Abbruch mitten im Schreiben, und zwei Vorgänge, die sich gegenseitig
überschreiben. Beides wird hier echt hergestellt – mit einem Prozessabbruch und
mit gleichzeitig laufenden Prozessen, nicht mit Attrappen.
"""
import json
import os
import subprocess
import sys
import textwrap
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import store  # noqa: E402

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_lesen_und_schreiben(tmp_path):
    p = str(tmp_path / "d.json")
    assert store.read(p, []) == []
    store.write(p, [{"a": 1}])
    assert store.read(p, []) == [{"a": 1}]


def test_kaputte_datei_wird_nicht_still_zur_leeren_liste(tmp_path):
    """Der teuerste Rückfall überhaupt: läse eine kaputte Datei als [], würde der
    nächste Schreibvorgang den (noch vorhandenen) Bestand endgültig überschreiben."""
    p = tmp_path / "d.json"
    p.write_text("{kein json", encoding="utf-8")
    with pytest.raises(store.DatenFehler):
        store.read(str(p), [])
    assert p.read_text(encoding="utf-8") == "{kein json"   # unangetastet


def test_fehlgeschlagenes_schreiben_laesst_den_alten_stand_stehen(tmp_path):
    """Nicht serialisierbarer Inhalt: früher war die Datei danach leer, weil
    open(..., "w") sie sofort auf 0 Bytes kürzt."""
    p = str(tmp_path / "d.json")
    store.write(p, [{"gut": 1}])
    with pytest.raises(TypeError):
        store.write(p, [{"schlecht": object()}])
    assert store.read(p, []) == [{"gut": 1}]
    assert not [f for f in os.listdir(tmp_path) if ".tmp-" in f], "Nachbardatei blieb liegen"


def test_abbruch_mitten_im_schreiben_zerstoert_die_datei_nicht(tmp_path):
    """Prozess wird während des Schreibens hart abgeschossen (SIGKILL).

    Das ist der Fall aus dem echten Leben: Server-Neustart, OOM-Killer,
    Stromausfall. Danach muss der alte Stand vollständig lesbar sein.
    """
    p = tmp_path / "d.json"
    store.write(str(p), [{"stand": "alt"}])
    skript = tmp_path / "schreiber.py"
    skript.write_text(textwrap.dedent(f"""
        import sys, os, signal, json
        sys.path.insert(0, {WURZEL!r})
        from app import store

        def halb_und_tot(obj, f, **kw):
            f.write('[{{"stand": "neu"')      # halbe Zeile ...
            f.flush()
            os.kill(os.getpid(), signal.SIGKILL)   # ... und mittendrin weg
        json.dump = halb_und_tot
        store.write({str(p)!r}, [{{"stand": "neu"}}])
    """), encoding="utf-8")
    r = subprocess.run([sys.executable, str(skript)], capture_output=True)
    assert r.returncode != 0                      # wirklich abgestürzt
    assert json.loads(p.read_text(encoding="utf-8")) == [{"stand": "alt"}]
    # Die halbe Nachbardatei bleibt liegen (der Prozess kam nicht mehr zum
    # Aufräumen) – lesen und schreiben müssen trotzdem weiter funktionieren.
    store.write(str(p), [{"stand": "danach"}])
    assert store.read(str(p), []) == [{"stand": "danach"}]


def test_edit_schreibt_beim_verlassen(tmp_path):
    p = str(tmp_path / "d.json")
    with store.edit(p, []) as a:
        a.wert.append("x")
    assert store.read(p, []) == ["x"]


def test_edit_schreibt_nicht_nach_verwerfen(tmp_path):
    p = str(tmp_path / "d.json")
    store.write(p, ["alt"])
    with store.edit(p, []) as a:
        a.wert.append("neu")
        a.verwerfen()
    assert store.read(p, []) == ["alt"]


def test_edit_schreibt_nicht_bei_ausnahme(tmp_path):
    p = str(tmp_path / "d.json")
    store.write(p, ["alt"])
    with pytest.raises(ValueError):
        with store.edit(p, []) as a:
            a.wert.append("neu")
            raise ValueError("mittendrin schiefgegangen")
    assert store.read(p, []) == ["alt"]


def test_sperre_ist_im_selben_thread_erneut_betretbar(tmp_path):
    """Sonst verklemmt sich die App selbst, sobald zwei Funktionen dieselbe Datei
    schachteln (z. B. get_checklist innerhalb einer Änderung)."""
    p = str(tmp_path / "d.json")
    with store.sperre(p):
        with store.sperre(p):
            store.write(p, ["drin"])
    assert store.read(p, []) == ["drin"]


def test_sperre_meldet_sich_statt_ewig_zu_warten(tmp_path):
    p = str(tmp_path / "d.json")
    gesperrt = threading.Event()
    weiter = threading.Event()

    def halten():
        with store.sperre(p):
            gesperrt.set()
            weiter.wait(5)

    t = threading.Thread(target=halten, daemon=True)
    t.start()
    gesperrt.wait(5)
    try:
        with pytest.raises(store.SperrFehler):
            with store.sperre(p, timeout=0.3):
                pass
    finally:
        weiter.set()
        t.join(5)


def test_gleichzeitige_prozesse_verlieren_keine_eintraege(tmp_path):
    """Der eigentliche Grund für die Sperre.

    Vier Prozesse hängen gleichzeitig je 25 Einträge an dieselbe Datei. Ohne
    Sperre überschreiben sie sich gegenseitig und es fehlen Einträge – genau das
    passiert im Betrieb, wenn die App schreibt, während `useradmin` oder die
    Sicherung laufen.
    """
    p = tmp_path / "d.json"
    store.write(str(p), [])
    skript = tmp_path / "anhaenger.py"
    skript.write_text(textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {WURZEL!r})
        from app import store
        wer = sys.argv[1]
        for i in range(25):
            with store.edit({str(p)!r}, []) as a:
                a.wert.append(f"{{wer}}-{{i}}")
            time.sleep(0.001)
    """), encoding="utf-8")

    prozesse = [subprocess.Popen([sys.executable, str(skript), f"p{n}"])
                for n in range(4)]
    for pr in prozesse:
        assert pr.wait(timeout=60) == 0

    eintraege = json.loads(p.read_text(encoding="utf-8"))
    assert len(eintraege) == 100, f"Einträge verloren gegangen: {len(eintraege)} von 100"
    assert len(set(eintraege)) == 100


def test_sperrdatei_liegt_neben_der_datei_und_nicht_darin(tmp_path):
    """Die Sperre darf die Nutzdatei nicht anfassen – os.replace haengt eine neue
    Datei an den Namen, eine Sperre auf der alten waere danach wertlos."""
    p = str(tmp_path / "d.json")
    store.write(p, ["x"])
    assert os.path.exists(p + ".lock")
    assert store.read(p, []) == ["x"]
