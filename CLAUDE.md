# LIVARO (Repo: `rentaltool`)

Verwaltungswerkzeug für die Ferienwohnungen der DS Apartments Dresden:
Beherbergungssteuer, Reinigung, Zeiterfassung, Belege, Rechnungen, Buchhaltung.
NiceGUI (reines Python), SQLite, keine Node-Toolchain.

## Erst hier nachsehen

| Frage | Steht in |
|---|---|
| **Woran arbeiten wir gerade?** | `docs/arbeitsstand.md` |
| **Was ist geplant, was ist fertig?** | `docs/roadmap.md` |
| Wie funktioniert Bereich X? | `README.md` (ausführlich, nach Bereichen gegliedert) |

## Hausregeln

**Arbeitspakete gehören in `docs/roadmap.md`, nicht in den Chat.** Ein neues
Paket wird dort *vor* der Umsetzung eingetragen und danach dort abgehakt. Ein
Chat kann abbrechen, das Repository nicht. Genauso wird `docs/arbeitsstand.md`
am Ende einer Arbeitssitzung nachgezogen — offene Fragen, was zuletzt geprüft
wurde, was noch nicht gepusht oder deployt ist.

**Tests laufen mit dem venv-Python**, nicht mit dem System-`python3`:

```bash
.venv/bin/python -m pytest -q          # Stand 7.8.2026: 703 Tests
```

**Ein Test, der auch ohne die Korrektur grün ist, ist kein Test.** Bei einem
Fehlerbericht immer gegenprüfen (`git stash` auf die geänderte Datei, Test
laufen lassen, er muss durchfallen). Der Fehler vom 7.8.2026 in „Entwürfe
suchen" saß in der *Naht* zwischen zwei Bausteinen, die einzeln beide geprüft
und einzeln beide richtig waren.

**Sprache:** Oberfläche, Kommentare, Dokumentation und Commit-Botschaften auf
Deutsch. Kommentare erklären das *Warum*, nicht das Was.

## Starten

```bash
./run-local.sh          # Echt-Konfiguration, Port 3001
tools/probelauf.sh      # Probe-Instanz, Port 3002, eigener Datenordner
tools/probelauf.sh --von-live   # ... gefüllt mit entschärften Live-Daten
```

Die Probe-Instanz (`RENTALTOOL_STAGING=1`) sperrt Mailversand, Gast-Nachrichten
und den Nextcloud-Spiegel. **Sie lädt den Code beim Start** — nach einer
Änderung neu starten, sonst prüft man den alten Stand.

## Aufbau in einem Absatz

Fachlogik in `app/`, Oberfläche in `app/ui/` mit einem Modul je Bereich. Die
Abhängigkeiten laufen von `app/ui/basis.py` (kennt keinen Bereich) nach außen.
Betriebsdaten liegen **getrennt vom Code** (`app/paths.py`, im Betrieb
`/var/lib/rentaltool`, Umgebungsvariable `RENTALTOOL_DATA`). Jeder Dateizugriff
geht über `app/store.py` (atomar, gesperrt). Details: `README.md` → Architektur.

**Stolperstein:** `bookings.normalize()` reicht Buchungen abgespeckt weiter —
ohne `price`, `price-details`, `created-at` und das verschachtelte `apartment`.
Für die Reinigungsliste reicht das, für Rechnungen und Steuer nicht. Wer Beträge
braucht, holt die Rohdaten über `data._reservations()`.

## Betrieb

Live: <https://app.ds-apartments.de> · SSH-Alias `rentaltool` · Code in
`/opt/rentaltool` · Ausrollen mit `tools/deploy.sh` (Tests, Rauchprobe,
automatischer Rückweg). Nächtliche Sicherung in die Nextcloud per systemd-Timer.
