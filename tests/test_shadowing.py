"""Der Namens-Prüfer läuft als Test mit.

Er hätte den Checklisten-Absturz vom 28.07. gefunden: dort war `t` (die
Übersetzungsfunktion) durch eine Schleifenvariable überschattet, wodurch
`t("Check-out")` mit UnboundLocalError knallte.
"""
import os
import subprocess
import sys

HIER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRUEFER = os.path.join(HIER, "tools", "check_shadowing.py")


def _lauf(*dateien):
    return subprocess.run([sys.executable, PRUEFER, *dateien],
                          capture_output=True, text=True, cwd=HIER)


def test_kein_name_wird_vor_seiner_bindung_benutzt():
    """Keine Funktion darf einen Modulnamen benutzen, den sie später lokal bindet."""
    r = _lauf()
    assert r.returncode == 0, (
        "Überschattung gefunden – ein Modulname (z. B. die Übersetzungsfunktion "
        "`t`) wird benutzt, bevor er lokal gebunden wird:\n" + r.stdout)


def test_pruefer_erkennt_den_bekannten_fehler(tmp_path):
    """Gegenprobe: der Prüfer darf nicht einfach immer 'alles gut' sagen."""
    schlecht = tmp_path / "schlecht.py"
    schlecht.write_text(
        "def t(text):\n"
        "    return text\n"
        "\n"
        "\n"
        "def render(aufgaben):\n"
        "    print(t('Check-out'))       # Nutzung ...\n"
        "    for t in aufgaben:          # ... und hier erst die Bindung\n"
        "        print(t['text'])\n",
        encoding="utf-8")
    r = _lauf(str(schlecht))
    assert r.returncode == 1, f"Fehler nicht erkannt:\n{r.stdout}"
    assert "UnboundLocalError" in r.stdout
