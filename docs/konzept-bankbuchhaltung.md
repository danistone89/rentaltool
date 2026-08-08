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

### B4b · Verrechnungskonto je Plattform — ✅ erledigt (8.8.2026)

**Der Betreiber hat entschieden: wie das Steuerbüro, mit Verrechnungskonto.**
Ein laufender Saldo je Plattform zeigt, was sonst niemand sieht – ob Booking
noch etwas schuldet, und ob ein Monat aufgeht.

```
Verrechnungskonto Booking.com
  + Rechnung 2026-0031  Meier          620,00
  + Rechnung 2026-0032  Schulz         540,00
  − Provision (Monatsbeleg Juni)      −145,87
  − Auszahlung 12.06.                −1014,13
  ─────────────────────────────────────────────
  Saldo                                  0,00  ✓
```

**Abgeleitet, nicht doppelt gebucht.** Es wäre möglich, für jede Rechnung und
jede Provision eine zweite Bewegung auf einem Plattform-Konto zu erzeugen –
echte doppelte Buchführung. Dagegen sprechen zwei Dinge: die Zahlen stünden
zweimal im Bestand und könnten auseinanderlaufen, und jeder Fehler müsste an
beiden Stellen korrigiert werden. Der Saldo lässt sich aus dem berechnen, was
ohnehin da ist:

    Saldo = Σ zugeordnete Rechnungen − Σ Provisionen − Σ Auszahlungen

Dieselbe Zahl, eine Quelle. Was hinzukommt, ist die **Ansicht**: ein Kontoblatt
je Plattform mit allen Zeilen und dem laufenden Saldo.

**Was es zusätzlich sichtbar macht** – und der eigentliche Gewinn:

* **Offene Forderung**: Rechnungen der Plattform, zu denen noch keine
  Auszahlung zugeordnet ist. „Booking schuldet dir noch 2.340 €."
  ⚠ **Nicht gebaut** – der Vertriebskanal steht nicht an der Rechnung, sondern
  an der Buchung, und erreicht das Konto erst über die Zuordnung zur
  Auszahlung. Eine Liste, die stattdessen *alle* offenen Rechnungen zeigt, sähe
  nach einer Antwort aus und wäre keine. Der Saldo sagt, **dass** etwas fehlt;
  **welche** Rechnung es ist, sagt die Vorschlagsliste aus B3. Sobald der Kanal
  an der Rechnung steht (offener Punkt), lässt es sich nachtragen.
* **Die Monatsprobe**: Die Summe der Provisions-Posten eines Monats muss den
  **Monatsbeleg** treffen. Weicht sie ab, fehlt eine Rechnung oder eine
  Auszahlung. Das ist die Prüfung, die vorher fälschlich gegen Smoobu lief –
  jetzt gegen eine verlässliche Quelle.
  ⚠ **Gerechnet, aber noch nicht bedienbar**: `verrechnung.monatsprobe` ist da
  und geprüft, braucht aber den Betrag vom Monatsbeleg. Den gibt es erst,
  wenn die Belege an den Bewegungen hängen – **B5**. Dort wird sie angezeigt.

*Größe:* M · *Umgesetzt:* `app/verrechnung.py`, Karte „Verrechnungskonten" im
Bereich Konto, `tests/test_verrechnung.py` (13 Prüfungen)

### B4 · Portalprovision gegenbuchen

Booking und Airbnb schicken **monatlich einen Provisionsbeleg**; Airbnb dazu
die Auszahlungsübersicht. Der Beleg wird als Gegenposten auf dieselbe Zahlung
gebucht — erst damit stimmen Umsatz und Ausgaben.

Zur Gegenprobe kennt das Werkzeug die Provision schon aus Smoobu
(`commission-included` je Buchung): Weicht die Summe der Einzelprovisionen vom
Monatsbeleg ab, ist das ein Befund und kein Rundungsfehler. · *Größe:* M

### B5 · Eingangsbelege zuordnen — ✅ erledigt (8.8.2026)

Heute laufen **Belege** (Mitarbeiter-Upload) und **Konto** nebeneinander: ein
fotografierter Beleg bleibt für das Konto unsichtbar, und derselbe Beleg kann
zweimal im System landen. Nötig: aus der Bewegung einen vorhandenen Beleg
auswählen, aus dem Beleg die passende Bewegung, und eine Dublettenprüfung über
beide Wege. · *Größe:* L

**Am Bestand nachgemessen (8.8.2026)** — bevor gebaut wird, was der Fall
gar nicht hergibt:

| | |
|---|---|
| Belege im Werkzeug | **4** |
| davon an einer Bewegung | **0** |
| davon mit Betrag | **1** |
| davon mit gepflegtem Belegdatum | **0** (alle über den Upload-Tag) |
| Ausgaben-Bewegungen | 128, davon **42 ohne Beleg** |

Zwei Folgerungen:

1. **Ein Abgleich über den Betrag trägt nicht.** Der eine Beleg mit Betrag
   (9,44 €) trifft **null** Bewegungen. Derselbe Befund wie bei den
   Zahlungseingängen in B3: Beträge sind hier kein Schlüssel. Sortiert wird
   nach **Händlername** und **Datumsnähe**; der Betrag ist ein Zusatzhinweis,
   wenn er da ist, und nie ein Ausschlusskriterium.
2. **Der Vorrat an freien Belegen ist heute leer.** „Aus der Bewegung einen
   vorhandenen Beleg wählen" hat momentan fast nichts zu wählen — der Weg
   bleibt trotzdem nötig, sonst ist jeder Handy-Upload für die Buchhaltung
   verloren. Der Nutzen wächst mit dem Bestand.

Aufgeteilt in vier Stücke:

* **B5a · Beide Richtungen.** Aus der Bewegung einen vorhandenen Beleg wählen,
  aus dem Beleg die Bewegung. Mit Grund an jedem Vorschlag, wie in B3.
* **B5b · Ein Beleg auf mehrere Bewegungen.** Der Provisionsbeleg von Booking
  kommt **monatlich**, die Auszahlungen kommen **einzeln** (44 im Halbjahr).
  Ein Beleg muss deshalb an mehreren Bewegungen hängen können. Damit wird die
  **Monatsprobe aus B4b** endlich anzeigbar: Summe der Provisions-Posten eines
  Monats gegen den Betrag des Monatsbelegs.
* **B5c · Dublettenprüfung.** Derselbe Beleg über beide Wege hochgeladen.
  Erkannt an Händler + Betrag + naher Datumslage; **gewarnt, nicht verhindert**
  — zwei Tankquittungen desselben Tages über denselben Betrag gibt es wirklich.
* **B5d · Die Wege zusammenführen.** Der Belege-Bereich zeigt an jedem Beleg,
  zu welcher Bewegung er gehört, und lässt nach „noch keiner Bewegung
  zugeordnet" filtern. Kein Zusammenlegen der Bereiche: der Handy-Upload
  unterwegs und die Buchhaltung am Schreibtisch sind zwei Situationen.

**Zwei Fehler, die dabei gefunden wurden** — beide bestanden vor B5:

1. **Ein Beleg löschte die Aufteilung.** `konto.beleg_setzen` löste zuerst
   *alle* Posten. Wer 100 € auf Putzmittel (60) und Gastgeschenke (40)
   aufgeteilt hatte und danach den Kassenbon anhängte, verlor die Aufteilung –
   stillschweigend. Ersetzt durch `konto.beleg_anhaengen`, das vorhandene
   Posten stehen lässt.
2. **An einer Auszahlung buchte der Beleg den Umsatz.** Erst an den echten
   Daten aufgefallen: der Provisionsbeleg über 265,87 € erzeugte an einer
   Booking-Auszahlung einen Posten über **+1.348,42 €** — den offenen Rest der
   Auszahlung. Ein Lieferantenbeleg kann diesen Rest nie decken; er gehört an
   die gegengebuchte Provision. Gibt es die noch nicht, passiert nichts und die
   Maske sagt es.

**Was B5 für B4b nachliefert:** die **Monatsprobe** ist jetzt anzeigbar. Der
Monatsbeleg hängt an den Provisions-Posten, `verrechnung.monatsuebersicht`
stellt gebuchte Provision und Belegbetrag je Monat gegenüber. An den echten
Daten durchgespielt: ein Beleg über 265,87 €, verteilt auf zwei
Juni-Auszahlungen, Probe stimmt.

**Nachgebessert nach der ersten Benutzung (8.8.2026):**

* **Mehrere Belege auf einmal.** Der Upload nahm eine Datei je Auswahl – im
  Alltag sammelt man Quittungen und lädt sie gemeinsam hoch. Jetzt bis zu 30,
  nacheinander verarbeitet (Zuschnitt, PDF und OCR laufen im Thread-Pool;
  gleichzeitig brächte keine Zeit, nur Last). **Ein Fehler stoppt den Stapel
  nicht** – sonst verhinderte eine unlesbare Datei in der Mitte alles
  Nachfolgende, und man wüsste hinterher nicht, was angekommen ist.
* **Alle passenden Bewegungen, nicht die ersten acht.** Die Vorauswahl half
  nur, solange die richtige Bewegung zufällig oben stand. Jetzt stehen alle
  122 zur Wahl – scrollbar, mit Suche über Empfänger, Verwendungszweck, Datum
  und Betrag. Sortierung ist eine Hilfe, kein Ersatz fürs Suchen.

*Umgesetzt:* `app/belegzuordnung.py`, `konto.beleg_anhaengen/beleg_loesen`,
`zuordnung.ziel_setzen/bewegungen_zu`, `verrechnung.monatsuebersicht`, Masken in
`app/ui/kontoblatt.py` und `app/ui/belege.py`, `tests/test_belegzuordnung.py`
(34 Prüfungen).

### B6 · Kategorien an jeder Zuordnung — ✅ erledigt (8.8.2026)

Anlegen und pflegen steht (AP27a). **Die Einnahmen-Kategorien fehlen nicht
mehr** — sie kamen mit den 31 wörtlichen Workbook-Kategorien
(„Beherbergungserlöse (Booking, netto Auszahlung)" usw.). Der frühere Text
hier war überholt.

**Am Bestand nachgesehen (8.8.2026), was wirklich fehlt:**

| Befund | |
|---|---|
| Posten ohne Kategorie | **2 von 10** |
| davon ein *Kategorie*-Posten ganz ohne Kategorie | 790,27 € |
| Kategorie für die **Portalprovision** | **existiert nicht** |
| Auswertung rechnet nach | `bewegung.klasse`, nicht nach Posten |

Drei Lücken, die zusammengehören:

* **B6a · Kategorie am Posten pflegbar.** Ein Posten trägt schon ein Feld
  `kategorie`, aber es lässt sich nach dem Anlegen nicht mehr ändern. Bei einer
  Sammelzahlung braucht jeder Posten seine eigene.
* **B6b · Ein Kategorie-Posten ohne Kategorie sagt nichts.** Genau so entstand
  der Posten über 790,27 €: die Maske ließ „— Kategorie —" stehen und buchte.
  Das Werkzeug soll das nicht annehmen — und, weil für die **Portalprovision
  keine Kategorie existiert**, an Ort und Stelle eine anlegen lassen. *Keine
  erfundene Vorgabe*: die Kategorien sind wörtlich die des Workbooks, und die
  Vorkontierung macht der Betrieb selbst (Ansage vom 8.8.2026).
* **B6c · Vorbelegung, wo sie sich ergibt.** Ein Rechnungs-Posten an einer
  Booking-Auszahlung ist ein Beherbergungserlös Booking; ein Beleg-Posten trägt
  die Kategorie seines Belegs. Beides steht schon fest und muss nicht getippt
  werden.

Die **Auswertung je Kategorie über die Posten** (statt über die Bewegung)
gehört zu B7 — hier entsteht nur die Funktion, auf der sie aufsetzt:
`konto.je_kategorie`. Drei Regeln, damit die Zahl ehrlich bleibt: wo Posten
sind, zählen sie; wo keine sind, zählt die Kategorie der Bewegung (sonst
verschwände jede noch nicht aufgeteilte Zahlung); und was an einer teilweise
aufgeteilten Bewegung offen ist, steht unter „— noch ohne Kategorie —" statt
bei der Bewegungskategorie mitzulaufen.

**Dabei gefunden:** trug ein Posten eine Kategorie, die es nicht mehr gibt
(gelöscht oder umbenannt), lehnte die Auswahl den Wert ab und die **ganze
Zuordnungsmaske brach ab** — der Posten war dann nicht einmal mehr erreichbar,
um ihn zu berichtigen. Solche Kategorien stehen jetzt mit dem Zusatz „nicht
mehr in der Liste" zur Wahl.

*Größe:* S · *Umgesetzt:* `zuordnung.kategorie_setzen/kategorie_vorschlag`,
Pflicht zur Kategorie in `zuordnung.hinzufuegen`, `konto.je_kategorie`,
Auswahl je Posten und „+ Neue Kategorie" in `app/ui/kontoblatt.py`,
`tests/test_postenkategorie.py` (21 Prüfungen)

### B7 · Der Überblick — ✅ erledigt (8.8.2026)

Einnahmen, Ausgaben, Ergebnis je Monat und Wohnung, dazu **je Kategorie** —
„wie viel ging für Putzmittel drauf". Ersetzt das, was heute das Workbook von
Hand liefert. *(war AP17 + zweite Hälfte AP27)* · *Größe:* L

**Am Bestand nachgemessen (8.8.2026), bevor gebaut wird:**

| Frage | Befund |
|---|---|
| Posten mit ableitbarer **Wohnung** | **1 von 27** |
| Belege mit Wohnung | **0 von 30** |
| Rechnungen mit Wohnung | 48 von 48 — aber nur 1 hängt an einer Zahlung |
| `monatssummen` rechnet nach | `bewegung.klasse` und `bewegung.kategorie` |

Daraus folgt der Zuschnitt:

* **B7a · Ergebnis je Monat, aus den Posten.** `monatssummen` rechnet heute
  über die Bewegung. Nach B6 kann eine Zahlung auf mehrere Kategorien mit
  verschiedenen Klassen aufgeteilt sein — eine Privatentnahme in einer
  Sammelzahlung würde das Ergebnis belasten. Dieselbe Naht wie in
  `ohne_zuordnung`: auch `unklar` zählt bisher nur das Feld und übersieht, was
  über die Maske zugeordnet wurde.
* **B7b · Je Kategorie, gruppiert nach Klasse.** Die eigentliche Frage aus dem
  Alltag. `konto.je_kategorie` steht seit B6; es fehlt die Gruppierung
  (Einnahme / Ausgabe / Privat / Durchlaufend) und die Anzeige mit Zeitraum.
* **B7c · Je Wohnung — so weit die Daten es hergeben.** Auf der Ausgabenseite
  ist das heute **nichts**: kein einziger Beleg trägt eine Wohnung. Gebaut wird
  die Rechnung trotzdem, aber die Anzeige **nennt ihre Abdeckung** statt eine
  leere Tabelle als Ergebnis auszugeben. Eine Auswertung, die verschweigt,
  worauf sie sich stützt, ist schlimmer als keine.

**Was der Überblick NICHT ist:** keine EÜR fürs Finanzamt. Der Zweck ist der
Blick auf die eigenen Zahlen, weil das Steuerbüro 8–10 Monate hinterherhinkt
(Ansage vom 8.8.2026). Deshalb steht überall dabei, wie belastbar die Zahl
gerade ist.

**Der Befund, der die Anzeige bestimmt hat.** Beim ersten Lauf über die echten
Zahlen stand für **jeden** Monat ein Verlust – Juni −1.489 €. Nicht weil der
Betrieb Verlust macht, sondern weil **11.932,88 €** noch keiner Kategorie
zugeordnet sind, überwiegend Einnahmen. Eine Ergebnisspalte, die das nicht
sagt, wäre die gefährlichste Zahl im ganzen Werkzeug. Deshalb liefert `monate()`
je Monat `offen_betrag` und `belastbar` mit; nicht belastbare Ergebnisse stehen
blass, und unter der Tabelle steht, wie viel fehlt.

*Umgesetzt:* `app/ueberblick.py` (monate / kategorien / wohnungen / abdeckung),
`app/ui/ueberblick.py` als eigener Bereich, `tests/test_ueberblick.py`
(23 Prüfungen)

### B8 · Vollständigkeit — ✅ erledigt (8.8.2026)

Saldo-Abgleich gegen den Kontoauszug, lückenlose Zeiträume, Liste der
Bewegungen mit Restbetrag ≠ 0 und der fehlenden Belege. *(war AP25)*
· *Größe:* M

**Warum das der wichtigste Prüfstein ist.** B7 zeigt Zahlen. Ob sie etwas
wert sind, hängt daran, ob *alle* Bewegungen da sind — und das sieht man ihnen
nicht an. Ein fehlender Auszugsmonat macht keinen Fehler, er macht ein
falsches, plausibel aussehendes Ergebnis.

**Am Bestand nachgesehen (8.8.2026):** die Kopfzeilen des DKB-Auszugs tragen
alles, was dafür nötig ist —

```
"DKB-Business";"DE62..."
"Zeitraum:";"01.01.2026 - 24.07.2026"
"Kontostand vom 24.07.2026:";"5.765,34 €"
```

— sie werden beim Einlesen bisher aber **übersprungen**. Ohne sie lässt sich
Vollständigkeit gar nicht behaupten.

* **B8a · Kopfdaten mitschreiben.** Je Import ein Satz: Konto, Zeitraum,
  Stichtag, Kontostand. Der Saldo-Abgleich funktioniert dann **ab dem zweiten
  Auszug** eines Kontos: die Differenz zweier Kontostände muss der Summe der
  Bewegungen dazwischen entsprechen. Stimmt sie nicht, fehlen Bewegungen —
  ohne dass man wüsste welche, aber man weiß *dass*.
* **B8b · Lücken im Zeitraum.** Decken die eingelesenen Auszüge einen
  durchgehenden Zeitraum ab, oder fehlt ein Monat?
* **B8c · Die offenen Arbeiten an einer Stelle.** Restbeträge ≠ 0, Ausgaben
  ohne Kategorie, fehlende Belege, Posten ohne Kategorie — die Listen gibt es
  verstreut; hier stehen sie zusammen mit einer Zahl davor.

**Bewusst kein Ampel-Gesamturteil.** „Alles in Ordnung" wäre eine Behauptung
über Daten, die das Werkzeug nicht kennen kann — etwa ein Konto, von dem noch
nie ein Auszug kam. Gezeigt wird, was geprüft wurde und was dabei herauskam.

**Der Befund steht ganz oben im Überblick, vor den Zahlen.** Wer die Zahlen
erst liest und die Einschränkung danach, hat sie schon geglaubt.

**Für den vorhandenen Bestand gilt er noch nicht:** die 193 Bewegungen wurden
vor B8 eingelesen, Kopfdaten gibt es dafür keine. Die Anzeige sagt das
ausdrücklich, statt „keine Saldosprünge" zu melden — was wie „geprüft und in
Ordnung" aussähe. Ab dem nächsten Import greift die Probe.

#### Die Kreditkarte — was der Bankimport mit dem Kartenauszug zu tun hat

Gefragt am 8.8.2026: *auf dem Bankimport müsste es eine Sammelbuchung zu einem
Kreditkartenbelegmonat geben.* Genau so ist es, und der Aufbau ist sauberer
als befürchtet:

```
Girokonto   26.01.  −185,68   KREDITKARTENABRECHNUNG VISA     ← Umbuchung
VISA 8136   22.01.  +185,68   Ausgleich Kreditkarte            ← Umbuchung
VISA 8136   05.01.   −30,00   Rossmann                         ← die Ausgabe
VISA 8136   08.01.   −26,93   dm                               ← die Ausgabe
```

**Beide Sammelbuchungen sind neutral gestellt** (`kontoauszug.ist_umbuchung`),
die **Einzelkäufe tragen die Ausgabe**. Nichts zählt doppelt — das war schon
seit AP16 richtig.

Die Gefahr liegt woanders: **fehlt der Kartenauszug, fehlen alle Einzelkäufe
im Ergebnis, und nichts fällt auf**, weil die Sammelbuchung ja neutral ist.
Zwei Proben dagegen:

* `kartenproben()` — deckt jeder Ausgleich genau die Käufe seit dem letzten?
  An den echten Daten stimmten **5 von 6** auf den Cent; der erste wich um
  22,00 € ab, weil seine Käufe vor dem Importzeitraum lagen. Deshalb gilt der
  erste Zyklus je Karte ausdrücklich als **nicht prüfbar**.
* `sammelbuchungen_ohne_karte()` — eine Abrechnung auf dem Girokonto, zu der
  kein Ausgleich in gleicher Höhe auf einem Kartenkonto steht. Das ist die
  Aufforderung: *diesen Kartenauszug noch hochladen.*

*Umgesetzt:* `kontoauszug.kopfdaten`, `app/vollstaendigkeit.py`, Tabelle
`auszuege`, Karte im Bereich Überblick, `tests/test_vollstaendigkeit.py`
(32 Prüfungen)

### B9 · Übergabe ans Steuerbüro — ✅ erledigt (8.8.2026)

Ablage in der Nextcloud nach Jahr und Monat, sprechende Dateinamen,
Belegnummer auf Dokument **und** Buchung. *(war AP18)* · *Größe:* L

**Am Bestand nachgesehen (8.8.2026):**

| | |
|---|---|
| Belege | 30, alle als PDF |
| davon mit **Belegnummer** | **0** — die gibt es noch gar nicht |
| davon mit gepflegtem Belegdatum | 0 (alle über den Upload-Tag) |
| Bewegungen / Posten | 238 / 53 |
| `belege_ordner` (Nextcloud) | leer |

**Der entscheidende Befund: das Kontenjournal kommt heute aus den Belegen**
(`buchhaltung.journal_zeile`). Das war richtig, solange Belege die einzige
Quelle waren. Seit B1 ist die Buchhaltung aber die **Bewegung mit ihren
Posten** — ein Journal aus Belegen kennt die 45 Ausgaben ohne Beleg nicht, und
es kennt keine Aufteilung. Es würde dem Steuerbüro ein unvollständiges Bild
geben, das vollständig aussieht.

* **B9a · Die Belegnummer.** Laufend je Jahr, auf dem Beleg gespeichert. Sie
  steht dann im Dateinamen **und** in der Journalzeile — das ist die Klammer,
  über die das Steuerbüro von der Buchung zum Papier findet. Einmal vergeben
  ändert sie sich nie wieder.
* **B9b · Das Journal aus den Bewegungen.** Eine Zeile je Posten (nicht je
  Beleg), mit Datum, Konto, Gegenpartei, Verwendungszweck, Betrag, Klasse,
  Kategorie, Belegnummer. Bewegungen ohne Posten kommen mit ihrer Kategorie,
  Umbuchungen mit dem Vermerk „neutral". Was fehlt, steht als Fehlt-Vermerk
  drin, statt zu fehlen.
* **B9c · Das Übergabepaket.** Ordner je Jahr und Monat, sprechende
  Dateinamen (`0007_2026-03-14_Rossmann_27,81.pdf`), das Journal als CSV, und
  ein **Deckblatt mit dem Befund aus B8** — wie viele Bewegungen ohne
  Kategorie, ohne Beleg, welcher Zeitraum, welche Konten. Ohne dieses Blatt
  liest das Steuerbüro einen Zwischenstand als Abschluss.

**Zwei Wege aus dem Werkzeug heraus:** herunterladen, oder direkt in einen
**Übergabe-Ordner** schreiben (Einstellungen → Ablage). Zeigt der auf den
Nextcloud-Sync, liegt die Übergabe dort, sobald der Client durchgelaufen ist –
ohne Zugangsdaten im Werkzeug und ohne zweiten Übertragungsweg.

Der Übergabe-Ordner ist bewusst **nicht** der Beleg-Ordner: der ist ein
laufender Spiegel, die Übergabe ein abgeschlossener Stapel. In denselben Ordner
geschrieben wäre nicht mehr zu erkennen, was zu welcher Übergabe gehört.

Drei Vorsichtsmaßnahmen beim Schreiben: nichts wird gelöscht oder
überschrieben (ein zweiter Lauf legt einen neuen Ordner an – sonst wäre eine
bereits weitergegebene Übergabe plötzlich eine andere), ein fehlendes Ziel wird
gemeldet statt angelegt (ein vertippter Pfad soll auffallen), und der
Ordnername nennt den Zeitraum.

*Anmerkung:* Beim ersten Bauen hatte ich daraus nur einen Download gemacht und
notiert „kein automatisches Hochladen". Auf die Frage *„wie speichere ich denn
alles, um es dem Steuerberater zu geben?"* zeigte sich, dass damit das
eigentliche Ziel fehlte – **sammeln im Werkzeug, speichern in der Nextcloud**
stand seit dem 8.8.2026 im Konzept.

**Beim ersten Paket aus den echten Daten fiel auf:** alle 30 Belege lagen im
Ordner `2026/08` — dem Monat des Uploads —, weil **keiner** ein Belegdatum
trug. Die Ablage nach Jahr und Monat wäre damit wertlos gewesen. Zwei
Konsequenzen: `receipts.guess_datum` liest das Datum aus dem Belegtext
(Rechnungsdatum vor erstem Fund, nichts aus der Zukunft — „buchen wir am
07.05. ab" ist kein Belegdatum), und was danach noch keins hat, kommt in einen
eigenen Ordner `_ohne Belegdatum` statt in den Upload-Monat. An den echten
Belegen: 24 von 30 bekamen ein Datum, die Ablage reicht jetzt von 2025/11 bis
2026/05.

*Umgesetzt:* `app/uebergabe.py` (nummer_vergeben / journal / journal_csv /
deckblatt / paket), `receipts.guess_datum`, Karte im Bereich Überblick,
`tests/test_uebergabe.py` (24 Prüfungen)

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
