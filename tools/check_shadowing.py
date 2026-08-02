#!/usr/bin/env python3
"""Findet Überschattungen von Modulnamen – vor allem der Übersetzungsfunktion `t`.

Hintergrund: In `reinigung_putzkraft` hieß die Aufgaben-Variable `t`
(`for t in all_tasks:`). Python macht `t` damit in der GANZEN Funktion lokal –
auch oberhalb der Schleife. Der Aufruf `t("Check-out")` weiter oben warf
deshalb `UnboundLocalError`, und die Checkliste stürzte genau auf dem Normalweg
ab (aus einer Buchung geöffnet). Kein Test hat das bemerkt.

Gemeldet wird je Funktion:
  FEHLER  – der Name wird BENUTZT, bevor er lokal gebunden wird
            -> UnboundLocalError zur Laufzeit.
  WARNUNG – der Name überschattet einen Modulnamen, wird aber erst nach der
            Bindung benutzt (z. B. `tl = i18n.tl`) oder gar nicht.

Aufruf:  python3 tools/check_shadowing.py [datei ...]
Exit 1, sobald ein FEHLER gefunden wurde.
"""
import ast
import os
import sys


def _modulnamen(baum):
    """Auf Modulebene gebundene Namen (Importe, def/class, Zuweisungen)."""
    namen = set()
    for knoten in baum.body:
        if isinstance(knoten, (ast.Import, ast.ImportFrom)):
            for a in knoten.names:
                namen.add((a.asname or a.name).split(".")[0])
        elif isinstance(knoten, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            namen.add(knoten.name)
        elif isinstance(knoten, ast.Assign):
            for ziel in knoten.targets:
                if isinstance(ziel, ast.Name):
                    namen.add(ziel.id)
    return namen


class _Scope(ast.NodeVisitor):
    """Sammelt lokale Bindungen und Nutzungen EINER Funktion.

    Verschachtelte Funktionen, Lambdas und Comprehensions haben in Python 3
    einen eigenen Gültigkeitsbereich und werden übersprungen – ihre Namen
    beeinflussen die äußere Funktion nicht.
    """

    def __init__(self, fn):
        self.fn = fn
        self.bindung = {}     # name -> erste Zeile der Bindung
        self.nutzung = {}     # name -> erste Zeile der Nutzung

    def _bind(self, name, zeile):
        if name not in self.bindung or zeile < self.bindung[name]:
            self.bindung[name] = zeile

    def _nutze(self, name, zeile):
        if name not in self.nutzung or zeile < self.nutzung[name]:
            self.nutzung[name] = zeile

    def visit_FunctionDef(self, node):
        if node is not self.fn:
            self._bind(node.name, node.lineno)      # def X() bindet X lokal
            return
        for a in (node.args.args + node.args.kwonlyargs + node.args.posonlyargs
                  if hasattr(node.args, "posonlyargs") else
                  node.args.args + node.args.kwonlyargs):
            self._bind(a.arg, node.lineno)
        for kind in node.body:
            self.visit(kind)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node):
        return

    def visit_ListComp(self, node):
        return

    visit_SetComp = visit_DictComp = visit_GeneratorExp = visit_ListComp

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self._bind(node.id, node.lineno)
        else:
            self._nutze(node.id, node.lineno)

    def visit_ExceptHandler(self, node):
        if node.name:
            self._bind(node.name, node.lineno)
        self.generic_visit(node)

    def visit_Import(self, node):
        for a in node.names:
            self._bind((a.asname or a.name).split(".")[0], node.lineno)

    visit_ImportFrom = visit_Import


def pruefe(pfad):
    baum = ast.parse(open(pfad, encoding="utf-8").read(), filename=pfad)
    modul = _modulnamen(baum)
    fehler, warnungen = [], []
    for fn in ast.walk(baum):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        s = _Scope(fn)
        s.visit(fn)
        for name, bzeile in sorted(s.bindung.items()):
            if name not in modul:
                continue                       # überschattet nichts
            nzeile = s.nutzung.get(name)
            if nzeile is None:
                continue                       # gebunden, nie gelesen: egal
            if nzeile < bzeile:
                fehler.append((pfad, fn.name, name, nzeile, bzeile))
            else:
                warnungen.append((pfad, fn.name, name, bzeile))
    return fehler, warnungen


def main(argv):
    hier = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dateien = argv[1:] or [os.path.join(hier, "app", f)
                           for f in sorted(os.listdir(os.path.join(hier, "app")))
                           if f.endswith(".py")]
    fehler, warnungen = [], []
    for f in dateien:
        fe, wa = pruefe(f)
        fehler += fe
        warnungen += wa

    for pfad, fn, name, nzeile, bzeile in fehler:
        print(f"FEHLER  {os.path.basename(pfad)}:{nzeile} in {fn}(): '{name}' wird "
              f"benutzt, aber erst in Zeile {bzeile} lokal gebunden "
              f"-> UnboundLocalError")
    for pfad, fn, name, bzeile in warnungen:
        print(f"WARNUNG {os.path.basename(pfad)}:{bzeile} in {fn}(): "
              f"'{name}' überschattet den Modulnamen")
    print(f"\n{len(fehler)} Fehler, {len(warnungen)} Warnungen "
          f"in {len(dateien)} Dateien")
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
