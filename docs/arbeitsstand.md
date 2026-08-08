# Arbeitsstand

Wo wir gerade stehen. Der *Plan* steht in `docs/roadmap.md` — hier steht der
*Tagesstand*: was gerade läuft, was geprüft wurde, was noch aussteht. Am Ende
einer Arbeitssitzung nachziehen.

**Stand: 7. August 2026**

## Wofür die Buchhaltung im Werkzeug da ist (festgelegt 7.8.2026)

**Nicht für das Finanzamt.** Steuererklärung, Umsatzsteuer-Voranmeldung und EÜR
macht der Steuerberater. Das Werkzeug gibt einen **aktuellen Überblick**: was
kommt rein, was geht raus, was bleibt — je Monat und je Wohnung.

**Der Anlass ist der Verzug**: der Steuerberater hinkt gelegentlich acht bis
zehn Monate hinterher, so lange ist der Betrieb im Blindflug. Heute füllt ein
Excel-Workbook diese Lücke, von Hand und auch nur bis zum 30.6.

Das hat Phase 7 spürbar verkleinert: die USt-Voranmeldung als Formular, die
GoBD-Verfahrensdokumentation, das Anlagenverzeichnis und die Feinheiten des
§ 13b sind entfallen. Ein Überblick muss stimmen, aber nicht prüfungsfest sein.

**Zweiter Zweck, ergänzt am 7.8.2026: das Sammeln und Übergeben.** Am Ende
bekommt der Steuerberater alle Belege; gesammelt wird im Werkzeug, abgelegt in
der Nextcloud. Damit ist **AP18 kein Anhängsel mehr, sondern der zweite
Ausgang** — und Vollständigkeit (AP25) wird zur Pflicht statt zur Kür. Neu
dazu: **AP27 Vorkontierung** (Konto, Steuerschlüssel, Belegfeld, Kostenstelle).

Zwei der vier Belegströme fehlen noch ganz: **Kontoauszüge** (kommt mit AP16)
und **Portalabrechnungen** (AP23).

**AP27 ist nicht mehr blockiert (7.8.2026): kein Kontenrahmen.** Kein SKR03,
kein SKR04, keine DATEV-Nummern — die Vorkontierung macht der Betreiber selbst.
Stattdessen **eigene Kategorien in den Einstellungen** und eine Auswertung
darüber: „wie viel für Putzmittel, wie viel für Gastgeschenke". Der Anschluss
fehlt nur halb — `buchhaltung.kategorien()` liest eigene Kategorien schon aus
der Konfiguration, es gibt bloß keine Oberfläche dafür; die Auswertung je
Kategorie gibt es gar nicht.

**E-Rechnung (AP28) — die Empfangsseite ist kein Zukunftsthema.** Strukturierte
Rechnungen entgegennehmen zu können, ist seit 1.1.2025 Pflicht; das Werkzeug
kann es nicht (alles läuft durch die OCR). Zugleich ist es eine Abkürzung: aus
dem eingebetteten XML kommen Lieferant, Netto, Steuersatz und Steuerbetrag
exakt — genau die Felder von AP19. **AP19 und AP28a gehören deshalb zusammen
gebaut.** Das Senden betrifft nur Geschäftskunden und gilt für diesen Betrieb
ab 1.1.2028; Vorschlag ZUGFeRD (PDF mit XML) statt reiner XRechnung, damit das
gesetzte Layout erhalten bleibt. Fristen vom Steuerberater bestätigen lassen.

**Damit ist eine verworfene Entscheidung wieder offen:** „Belege aus dem
Postfach holen" wurde am 7.8. mit der Begründung verworfen, Hochladen genüge.
Für E-Rechnungen stimmt das nicht mehr — sie kommen per Mail, und ein Foto
davon ist keine E-Rechnung. Drei Wege stehen bei AP28a im Fahrplan zur Wahl
(Postfachabruf, Datei-Upload statt Foto, eigene Sammeladresse); zu entscheiden,
bevor AP28a gebaut wird.

## Wo die Buchhaltung steht (Prüfung vom 7.8.2026)

**Fertig:** Ausgangsrechnungen aus der Buchung (AP14) samt PDF · Belege mit
Kategorie und Kreditor (AP10/AP13/AP15) · Beherbergungssteuer-Anmeldung (AP11)
· Monatsabschluss und CSV in den acht Spalten des Kontenjournals.

**Es fehlt die halbe Kette.** Nachgeprüft im Code, nicht vermutet: Vorsteuer je
Beleg, Umsatzsteuer-Voranmeldung, Zahlungsabgleich (eine Rechnung kennt keinen
Status „bezahlt"), Reverse-Charge § 13b, Anlagevermögen/AfA/Darlehen. Und die
Reihenfolge stimmte nicht: Die EÜR ist eine **Zufluss-/Abfluss**-Rechnung, das
Werkzeug bucht aber nach Beleg- und Rechnungsdatum — die Kontobewegungen sind
deshalb das Fundament der EÜR, kein Paket daneben.

**Zweiter Durchgang, weil der erste zu kurz griff:** Er sah nur auf die
Ausgabenseite. Die größte Lücke liegt bei den **Erlösen** — „Provision" kommt
im Code nicht vor. Airbnb und Booking zahlen **netto** aus; bucht man den
Eingang als Erlös, ist die EÜR auf *beiden* Seiten zu niedrig (Erlös um die
Provision, Ausgabe um denselben Betrag). Dazu: Dauerbelege haben nur ein
Textfeld, ein Übernahmestichtag gegen das Workbook fehlt, und niemand merkt
eine Lücke im Bank-CSV.

Neu geordnet als **Phase 7** im Fahrplan. Alles läuft in **AP20**
(Zahlungsabgleich) zusammen — das ist das schwerste Paket, nicht die EÜR.

**Entschieden am 7.8.2026: Ist-Versteuerung, keine Barzahlungen.** Damit hängt
die Umsatzsteuer am Zahlungseingang — die Voranmeldung (AP21) setzt den
Zahlungsabgleich (AP20) voraus. Kein Kassenbuch nötig; weil jeder Erlös über
die Bank läuft, ist der Kontoimport auch das Fundament der Umsatzsteuer.

**Der Punkt, an dem es schiefgehen kann:** Die Ist-Versteuerung betrifft nur die
eigene Umsatzsteuer. Der **Vorsteuerabzug** hängt am Rechnungseingang, nicht an
der Zahlung. Die Voranmeldung zieht also aus zwei verschiedenen Stichtagen —
das gehört vom Steuerberater bestätigt, bevor AP21 gebaut wird.

## Offen — braucht eine Entscheidung

**Dezember-Anmeldung: erledigt, wird NICHT berichtigt** (entschieden 7.8.2026).
Eingereicht wurden 5.698,29 € / 341,90 €; nach der Regel von AP14c wären es
5.652,71 € / 339,16 € — 2,74 € zu viel gezahlt. „Was vergangen ist, ist
vergangen." Der eingereichte Stand bleibt in `tests/test_steuer.py`
dokumentiert, damit die Abweichung später erklärbar ist.

**Die Wernerstraße rechnet gegenüber dem Gast weiter mit 7 %.** Auf unsere
Zahlen wirkt sich das nicht mehr aus, auf die Gäste schon — sie zahlen zu viel.
Die Einstellung gehört in Smoobu/Booking.com auf 6 % korrigiert.

## Gerade erledigt

**AP16: Kontobewegungen werden eingelesen.** Neuer Bereich „Konto" —
DKB-Business und DKB-VISA, Summen je Monat, Bewegungsliste. Gebaut gegen die
echten Exporte vom 24.7., dadurch zwei Funde: die zweistellige Jahreszahl
(`24.07.26`) und der **Kreditkarten-Ausgleich, der in beiden Auszügen steht** —
wer beide einliest, zählt die Kartenkäufe sonst doppelt. Er gilt jetzt als
Umbuchung zwischen eigenen Konten und bleibt aus den Summen draußen.

Ein zweiter Import erzeugt keine Dubletten (Fingerabdruck statt laufender
Nummer) und lässt eigene Zuordnungen in Ruhe. In der Probe-Instanz liegen die
echten 193 Bewegungen aus Januar bis Juli 2026.

**AP24: die Bewegungen werden erkannt.** Entschieden anhand der echten Daten —
76 % der Ausgänge gehen an immer denselben Empfänger, und drei der größten
Posten sind gar keine Betriebsausgaben (Privatentnahme, abgeführte
Beherbergungssteuer, Darlehenstilgung). Die Oberfläche zeigt jetzt **Geldfluss
und Ergebnis getrennt**; über das erste Halbjahr liegen dazwischen 6.181 €.

154 von 193 Bewegungen erkannt, **39 Ausgänge warten noch auf eine Zuordnung** —
die Anzeige sagt das, statt ein fertiges Ergebnis vorzutäuschen.

> **Gegenprobe:** Januar–Juni 2026 ergibt **6.235,60 €** gegen **6.048,85 €**
> im Workbook — 3,1 % Unterschied, bei 33 offenen Ausgängen, ungetrennter
> Tilgung und fehlender Abschreibung. Der Weg trägt.

**AP15 Schritt 1: die Beleg-Zuordnung lernt.** Setzt man die Kategorie eines
Belegs von Hand, merkt sich das der Kreditor — beim nächsten Beleg desselben
Händlers steht sie schon da. Trifft kein vorhandener Kreditor, entsteht einer
mit `quelle="gelernt"`; das Muster ist der normalisierte Händlername, damit
„BAUHAUS 4711" und „Bauhaus GmbH" derselbe Lieferant bleiben. Eine **gepflegte**
Kategorie wird nicht überschrieben — sonst kippte ein falsch zugeordneter Beleg
die Stammdaten. Der Kreditor steht jetzt auch am Beleg (`kreditor_id`).

Offen in AP15: Kreditor am Beleg sichtbar und änderbar (Schritt 2), Kostenstelle
als eigenes Feld für Verwaltungskosten ohne Wohnung (Schritt 3).

**Von Smoobu wird nur noch der Gesamtbetrag geglaubt (AP14c).** Die
Beherbergungssteuer wurde übernommen, wenn Smoobu sie auswies — Booking.com
rechnet sie auf denselben zwei Wohnungen aber nach drei verschiedenen Formeln
(76× 6 % ohne Reinigung in der Basis, 37× richtig, 18× 7 %). Dadurch nannten
Gastrechnung und Steueranmeldung verschiedene Zahlen; über 135 Buchungen waren
das 263,31 €, die in keiner von beiden vorkamen. Jetzt wird die Steuer gerechnet
(`price / 1,06`), und für jede Buchung gilt: Basis + Steuer = Rechnungsbetrag
und Steuer = 6 % der Basis.

**Die Rechnung ist umgestellt (AP14b).** Der Aufbau folgt der abgestimmten
Vorlage `Beispielrechnung_B2B_Ferienzimmer` — Logo oben links, Anbieterdaten
oben rechts, Anschriftfeld, Titel mit Nummer und Datum daneben, Block
Aufenthalt/Gast/Zeitraum, Aufstellung mit Netto/USt./Brutto, Zwischensumme
„Beherbergungsleistungen", Beherbergungssteuer, Gesamtbetrag,
Steuerinformation, Hinweis, Fußzeile aus drei Spalten. **Nur der Aufbau, nicht
die Gestaltung**: keine farbigen Flächen, die Hausfarbe nur für Titel und
Gesamtbetrag.

Die Abstände folgen jetzt **DIN 5008 Form A**. Zwei Abweichungen waren drin:
linker Rand 22 statt 24,1 mm, und die Empfängeranschrift begann auf 50,7 mm
statt in der Anschriftzone ab 44,7 mm — im Fensterumschlag saß sie zu tief.
Ein **Logo** lässt sich unter Einstellungen → Betreiber hochladen.

Dabei zwei technische Funde: `insert_text` kodierte nach Latin-1 und machte aus
„€" still einen Punkt (daher stand „EUR" auf der Rechnung) — geschrieben wird
jetzt mit `fitz.TextWriter`. Und weil der nur eine Farbe je Durchgang kann,
hätte eine Gruppierung nach Farbe die Lesereihenfolge im PDF zerstört.

Die Beträge stammen weiter aus `rechnung.summen()`, also aus der Summe der
**einzeln gerundeten** Positionen. Aus 765,93 direkt gerechnet kämen 50,11 und
715,82 heraus – ein Cent Unterschied. Richtig ist der Weg über die Positionen,
weil die Rechnung genau diese Positionen ausweist.

**„Entwürfe suchen" unter Rechnungen legte keine Entwürfe an.** Zwei Fehler
hintereinander, beide inzwischen behoben:

1. Der Rückblick betrug einen Tag statt 90 (Commit `6791e6d`) — von 48
   abgereisten Buchungen war eine erreichbar.
2. Der Knopf holte die Buchungen über die **Reinigungsliste**
   (`ui_buchungen._cleaning_jobs`). Die reicht sie durch
   `bookings.normalize()`, und das wirft `price`, `price-details`, `created-at`
   und das verschachtelte `apartment` weg. `rechnung.aufteilung()` fand keinen
   Betrag und brach ab — bei *jeder* Buchung, lautlos. Die Rechnungssuche holt
   ihre Buchungen jetzt selbst roh über `data._reservations()`, und was sie
   nicht verarbeiten kann, benennt sie ("5 übersprungen: 4× keine
   Reinigungsgebühr hinterlegt").

Warum das keiner gemerkt hat: `faellige_buchungen` wurde mit Attrappen geprüft,
`entwurf_fuer` mit echten Smoobu-Daten. Beide Hälften waren richtig, die Naht
dazwischen prüfte nichts. Es gibt jetzt zwei Tests, die den Knopf **wirklich
anklicken** (`test_der_knopf_legt_wirklich_entwuerfe_an`,
`test_uebersprungene_buchungen_sagen_warum`) — gegengeprüft, sie fallen ohne die
Korrektur durch.

**Ausgangsrechnung neu aufgeteilt.** Anlass: das Steuerbüro musste den
eigentlichen Rechnungsbetrag (Netto + USt) für jede Rechnung selbst bilden.
Neu auf dem PDF: Zwischensumme der Leistung, „nicht steuerbar" statt des
falschen „steuerfrei", und ein Steuernachweis-Block wie in der Hotelbranche
üblich. `tests/test_rechnung_pdf.py` ist neu — das Modul war vorher ungeprüft.
Details und Begründung: README → „Was auf der Ausgangsrechnung steht".

## Offen / ausstehend

* **7 Commits sind weder gepusht noch ausgerollt.** Im Echtbetrieb
  (app.ds-apartments.de) fehlen damit unter anderem der 90-Tage-Rückblick, der
  Rechnungs-Fix, die Lohn-Vorschau und AP14. Nächster Schritt: `git push` +
  `tools/deploy.sh`.
* **Am echten Bestand noch nicht geprüft:** wie viele der 48 abgereisten
  Buchungen nun tatsächlich einen sauberen Entwurf ergeben und welche Befunde
  übrig bleiben. Erwartung aus dem Gegentest vom 7.8.: von 219 Buchungen teilen
  sich 186 sauber auf; die Ausreißer sind Datenfunde, keine Rechenfehler.
* **Wernerstraße rechnet 7 % Beherbergungssteuer statt 6 %** — im README seit
  längerem als offen vermerkt, am 7.8.2026 nachgemessen: unverändert offen,
  26 von 45 Buchungen der letzten 90 Tage betroffen, jüngste Abreise 9.8.2026.
  Die Gäste zahlen dort zu viel, abgeführt werden korrekt 6 %. Zu korrigieren
  ist die Einstellung **in Smoobu/Booking.com**, nicht im Code. Solange offen,
  steht auf der Rechnung bewusst kein Prozentsatz.
* **B4b ist fertig (8.8.2026):** Verrechnungskonto je Plattform, als Karte im
  Bereich Konto. Am Probe-Bestand erkannt: 44 Booking- und 7 Airbnb-Eingänge
  über 32.251 €. Der Saldo steht dort fast in voller Höhe offen, weil bisher
  nur zwei Rechnungen zugeordnet sind — richtig so, das ist die Aussage.
  Zwei Teile des Konzepts bewusst **nicht** gebaut: die „offene Forderung je
  Plattform" (der Vertriebskanal steht nicht an der Rechnung) und die Anzeige
  der Monatsprobe (braucht den Betrag vom Monatsbeleg, kommt mit B5).
  Begründung jeweils in `docs/konzept-bankbuchhaltung.md`.
* **B5 ist fertig (8.8.2026):** Belege und Bankbewegungen finden zueinander –
  aus der Bewegung ein vorhandener Beleg, aus dem Beleg die Bewegung, ein Beleg
  auf mehreren Bewegungen (Monatsbeleg der Portale), Dublettenwarnung beim
  Hochladen, und im Belege-Bereich der Filter „ohne Bewegung". Dabei zwei
  bestehende Fehler behoben: ein Beleg löschte die Aufteilung einer Zahlung,
  und an einer Portal-Auszahlung buchte er den Umsatz statt der Provision (der
  zweite fiel erst an den echten Daten auf). Die Monatsprobe aus B4b ist damit
  anzeigbar. Nach der ersten Benutzung nachgebessert: Mehrfach-Upload (bis 30
  Dateien) und Suche statt Deckel in beiden Zuordnungsmasken.
* **Belegerkennung berichtigt (8.8.2026)** — nach dem ersten großen Upload
  gemeldet: eine Lexware-Rechnung stand als „Netto 34,80 €" in der Liste. Der
  Bankvorgang „Netto 34,80 €" passte scheinbar dazu. Nachgemessen an 31
  Belegen: **13 hießen „Netto"**, weil `NETTO` in der Händlerliste stand und
  als Teilzeichenkette im ganzen Dokument gesucht wurde — auf jeder Rechnung
  steht „Nettobetrag", in jeder Tabelle „Netto" als Spaltenkopf. **5** trugen
  die Seitenzahl („1/2") als Händler, **13 Beträge waren Datumsangaben**
  (31,12 = 31.12.). Beim Lexware-Beleg kam beides zusammen: 34,80 war der
  *Nettoanteil*, zu zahlen waren 41,41.
  Ergebnis nach der Korrektur: falsche „Netto" 15 → 0, Seitenzahlen 5 → 0,
  Datum-als-Betrag 13 → 0; Belege, deren Betrag exakt eine Bankbewegung trifft,
  **6 → 14 von 31**. Für die bereits hochgeladenen Belege gibt es im
  Belege-Bereich den Knopf „*n* Belege neu auslesen" mit Vorschau; von Hand
  gepflegte Angaben bleiben unangetastet.
* **Nächstes Paket: B6** — Kategorien an der Zuordnung statt an der Bewegung.
* **Ältere Arbeitspakete:** AP15 (Eingangsrechnungen mit Kreditor und
  Kostenstelle), AP16 (Kontoauszug einlesen), AP17 (EÜR im Werkzeug), AP18
  (Ablage in der Nextcloud) — Beschreibung in `docs/roadmap.md`.

## Wie geprüft wird

```bash
.venv/bin/python -m pytest -q     # 956 Tests, Stand 8.8.2026 grün
tools/probelauf.sh                # Port 3002 — nach Codeänderung NEU STARTEN
```
