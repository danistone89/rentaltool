# Konzept: Bankbuchhaltung in LIVARO

**Stand:** 8.8.2026 · zur Prüfung, noch nicht umgesetzt

---

## 1. Das Zielbild

LIVARO soll den **Überblick über die Zahlen** geben — bedient wie lexoffice:

* **Einnahmen** entstehen aus den Smoobu-Buchungen als Ausgangsrechnungen.
* **Ausgaben** kommen als Eingangsbelege dazu.
* In der Mitte stehen die **Bankbewegungen**, importiert als CSV — Girokonto
  und Kreditkarte.
* Belege beider Seiten werden den Bankbewegungen **zugeordnet**.
* Eine Auszahlung von Booking oder Airbnb über mehrere tausend Euro muss
  **mehreren Ausgangsrechnungen** zugeordnet werden können.
* Weil die **Provision nicht in der Auszahlung** steckt, muss der
  Provisionsbeleg des Portals **gegen dieselbe Zahlung** gebucht werden.
* Wie in DATEV: einer Zahlung lassen sich **mehrere** Kosten oder Einnahmen
  zuordnen.
* Überweist ein Gast **1:1 den Rechnungsbetrag**, muss die Zuordnung mit einem
  Griff gehen.
* Jeder Bankvorgang bekommt eine **Kategorie**, konfigurierbar in den
  Einstellungen — „Einnahmen Airbnb", „Einnahmen Booking", „Putzmittel",
  „Gastgeschenke".

---

## 2. Was heute schon steht

Gebaut am 7./8.8.2026, Branch `buchhaltung/konto-und-rechnung`:

| Baustein | Stand |
|---|---|
| **Ausgangsrechnung aus der Buchung** (AP14) | Entwurf → Festschreiben → PDF → Versand, Nummernkreis je Jahr |
| **Rechnungslayout** (AP14b) | Aufbau der abgestimmten Vorlage, DIN 5008, Logo |
| **Beherbergungssteuer selbst rechnen** (AP14c) | Von Smoobu gilt nur der Gesamtbetrag |
| **Bankbewegungen** (AP16) | DKB-Giro **und** VISA als CSV, Dubletten, Umbuchungen erkannt |
| **Erkennung** (AP24) | Kreditor am Empfänger, Klasse entscheidet über das Ergebnis |
| **Kategorien** (AP27a) | Eigene anlegen, umbenennen (samt Sätzen), löschen |
| **Beleg an der Buchung** (AP20 Schritt 1) | Hochladen, lösen, abhaken; Liste „fehlt noch" |
| **Belege** (AP10) | Upload durch Mitarbeiter, OCR, Kategorie — **ohne Bezug zum Konto** |

Das Fundament trägt. Was fehlt, ist die Mitte: die **Zuordnung**.

---

## 3. Der Bruch: das heutige Datenmodell trägt das Zielbild nicht

Eine Bewegung hat heute **je ein Feld**:

```python
bewegung = { …, "beleg_id": "…", "rechnung_id": "…", "kategorie": "…" }
```

Das ist eine **1:1-Beziehung**. Damit lässt sich nicht ausdrücken:

* eine Airbnb-Auszahlung über 1.794,13 € für **fünf** Buchungen,
* **plus** den Provisionsbeleg, der dagegen gerechnet wird,
* jeweils **mit eigenem Betrag**.

**Das ist der eine Umbau, der vor allem anderen kommen muss.** Jede weitere
Funktion, die auf `beleg_id` aufsetzt, müsste später zurückgebaut werden.

### Das neue Modell: die Zuordnung wird ein eigener Satz

```python
zuordnung = {
    "id":          "…",
    "bewegung_id": "…",          # welche Bankbewegung
    "art":         "rechnung" | "beleg" | "kategorie",
    "ziel_id":     "…",          # Rechnung, Beleg – oder leer bei „nur Kategorie"
    "kategorie":   "…",          # immer gesetzt, auch bei Rechnung/Beleg
    "betrag":      123.45,       # Teilbetrag, Vorzeichen wie die Bewegung
    "notiz":       "",
}
```

Daraus folgt alles Weitere:

* **Restbetrag** = Bewegungsbetrag − Summe der Zuordnungen. Er steht sichtbar
  daneben, wie in DATEV und lexoffice.
* **Fertig** ist eine Bewegung, wenn der Rest **0,00 €** ist.
* Ein 1:1-Fall ist der Sonderfall mit genau einer Zuordnung — nicht ein
  eigener Mechanismus.
* Die **Provision** ist eine Zuordnung mit umgekehrtem Vorzeichen: die Summe
  der Rechnungen ist größer als die Auszahlung, die Differenz ist die
  Provision, und erst mit ihr geht der Rest auf null.

### Beispiel: eine Airbnb-Auszahlung

```
Bankbewegung  12.01.2026   +1.794,13 €   Airbnb
├─ Rechnung 41  Meier      +  620,00 €   Einnahmen Airbnb
├─ Rechnung 42  Schulz     +  540,00 €   Einnahmen Airbnb
├─ Rechnung 43  Kowalski   +  780,00 €   Einnahmen Airbnb
└─ Beleg: Airbnb-Provision −  145,87 €   Portalprovision
                            ─────────────
   Rest                        0,00 €  ✓
```

Erst diese Aufteilung zeigt den **echten Umsatz** (1.940,00 €) und die
**Provision als Ausgabe** (145,87 €). Bucht man nur die Auszahlung, ist beides
zu niedrig — das Ergebnis stimmt zufällig, die Zahlen nicht.

---

## 4. Die vier Fälle — an den echten Daten gezählt

Aus 193 eingelesenen Bewegungen (Januar bis Juli 2026):

| Fall | Anzahl | Erkennungsmerkmal |
|---|---:|---|
| **Booking**, je Reservierung | 44 Eingänge | `ID.14005823` im Verwendungszweck |
| **Airbnb**, Sammelauszahlung | 7 Eingänge | Verwendungszweck nutzlos („AWV-MELDEPFLICHT") |
| **Direktzahler** | 8 Eingänge | Gastname im Verwendungszweck („Buchung Katarina Gockel") |
| **Ausgaben mit Beleg** | 122 Ausgänge | Empfänger → Kreditor (steht schon) |

### Der Befund, der die automatische Erkennung entscheidet

> **Von 65 Zahlungseingängen entspricht genau EINER exakt einem
> Rechnungsbetrag.**

Der naheliegende Weg — „gleicher Betrag, also dieselbe Rechnung" — trifft in
**1,5 %** der Fälle. Grund: Booking und Airbnb zahlen **netto nach Provision**
aus, der Betrag kann gar nicht stimmen.

Brauchbar ist stattdessen:

* **Booking:** die Reservierungsnummer aus dem Verwendungszweck. *Zu prüfen:
  steht sie so auch in den Smoobu-Daten?* — das ist der erste Rechercheschritt.
* **Direktzahler:** der Gastname im Verwendungszweck gegen den Gast der
  Rechnung. Bei „Buchung Katarina Gockel Cottaer Straße" eindeutig.
* **Airbnb:** aus der Bewegung heraus gar nicht. Nötig ist die
  **Auszahlungsübersicht** (earnings-PDF) oder die Auswahl von Hand.

**Konsequenz fürs Konzept:** Die Zuordnung ist in erster Linie **bedient**, in
zweiter automatisch. Ein Vorschlag darf nie still buchen — was nicht eindeutig
ist, bleibt offen.

---

## 5. Die Arbeitspakete

Neu geschnitten als Reihe **B** (Bankbuchhaltung). Sie lösen die bisherigen
Pakete AP20, AP23 und AP25 ab; AP17/AP21/AP22/AP26 bleiben unverändert
bestehen.

### B1 · Die Zuordnung als eigener Satz — *Fundament*

Neue Tabelle `zuordnungen`, Restbetrag-Rechnung, Übernahme der heutigen
1:1-Felder (`beleg_id`) in das neue Modell. Ohne Oberfläche.
**Alles Weitere hängt daran.** · *Größe:* M

### B2 · Die Zuordnungsmaske

Eine Bewegung aufklappen, Posten hinzufügen, Restbetrag mitlaufen sehen,
speichern erst wenn er null ist — oder bewusst offen lassen. Der Bildschirm,
an dem die tägliche Arbeit stattfindet. · *Größe:* L

### B3 · Ausgangsrechnungen zuordnen

Rechnungen suchen und auswählen; Vorschläge über Gastname und
Reservierungsnummer (**nicht** über den Betrag, siehe oben). Die Rechnung wird
damit **bezahlt** und trägt ein Zahlungsdatum. · *Größe:* L

### B4 · Portalprovision gegenbuchen

Provisionsbeleg als Gegenposten auf dieselbe Zahlung. Erst damit stimmen Umsatz
und Ausgaben. Einschließlich der Frage, woher der Provisionsbeleg kommt
(Booking-Rechnung, Airbnb-Auszahlungsübersicht). · *Größe:* M

### B5 · Eingangsbelege zuordnen — und die beiden Wege zusammenführen

Heute laufen **Belege** (Mitarbeiter-Upload) und **Konto** nebeneinander: ein
fotografierter Beleg bleibt für das Konto unsichtbar, und derselbe Beleg kann
zweimal im System landen. Nötig: aus der Bewegung einen vorhandenen Beleg
auswählen, aus dem Beleg die passende Bewegung, und eine Dublettenprüfung über
beide Wege. · *Größe:* L

### B6 · Kategorien an jeder Bewegung

Anlegen und pflegen steht (AP27a). Es fehlen die **Einnahmen-Kategorien**
(„Einnahmen Booking", „Einnahmen Airbnb", „Einnahmen Direktbuchung") und die
Kategorie an der **Zuordnung** statt an der Bewegung — bei einer Sammelzahlung
kann jeder Posten eine andere haben. · *Größe:* S

### B7 · Der Überblick

Einnahmen, Ausgaben, Ergebnis je Monat und Wohnung, dazu **je Kategorie** —
„wie viel ging für Putzmittel drauf". Ersetzt das, was heute das Workbook von
Hand liefert. *(war AP17 + zweite Hälfte AP27)* · *Größe:* L

### B8 · Vollständigkeit

Saldo-Abgleich gegen den Kontoauszug, lückenlose Zeiträume, Liste der
Bewegungen mit Restbetrag ≠ 0 und der fehlenden Belege. *(war AP25)*
· *Größe:* M

### B9 · Übergabe ans Steuerbüro

Ablage in der Nextcloud nach Jahr und Monat, sprechende Dateinamen,
Belegnummer auf Dokument **und** Buchung. *(war AP18)* · *Größe:* L

### Reihenfolge

```
B1 ──► B2 ──► B3 ──► B4 ──┐
        │                  ├──► B7 (Überblick)
        └──► B5 ──► B6 ────┘
                           └──► B8 ──► B9
```

**B1 und B2 sind der Kern.** Danach ist das Werkzeug bedienbar wie ein
lexoffice; B3–B6 füllen die Fälle, B7–B9 sind Ernte und Übergabe.

---

## 6. Was aus dem alten Plan entfällt

* **AP20** geht in B1–B5 auf (Schritt 1 ist gebaut und wird nach B1 überführt).
* **AP23** wird zu B4.
* **AP25** wird zu B8, **AP18** zu B9.
* **AP19/AP28** (Vorsteuer, E-Rechnung) bleiben liegen, bis die Zuordnung
  steht — sie betreffen den Beleg, nicht die Zahlung.

## 7. Offene Fragen vor dem Bau

1. **Steht die Booking-Reservierungsnummer aus dem Verwendungszweck auch in
   den Smoobu-Daten?** Davon hängt ab, ob 44 der 65 Eingänge automatisch
   vorgeschlagen werden können oder von Hand laufen.
2. **Woher kommt der Provisionsbeleg?** Stellt Booking eine monatliche
   Rechnung, oder muss die Provision je Reservierung aus der Differenz
   errechnet werden?
3. **Airbnb-Auszahlungsübersicht:** liegen die earnings-PDFs regelmäßig vor,
   oder wird Airbnb von Hand aufgeteilt?
