"""Farb- und Abstandsrollen der Oberfläche – eine Stelle, ein Vokabular.

Warum es dieses Modul gibt: Die Farben standen als Tailwind-Klassen verstreut im
Code, und dabei sind zwei Fehler gewachsen.

**Erstens zwei Neutral-Skalen für eine Aufgabe.** Die hellen Stufen kamen aus
`gray` (`text-gray-400`, `text-gray-500`), die dunklen aus `slate`
(`text-slate-700`, `text-slate-800`). Beides sind Grautöne, aber `gray` ist
neutral und `slate` leicht blaustichig – untereinander in derselben Karte sieht
man den Bruch. Jetzt gibt es nur noch `slate`.

**Zweitens gleiche Bedeutung in verschiedenen Stufen.** „Hinweis" war je nach
Fundstelle `amber-600`, `amber-700` oder `amber-800`.

Die Regel ab hier: **In neuem Code steht keine Farbklasse mehr direkt.** Wer
etwas hervorheben will, sucht sich hier die Bedeutung und nimmt deren Namen. Was
hier fehlt, ist entweder keine eigene Bedeutung – oder gehört hier ergänzt.

    ui.label(text).classes(ton.LEISE)
    ui.icon("warning").classes(ton.DRINGEND)
    with ui.card().classes(ton.KARTE_ENG): ...

Der Test `tests/test_ton.py` hält die Regel fest: `gray` darf nirgends mehr
vorkommen, sonst wächst die zweite Skala wieder nach.
"""

# ---- Neutrale Töne: eine Skala, von laut nach leise ------------------------
TITEL = "text-slate-800"      # Überschriften
TEXT = "text-slate-700"       # normaler Fließtext
GEDECKT = "text-slate-600"    # Text, der zurücktreten darf
LEISE = "text-slate-500"      # Nebeninfo, Unterzeilen
STILL = "text-slate-400"      # Zeitstempel, Platzhalter, „hier steht nichts"
ZART = "text-slate-300"       # nur für große Symbole in leeren Bereichen

# ---- Bedeutungen ----------------------------------------------------------
# Vier, und mehr sollen es nicht werden: wer fünf Dringlichkeiten unterscheidet,
# unterscheidet keine mehr.
HINWEIS = "text-amber-700"    # „offen", „noch frei", „so ist es eingestellt"
DRINGEND = "text-orange-700"  # es eilt heute – Wechseltag
ERFOLG = "text-green-700"     # erledigt, bestätigt
STOERUNG = "text-red-700"     # kaputt, überfällig, fehlgeschlagen

# Auf getönter Fläche braucht der Text eine Stufe mehr – sonst trägt der
# Kontrast nicht. Das ist keine zweite Bedeutung, sondern dieselbe im anderen
# Zusammenhang: `HINWEIS` auf Weiß, `AUF_HINWEIS` auf `FLAECHE_HINWEIS`.
AUF_HINWEIS = "text-amber-800"
AUF_DRINGEND = "text-orange-800"
AUF_ERFOLG = "text-green-800"
AUF_STOERUNG = "text-red-800"

# Großes Symbol eines Zustands – so blass, dass es die Aussage nicht überstimmt.
SYMBOL_LEER = "text-slate-300"
SYMBOL_STOERUNG = "text-red-200"

# Dieselben Bedeutungen als Fläche (Hintergrund + Rand), für Banner und Felder.
FLAECHE_HINWEIS = "bg-amber-50 border border-amber-200"
FLAECHE_DRINGEND = "bg-orange-50 border border-orange-300"
FLAECHE_ERFOLG = "bg-green-50 border border-green-200"
FLAECHE_STOERUNG = "bg-red-50 border border-red-200"
FLAECHE_RUHIG = "bg-slate-50 border border-slate-200"

# ---- Abstände und Flächen -------------------------------------------------
# Die Karte ist die Grundform der Oberfläche. Sie stand an fünfzehn Stellen
# Wort für Wort neu geschrieben, mit Innenabständen zwischen p-3 und p-4.
KARTENFLAECHE = "rounded-xl shadow-sm border border-slate-100"  # ohne Breite
KARTE = "w-full " + KARTENFLAECHE                               # ohne Innenabstand
KARTE_ENG = KARTE + " p-3 gap-2"      # Normalfall: Listen, Formularblöcke
KARTE_WEIT = KARTE + " p-4 gap-2"     # wenn der Inhalt Luft braucht

# Innenabstand des Bereichsinhalts – am Handy knapp, am Rechner großzügig.
INHALT = "w-full max-w-6xl mx-auto p-3 sm:p-6 gap-4 sm:gap-5"

# Mindestgröße eines Tap-Ziels. 44 Punkte ist die kleinste Fläche, die ein
# Daumen zuverlässig trifft – darunter wird geraten.
TAP = "min-h-[44px]"
