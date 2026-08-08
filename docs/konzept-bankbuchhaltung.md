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
| **Booking**, Sammelauszahlung je Wohnung | 44 Eingänge | nur die Wohnung, **nicht** die Buchung |
| **Airbnb**, Sammelauszahlung | 7 Eingänge | Verwendungszweck nutzlos („AWV-MELDEPFLICHT") |
| **Direktzahler** | 8 Eingänge | Gastname im Verwendungszweck („Buchung Katarina Gockel") |
| **Ausgaben mit Beleg** | 122 Ausgänge | Empfänger → Kreditor (steht schon) |

### Nachgeprüft am 8.8.2026 — und eine Annahme war falsch

Die erste Fassung dieses Konzepts nahm an, im Verwendungszweck von Booking
stünde die Reservierungsnummer. **Sie steht dort nicht.**

`NO.bbqETYstLU6QDo85/ID.14005823` — über alle 44 Zahlungen kommen genau **zwei
verschiedene** `ID.`-Nummern vor: `14005823` und `15049295`. Das sind die
beiden **Wohnungen** bei Booking, nicht die Buchungen. Die Smoobu-Buchungen
tragen ihre Booking-Nummer in `reference-id` (z. B. `5882430387`) — sie taucht
im Bankauszug **nirgends** auf.

Und die Beträge helfen auch nicht:

| Vergleich | Treffer |
|---|---:|
| Zahlungseingang == Rechnungsbetrag | **1 von 65** |
| Booking-Zahlung == `price` einer Buchung | **0 von 44** |
| Booking-Zahlung == `price − commission` einer Buchung | **0 von 44** |

> **Auch Booking zahlt gesammelt aus** — nicht je Reservierung, wie zuerst
> angenommen, sondern **je Wohnung und Auszahlungslauf**. Damit ist der
> n:m-Fall nicht die Ausnahme für Airbnb, sondern der **Normalfall für beide
> Portale**: 51 von 65 Zahlungseingängen.

### Was stattdessen trägt

**Der Restbetrag trägt die Arbeit.** Man wählt Rechnungen aus – zugeordnet wird
der **Rechnungsbetrag**, nicht die Auszahlung –, der Rest zählt herunter, und
was übrig bleibt, ist die einbehaltene Provision.

> **Korrektur vom 8.8.2026:** Eine frühere Fassung wollte den Rest gegen
> `commission-included` aus Smoobu prüfen. Der Betreiber hat widersprochen: die
> Zahl stimmt nicht verlässlich. **Maßgeblich sind die monatlichen Belege von
> Booking und Airbnb**, die das Steuerbüro gegen die Auszahlungen bucht. Eine
> Nachrechnung gegen eine unzuverlässige Zahl hätte Fehlalarme erzeugt – „es
> fehlt eine Rechnung", wo nur die Schätzung daneben lag. Geprüft wird gegen
> den Monatsbeleg (B5).

Dazu kommen die **monatlichen Provisionsbelege** von Booking und Airbnb
(bestätigt am 8.8.2026) sowie die monatliche Airbnb-Auszahlungsübersicht. Sie
sind die Belege, gegen die gebucht wird.

**Konsequenz fürs Konzept:** Die Zuordnung ist **bedient**, nicht automatisch.
Das Werkzeug schlägt eine **Kandidatenliste** vor — offene Rechnungen dieser
Wohnung im passenden Zeitraum, mit erwartetem Nettobetrag — und man hakt ab,
bis der Rest null ist. Genau so arbeitet lexoffice. Eine Automatik, die aus
Beträgen Kombinationen rät, würde falsch buchen und es nicht sagen.

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

Eine **Kandidatenliste** statt einer Automatik: offene Rechnungen der Wohnung
im passenden Zeitraum, jede mit ihrem **erwarteten Auszahlungsbetrag**
(`price − commission-included` aus Smoobu). Abhaken, bis der Rest null ist.

Die Wohnung kommt aus der `ID.`-Nummer im Verwendungszweck — sie ist zwar nicht
die Buchung, aber sie halbiert die Kandidatenliste. Welche Nummer zu welcher
Wohnung gehört, lernt das Werkzeug bei der ersten Zuordnung.

Für Direktzahler zusätzlich der **Gastname** aus dem Verwendungszweck. Die
zugeordnete Rechnung gilt damit als **bezahlt** und trägt ein Zahlungsdatum.
· *Größe:* L

### B4 · Portalprovision gegenbuchen

Booking und Airbnb schicken **monatlich einen Provisionsbeleg**; Airbnb dazu
die Auszahlungsübersicht. Der Beleg wird als Gegenposten auf dieselbe Zahlung
gebucht — erst damit stimmen Umsatz und Ausgaben.

Zur Gegenprobe kennt das Werkzeug die Provision schon aus Smoobu
(`commission-included` je Buchung): Weicht die Summe der Einzelprovisionen vom
Monatsbeleg ab, ist das ein Befund und kein Rundungsfehler. · *Größe:* M

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

## 7. Geklärt am 8.8.2026

1. **Die Booking-Reservierungsnummer steht NICHT im Verwendungszweck** —
   nachgeprüft. Dort steht die Wohnung. Auch Booking zahlt gesammelt aus.
   *(Abschnitt 4)*
2. **Die Provisionsbelege kommen monatlich** von Booking und Airbnb.
3. **Die Airbnb-Auszahlungsübersicht liegt monatlich vor.**
4. **Smoobu liefert die Provision je Buchung** (`commission-included`) — damit
   ist der erwartete Auszahlungsbetrag je Rechnung bekannt.

Damit ist nichts mehr offen, was den Zuschnitt ändern würde. **B1 kann
beginnen.**
