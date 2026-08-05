"""Oberflaeche, ein Modul je Bereich.

Die Abhaengigkeiten laufen von `basis` (kennt keinen Bereich) nach aussen.
Wo zwei Bereiche einander brauchen -- Buchungen, Dialog, Kalender, Reinigung --
wird das jeweils andere Modul als Objekt importiert und der Name erst beim
Aufruf nachgeschlagen; ein `from X import name` wuerde sich beim Laden im Kreis
drehen.
"""
