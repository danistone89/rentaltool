# Beherbergungssteuer Dresden

Lokale Webapp, die aus den Smoobu-Buchungen die monatliche
Beherbergungssteuer-Anmeldung für Dresden berechnet und das **amtliche Formular
(Vdr 22.040/5) pixelgenau als PDF** erzeugt.

**Frontend:** NiceGUI (reines Python, keine Node-Toolchain). **Backend:**
Standardbibliothek (Smoobu/Steuer) + PyMuPDF (PDF). Alles via
`pip install -r requirements.txt`.

## Start

```bash
cd apps/beherbergungssteuer
pip install -r requirements.txt
cp config.example.json config.json   # einmalig: API-Key + Betreiberdaten
./run-local.sh                       # = python3 app/web.py
```

Dann <http://localhost:3001/> öffnen, Jahr/Monat + Apartments wählen,
**Berechnen** → KPIs, Buchungsliste und **„📄 Amtliches Formular (PDF)
herunterladen"**. Einstellungen oben rechts (⚙️).

## Architektur

**Fachlogik** (`app/`) und **Oberfläche** (`app/ui/`) sind getrennt. Die
Oberfläche hat ein Modul je Bereich:

| Oberfläche | Aufgabe | Zeilen |
|---|---|---:|
| `app/web.py` | Einstieg: Zeitzone, Login-Schranke, Routen, Hauptseite mit Navigation | 353 |
| `app/ui/basis.py` | Gemeinsame Grundlage: Konfiguration, Sprache, Rollen, Logo, Format- und Foto-Helfer | 337 |
| `app/ui/standort.py` | GPS, IP, Geofence für die Zeiterfassung | 110 |
| `app/ui/zugang.py` | Anmelden, Einladung, Passwort vergessen, Mein Konto, Benutzer | 644 |
| `app/ui/einstellungen.py` | Einstellungs-Dialog (Betreiber, Steuer, E-Mail, Archiv, Standorte) | 398 |
| `app/ui/steuer.py` | Beherbergungssteuer: Berechnung anzeigen, PDF erzeugen, Archiv | 356 |
| `app/ui/zeiten.py` | Zeiterfassung: Liste, Kennzahlen, Abrechnungsstatus, CSV | 487 |
| `app/ui/buchungen.py` | Reinigungslisten, Tagesgruppen, Reinigungskarten | 751 |
| `app/ui/dialog.py` | Buchungs-Dialog samt Aktionen und Gast-Nachrichten | 413 |
| `app/ui/kalender.py` | Zeitleiste über alle Wohnungen, Monatsblatt einer Wohnung | 241 |
| `app/ui/reinigung.py` | Checklisten-Durchgang, Schäden, Bestand, Übersicht | 594 |
| `app/ui/belege.py` | Belegscanner, Ablage, OCR, Liste | 441 |
| `app/ui/pwa.py` | Handy-App: Manifest, Icons, Service Worker, Einricht-Anleitung | 290 |
| `app/ui/benachrichtigungen.py` | Push einschalten, Geräte verwalten, Meldearten | 210 |
| `app/ui/planung.py` | Sammelzuweisung, Abwesenheiten, Stammzuständigkeit | 200 |
| `app/ui/auswertung.py` | Kennzahlen-Blatt (Reiter in der Übersicht) | 175 |

Die Abhängigkeiten laufen von `basis` (kennt keinen Bereich) nach außen. Wo zwei
Bereiche einander brauchen – Buchungen, Dialog, Kalender, Reinigung –, wird das
jeweils andere **Modul als Objekt** importiert und der Name erst beim Aufruf
nachgeschlagen (`dialog.open_booking_dialog(…)`); ein `from X import name` würde
sich beim Laden im Kreis drehen.

> **Falle beim Registrieren von Seiten:** `/login` und `/invite` werden über
> `zugang.seiten_registrieren()` angemeldet, nicht per `@ui.page`-Dekorator. Der
> Testlauf führt `app/web.py` **je Test erneut** aus, während die Bereichsmodule
> geladen bleiben – ein Dekorator dort liefe nur beim allerersten Import, und ab
> dem zweiten Test wäre die Seite verschwunden (404). Aus demselben Grund leert
> `web.py` beim Start die flüchtigen Zwischenspeicher.

| Fachlogik | Aufgabe |
|---|---|
| `app/data.py` | Config, Smoobu-Cache, Berechnungs-Glue |
| `app/steuer.py` | Steuerberechnung (Golden-Tests) |
| `app/smoobu.py` | Smoobu-API-Client |
| `app/pdf_form.py` | Amtliches PDF aus Blanko-Vorlage |
| `app/archive.py` | Revisionssichere Ablage (Hash-Kette, Versionen, Spiegel) |
| `app/mailer.py` | E-Mail-Versand über Gmail (Vorlagen) |
| `app/auth.py` | Login (PBKDF2) + optionale 2FA (TOTP) + Einladungs-Links |
| `app/feiertage.py` | Gesetzliche Feiertage Sachsen + Tagesart (Werktag / Wochenende+Feiertag) |
| `app/i18n.py` | Mehrsprachigkeit DE/EN der Mitarbeiterbereiche (`t()`) |
| `app/ical.py` | Reinigungstermin als `.ics` für den eigenen Kalender |
| `app/paths.py` | Wo die Betriebsdaten liegen (Datenordner, getrennt vom Code) |
| `app/db.py` | Betriebsdaten in SQLite (Sätze als JSON, generierte Spalten, Transaktionen) |
| `app/store.py` | Dateizugriff für `config.json`: atomar schreiben, gesperrt ändern |
| `app/mode.py` | Echtbetrieb oder Probe-Instanz (sperrt Mail/Gast-Nachricht/Spiegel) |
| `app/push.py` | Web Push: VAPID-Schlüssel, Geräte-Anmeldungen, Versand |
| `app/planung.py` | Stammzuständigkeit, Abwesenheiten, Zuweisungs-Vorschläge |
| `app/kennzahlen.py` | Auslastung, Umsatz, Reinigungs- und Materialkosten je Wohnung |

| Werkzeuge | Aufgabe |
|---|---|
| `tools/make_blank.py` | Blanko-Vorlage + Unterschrift aus eingereichter PDF |
| `tools/useradmin.py` | Benutzer per Kommandozeile (Notfall/Server, ohne Oberfläche) |
| `tools/migrate_data.py` | Betriebsdaten einmalig in einen eigenen Datenordner umziehen |
| `tools/backup.py` | Tägliche Sicherung auf die Nextcloud + Wiederherstellungs-Probe |
| `tools/migrate_db.py` | Einmalige Übernahme der JSON-Bestände in die Datenbank |
| `tools/deploy.sh` | Ausrollen mit Tests, Rauchprobe und Rückweg |
| `tools/staging_refresh.py` | Probe-Instanz mit entschärfter Kopie der Echtdaten füllen |
| `tools/watchdog.py` | Wächter: Oberfläche, Smoobu, Daten, Sicherung |
| `tools/erinnerung.py` | Abendliche Erinnerung: was morgen ansteht |
| `tools/uishot.py` | Bildschirmfotos der laufenden Oberfläche – auch hinter dem Login |
| `tools/check_shadowing.py` | Findet überschattete Modulnamen (läuft als Test mit) |

Der Fahrplan für den weiteren Ausbau steht in [`docs/roadmap.md`](docs/roadmap.md).

## Oberfläche prüfen lassen

Eine Oberfläche lässt sich nicht aus dem Quelltext beurteilen. `tools/uishot.py`
startet die App mit einem **Wegwerf-Datenordner** (eigene Konten, eigene
Datenbank, erfundene Buchungen), steuert Chrome über das DevTools-Protokoll,
meldet sich an und klickt sich durch die Bereiche:

```bash
.venv/bin/python tools/uishot.py --ziel /tmp/ui          # Handy, 390 × 844
.venv/bin/python tools/uishot.py --ziel /tmp/ui --breit  # zusätzlich 1280 px
```

Der Echtbetrieb wird dabei nicht berührt. Ein einfaches `chrome --screenshot`
reicht nicht: NiceGUI baut die Oberfläche erst über eine offene Verbindung auf,
und ohne Anmeldung sieht man nur die Login-Seite.

Darauf setzt der Prüf-Agent **`ui-design`** auf
([`.claude/agents/ui-design.md`](.claude/agents/ui-design.md)). Er sieht sich die
Bilder an und misst sie an den Festlegungen dieses README und des
Navigationskonzepts: Erreichbarkeit am Daumen, wie viel Platz das Rahmenwerk
frisst, Überlauf am rechten Rand, Ablesbarkeit des Zustands, Verständlichkeit der
Texte, Einheitlichkeit, Zahlen, englische Fassung. Einsetzen **nachdem** etwas an
der Oberfläche gebaut wurde und **bevor** es in den Echtbetrieb geht.

> Zwei Fallstricke beim Fernsteuern von Chrome, beide beim Bauen aufgelaufen:
> Quasar setzt Knopf-Beschriftungen per CSS in **Großbuchstaben**, `innerText`
> liefert die gerenderte Fassung – ein Vergleich mit „Anmelden" findet
> „ANMELDEN" nicht. Und die umgebende **Karte enthält den Text des Knopfes
> ebenfalls** und steht im Dokument davor; ein Klick auf sie löst nichts aus.
> Deshalb gewinnt das Element mit dem **kürzesten** Text.

## Amtliches PDF-Formular

Dresden bietet das Formular nur über ein Online-System (intelliform) an, kein
Blanko-Download. Daher wurde aus einer eingereichten PDF einmalig eine
Blanko-Vorlage erzeugt: `templates/anmeldung_blank.pdf` – ALLE variablen/
personenbezogenen Werte (Zahlen, Datum, Jahr, Monatskreuz, Dokument-ID,
Betreiberdaten, Kassenzeichen, **Unterschrift**) per Redaction entfernt, nur das
Formular-Layout bleibt (Generator: `tools/make_blank.py`). Die Unterschrift wird
dabei nach `assets/signature.png` extrahiert.

`app/pdf_form.py` setzt je Anmeldung ein: Betreiberdaten + Kassenzeichen aus
`config.json`, die berechneten Werte, das Monatskreuz und die Unterschrift
(`assets/signature.png`, Position über `unterschrift_x` einstellbar).

## Revisionssichere Ablage & erneute Erstellung

Über **„📥 Erzeugen & revisionssicher ablegen"** wird das PDF unveränderbar im
Archiv festgeschrieben (Modul `app/archive.py`):

* Datei → `archive/<jahr>/Beherbergungssteuer_<periode>_v<rev>.pdf`,
  auf **schreibgeschützt (0444)** gesetzt, wird **nie überschrieben**.
* **Erneute Erstellung** eines Monats legt eine **neue Revision** an (v2, v3 …) –
  die alte bleibt erhalten (= „berichtigte Anmeldung"). Über **„👁 Nur Vorschau"**
  lässt sich ein PDF unverbindlich ansehen, ohne es abzulegen.
* Jede Ablage wird in einer **append-only Hash-Kette** (`archive/ledger.jsonl`)
  protokolliert (SHA-256 der PDF + `prev_hash`-Verkettung). Das **Archiv** (📚 oben)
  listet alle Ablagen und prüft die Integrität – jede nachträgliche Änderung an
  Datei oder Eintrag wird erkannt.

**Ablage-Ordner (Computer):** In den Einstellungen (Tab „Archiv") einen Ordner
auf dem Computer wählen (Browser „Durchsuchen"); jede Festschreibung wird dorthin
kopiert – z. B. ein Nextcloud-Sync-Ordner oder ein Buchhaltungs-Ordner. Über das
Archiv (📚) sichert **„🔁 Alles … spiegeln"** den Bestand nachträglich. Schlägt
das Kopieren fehl, bleibt die interne Ablage (`archive/`) trotzdem gültig.

Hinweis: Der Ordner liegt dort, wo die App läuft. Lokal = dein Mac; auf dem
Server = der Server (dann ggf. den Ordner via Mount mit der Cloud verbinden).
Die WebDAV-Funktion im Code (`archive.mirror_entry` via `archiv_webdav`) bleibt
verfügbar, ist in der UI aber nicht mehr eingebunden.

> Pragmatische Revisionssicherheit (Integrität, Unveränderbarkeit, Nachweis +
> externe Kopie). `archive/` ist gitignored.

## Datenaktualität

Smoobu-Daten werden beim **Berechnen** geladen und **5 Minuten** pro Monats-
zeitraum zwischengespeichert. Der **🔄-Button** leert den Cache und lädt frisch;
unter den Eingaben steht „Daten zuletzt von Smoobu geladen: …". Der Webhook
(`/api/smoobu/webhook`) leert den Cache automatisch bei Änderungen in Smoobu.

## Login, Benutzer & Rollen

Die App ist durch einen **Login** geschützt (`app/auth.py`, PBKDF2-Hashes in
`config.auth.users`). Beim allerersten Aufruf legst du unter `/login` den
**ersten Administrator** an (Benutzername + Passwort). Ausgenommen vom
Login-Zwang: Login-Seite, Smoobu-Webhook (`/api/…`), NiceGUI-Interna.

**Einladung statt Startpasswort:** Neue Mitarbeiter legt der Admin unter
**„Benutzer" → „Neuen Benutzer einladen"** mit Benutzername, E-Mail, Rolle und
Sprache an – **ohne Passwort**. Sie erhalten eine E-Mail (in ihrer Profilsprache)
mit einem **Einmal-Link, 7 Tage gültig**, vergeben sich darüber selbst ein
Passwort und sind danach **direkt angemeldet**. In der Benutzerliste steht
solange „Einladung offen – Link gültig bis …"; ein Login-Versuch verweist auf die
Einladungsmail.

**Passwort vergessen (ohne Admin):** Auf der Login-Seite fordert sich jeder über
**„Passwort vergessen?"** selbst einen Link an – mit Benutzername *oder*
hinterlegter E-Mail. Die Seite antwortet immer gleich („wenn es dazu ein Konto
gibt …"), verrät also nicht, welche Konten existieren, zeigt nie einen Link an
und schickt pro Konto höchstens alle zwei Minuten eine Mail. Ohne hinterlegte
E-Mail-Adresse geht das nicht – dann hilft nur der Admin.

Derselbe Weg dient dem **Zurücksetzen durch den Admin**: „Zugang zurücksetzen"
schickt einen neuen Link. Das **bisherige Passwort bleibt gültig, bis der Link benutzt wird** –
so sperrt ein misslungener Mailversand niemanden aus. Wer hart sperren will,
setzt über **„Passwort"** direkt ein neues (das macht einen offenen Link ungültig).

Gespeichert wird nur der **SHA-256-Hash** des Tokens (`auth.new_invite`), der
Klartext-Link existiert also nur im Moment des Versands. Geht die Mail nicht raus
(kein Absender hinterlegt, Gmail streikt) oder fehlt die E-Mail-Adresse, zeigt
die App den Link **einmalig zum Kopieren** an. Die Links zeigen auf die
**Adresse der App** aus den Einstellungen (E-Mail → „Adresse der App",
`config.app_url`, Vorgabe `https://app.ds-apartments.de`) – lokal zum Testen auf
`http://127.0.0.1:3001` stellen.

**Mehrbenutzer & Rollen:** Über **„Benutzer"** (im Menü, nur Admin) lassen sich
weitere Konten einladen, Zugänge zurücksetzen, Rollen ändern oder löschen.
Rollen: `admin` (sieht alles, verwaltet Nutzer/Einstellungen), `manager`
(operative Koordination ohne Steuer und Verwaltung) und `putzkraft`. **Welche
Bereiche eine Rolle sieht, steuert `ROLE_AREAS` in `app/ui/basis.py`.** Nutzer
ohne freigeschaltete Bereiche sehen eine Willkommens-/Hinweisseite.

**Navigation:** Am Handy stehen die Bereiche in einer Leiste unten, ab 1024 px
in der Schublade links. Beides kommt aus `basis.nav_plan(rolle)` – **eine**
Liste für beide Ansichten, sonst laufen sie auseinander. Unten ist Platz für
drei Bereiche plus das Menü; welche drei, sagt `ROLE_BAR` (Putzkraft:
Reinigungen · Zeiten · Belege; Verwaltung: Buchungen · Übersicht · Belege).
Alles Weitere – Zeiterfassung, Beherbergungssteuer, Benutzer, Einstellungen,
Archiv, Mein Konto, Sprache, Abmelden – liegt im Menü. `nav_plan` sortiert nur;
freigeschaltet wird ausschließlich über `ROLE_AREAS`.

**Mein Konto** (jeder Nutzer): eigenes Passwort ändern und **2FA (Google
Authenticator / TOTP)** aktivieren/deaktivieren → ab dann Login mit Passwort **+**
6-stelligem Code.

## Reinigung: Abreise und Anreise strikt getrennt

In einem Reinigungsauftrag stehen zwei Personenzahlen – die der **abreisenden**
und die der **anreisenden** Gäste. Standen beide untereinander in derselben
Karte, wurde regelmäßig die falsche gelesen und für die falsche Personenzahl
eingedeckt (z. B. für 3 Abreisende statt für 2 Anreisende).

Deshalb gilt in der Reinigungskarte: **Abreise und Anreise liegen in getrennten
Tabs** („Vorbereiten" / „Abreise"), Vorreiter ist immer „Vorbereiten".

* **„Vorbereiten"** (`_prep_panel`): farbiger Kasten mit der Anreise-Zahl in
  großer Schrift, darunter die Aufschlüsselung (Erwachsene/Kinder), Gastname und
  Anreisezeitpunkt. Am **Wechseltag** wird der Kasten orange.
* **„Abreise"** (`_depart_panel`): neutral grau, kleine Schrift, **keine große
  Zahl**, mit dem ausdrücklichen Hinweis „Nur zur Info – nicht die Zahl für die
  Vorbereitung."

Die Regel dahinter: **eine große Personenzahl gibt es in der ganzen Oberfläche
nur ein einziges Mal, und die meint immer die Anreise.** Wer das später ändert,
holt den Fehler zurück – `tests/test_web.py::test_abreise_und_anreise_getrennt`
prüft genau das (3 reisen ab, 2 kommen → große Zahl muss „2" sein).

In der **Tagesliste kommender Reinigungen** (Kompaktzeile) steht aus demselben
Grund nur noch „Vorbereiten für N Personen"; die abreisenden Gäste stehen im
Detail-Dialog. Der **Checklisten-Durchgang** zeigt denselben „Vorbereiten
für"-Kasten oben – dort, wo tatsächlich gearbeitet wird.

### „Meine Reinigungen" als Startbildschirm

Sind an einem Tag zwei Reinigungen zu machen – eine für Gabriel, eine für
Valeriya – war in einer gemeinsamen Liste nicht zu erkennen, welche Wohnung für
wen ist. Die Buchungsseite hat deshalb **drei Tabs**:

| Tab | Inhalt |
|---|---|
| **Meine Reinigungen** | nur die eigenen Aufträge – der Startbildschirm |
| **Alle Reinigungen** | alles, hier wird zugewiesen |
| Kalender | unverändert |

**„Meine Reinigungen" ist die Startseite der App.** Nach dem Anmelden landet
man immer dort – `_finish_login` verwirft dazu den gemerkten Bereich, der nur
*innerhalb* einer Sitzung gilt (Neuladen nach einer Aktion). Ist nichts
zugewiesen, führt ein Knopf im Leerzustand direkt zu „Alle Reinigungen".

In der eigenen Liste sind die Chips „n frei" / „n vergeben" sinnlos (alles ist
zugewiesen). Dort stehen im Kopf der Tagesgruppe stattdessen die **Wohnungen** –
die Information, die man morgens braucht. Auch der bernsteinfarbene Warnrahmen
entfällt.

Beide Listen kommen aus derselben Funktion (`_render_cleaning(..., nur_eigene=)`).
Die „Bitte nachtragen"-Erinnerung läuft nur im Alle-Zweig, sonst würde sie bei
jedem Seitenaufbau zweimal ausgelöst.

### Termin in den eigenen Kalender (.ics)

Jede Reinigungskarte hat **„In meinen Kalender"**, ebenso die Aktionsliste im
Buchungs-Dialog. Erzeugt wird eine `.ics`-Datei (`app/ical.py`, reine
Standardbibliothek):

* **Zeitfenster** = Check-out bis zur Anreise der Folgebuchung **am selben Tag**;
  sonst zwei Stunden ab Check-out. Liegt die Anreise vor dem Check-out (kaputte
  Daten), greift ebenfalls die Zwei-Stunden-Regel – ein Termin darf nie vor
  seinem Beginn enden.
* **Titel** „Reinigung <Wohnung>", am Wechseltag mit Zusatz. **Beschreibung**
  mit Check-out, „Vorbereiten für N Personen", Anreisezeit und Gastname.
* **Erinnerung** 60 Minuten vorher (`VALARM`).
* **Zeitzone**: `TZID=Europe/Berlin` mit vollständigem `VTIMEZONE`-Block. Ohne
  den würden Kalender die Zeit als „schwebend" behandeln und bei Sommerzeit
  oder auf Reisen verschieben.
* Text wird nach RFC 5545 maskiert (`; , \` und Zeilenumbrüche) und auf
  **75 Oktette gefaltet** – die Faltung achtet auf UTF-8-Grenzen, sonst
  zerbrächen Umlaute mitten im Zeichen.

Abgedeckt durch `tests/test_ical.py` (9 Tests: Zeitfenster, Wechseltag,
Rückfall bei kaputten Zeiten, Maskierung, Faltung, Erinnerung, Dateiname).

### Freie Reinigungen ohne Aufklappen erkennen

Die kommenden Tage sind zu Gruppen zusammengeklappt. Wer sehen wollte, ob noch
etwas zu vergeben ist, musste jeden Tag einzeln aufklappen – besonders tückisch,
wenn an einem Tag **zwei** Reinigungen anstehen und nur **eine** davon offen ist.

Der Kopf jeder Tagesgruppe zeigt das deshalb direkt (`_tagesgruppe`):

* Chip **„n frei"** (bernstein) für die noch nicht zugewiesenen Reinigungen,
* Chip mit dem **Namen** der Zuständigen, wenn genau eine Person zugewiesen ist,
  sonst **„n vergeben"** (grün),
* der Rahmen der Gruppe wird bernsteinfarben, sobald etwas offen ist,
* über der Liste steht zusätzlich, wie viele Reinigungen **insgesamt** noch
  niemandem zugewiesen sind.

Der Kopf ist ein eigener Quasar-`header`-Slot. Zwei Fallen dabei:

* Quasars **Aufklapppfeil bleibt erhalten** – wer einen eigenen ergänzt, bekommt
  zwei Pfeile nebeneinander.
* Die Chips stehen **unter** dem Datum, nicht daneben. Nebeneinander reicht der
  Platz auf dem Handy nicht: die Datumsspalte schrumpft, das Datum bricht mitten
  um („So" / „02.08.2026") und die Chips laufen darüber. Das Datum steht deshalb
  zusätzlich auf `whitespace-nowrap` und ohne Jahr (die Liste reicht ohnehin nur
  21 Tage).

Zum Nachprüfen der Handy-Darstellung: Chrome headless erzwingt eine
**Mindest-Fensterbreite von ~500 px**, `--window-size=390,…` liefert also nur
einen 390-px-Ausschnitt eines 500-px-Viewports und täuscht abgeschnittene
Ränder vor. Stattdessen den Inhalt in einen Container fester Breite
(`w-[360px]`) legen und in einem breiteren Fenster aufnehmen.

Abgesichert durch
`tests/test_web.py::test_tagesgruppe_zeigt_frei_und_vergeben_ohne_aufklappen`
(zwei Buchungen an einem Tag, eine davon vergeben).

## Zeiterfassung: Übersicht & Abrechnungsstatus

**Für Mitarbeiter** steht über der Zeitenliste eine **eigene Übersicht**
(`_meine_kennzahlen`): Stunden im laufenden Abrechnungsmonat, Ø-Dauer je
Einsatz, Anzahl Einsätze und Wohnungen, Wochenend-/Feiertagsanteil, Vormonat,
Gesamtsumme und – sofern Stundensätze gepflegt sind – der Betrag. Zeitraum ist
immer der **Abrechnungsmonat (19.–18.)**, damit die Zahlen zu dem passen, was
ans Steuerbüro geht.

Darunter der **Abrechnungsstand**: wie viele Stunden noch offen und wie viele
bereits gemeldet sind, mit Fortschrittsbalken.

**Für den Admin** gibt es unter „Auswertung" den Block **Abrechnungsstatus**
(`_abrechnen_block`). Nach dem Versand an den Steuerberater setzt
**„Als abgerechnet markieren"** alle Einträge des gewählten Abrechnungsmonats
auf gemeldet; der Filter „Mitarbeiter" wirkt mit, es lässt sich also auch
einzeln abrechnen. **„Markierung aufheben"** nimmt es zurück. Beides fragt
vorher nach.

Bewusst ein **eigener Schritt** nach dem Senden: der Mailversand kann
scheitern, und manche Meldung läuft über Portal oder Post.

**Wirkung:** Ein abgerechneter Eintrag bekommt in der Liste ein Schloss-Symbol
und ist für Mitarbeiter **nicht mehr änderbar oder löschbar** – sonst weicht der
Bestand von dem ab, was beim Steuerbüro liegt. Der Admin kann weiterhin
korrigieren. Die CSV enthält eine Spalte `Abrechnungsstatus`.

Gespeichert wird direkt am Zeiteintrag in `worklog.json`: `abgerechnet`
(Zeitstempel) und `abgerechnet_von`. Ein bereits markierter Eintrag wird beim
erneuten Markieren nicht überschrieben – der ursprüngliche Meldezeitpunkt
bleibt erhalten.

> Technischer Hinweis: Der Bestätigungsdialog wird in einen **eigenen Container
> außerhalb von `body`** gehängt (`dlg_slot`). Läge er in `body`, würde er beim
> Neuaufbau mitten in seinem eigenen Klick-Handler gelöscht.

## Checklisten & Fotonachweis (Vorgabe: AUS)

Für den Einstieg sind die **Reinigungs-Checklisten ausgeschaltet**
(`config.checklisten_aktiv`, Vorgabe `false`). Sie verlangen Pflege je Wohnung
und Foto-Disziplin – beim Einführen ist das zu viel auf einmal.

**Ausgeschaltet läuft eine Reinigung so:** Arbeitszeit starten → bei Bedarf
Schaden melden, Notiz, Verbrauch/Wäsche → Arbeitszeit beenden. Fertig.

Ausgeblendet werden dann:

* der **Checklisten-Durchgang** (Bereich `reinigung`) samt Soll-/Ist-Fotos,
* die Aktion **„Checkliste & Fotos"** im Buchungs-Dialog,
* **Fortschrittsbalken** und „Weiter zur Checkliste" auf der Reinigungskarte,
* in der Übersicht der Tab **„Durchgänge"** und der Checklisten-Teil der
  **Konfiguration** (die Bestandsliste bleibt – sie speist „Verbrauch/Wäsche"),
* die Checklisten-Spalte in der Zusammenfassung.

**Wichtig für den Status:** `_booking_status` verlangt für „Fertig" sonst eine
vollständig abgehakte Checkliste. Bei ausgeschalteten Checklisten zählt allein
die erfasste Arbeitszeit – sonst käme nie ein „Fertig" zustande.

Wieder einschalten: **Einstellungen → Reinigung**. Es wird nichts gelöscht –
angelegte Checklisten, erfasste Durchgänge und Fotos bleiben erhalten und sind
danach wieder da. Der Absturz-Regressionstest
(`test_checkliste_aus_buchung_stuerzt_nicht_ab`) schaltet die Funktion für sich
ein, die Abdeckung bleibt also bestehen.

## Belegscanner

**Belege → „Beleg scannen"** in zwei Schritten:

1. **Foto aufnehmen** – Kamera öffnet, der Beleg wird mitsamt Rändern
   fotografiert (alternativ ein vorhandenes Foto wählen).
2. **Ecken ziehen** – vier Punkte liegen auf dem eingefrorenen Bild und werden
   per Finger/Maus auf die Belegkanten gezogen. Eine Lupe zeigt den Bereich
   unter dem Finger, der Rest wird abgedunkelt. „Zuschneiden & speichern"
   entzerrt perspektivisch und legt eine **A4-PDF** ab, danach OCR.

Bewusst **ohne automatische Kantenerkennung**: der frühere Versuch mit
OpenCV.js + jscanify traf Belege zu unzuverlässig (Kassenbons auf hellem
Untergrund liefern kaum Kanten) und lud 10 MB WebAssembly. Der Scanner braucht
jetzt **keine Fremdbibliothek** – reines Canvas.

Entzerrt wird **serverseitig** (`receipts.crop_quad`, OpenCV + numpy). Fehlen
die, wird auf einen achsenparallelen Zuschnitt auf das umgebende Rechteck
zurückgefallen (PyMuPDF) – schräg fotografiert bleibt es dann schief, aber der
Rand ist weg.

Wichtig: Das `ui.html` des Scanners muss **`sanitize=False`** setzen, sonst
entfernt NiceGUI `<video>`/`<canvas>` und die Vorschau bleibt schwarz. Kamera
gibt es nur über **HTTPS**.

Der Weg über **„Foto / Datei"** neben dem Scanner bleibt bestehen; dort schneidet
der Server automatisch zu (`receipts.autocrop`).

## Standorterfassung (abschaltbar)

**Einstellungen → Standorte → „Standort bei der Zeiterfassung erfassen"**.
Standard ist **aus**: beim Ein- und Auschecken wird dann weder GPS noch IP
abgefragt oder gespeichert, und die Mitarbeiter werden nicht nach einer
Ortungsfreigabe gefragt. Die Geofence-Liste darunter wirkt nur bei
eingeschaltetem Schalter. Bereits erfasste Standorte älterer Einträge bleiben in
`worklog.json` erhalten.

## Als App auf dem Handy (PWA)

Die Putzkräfte arbeiten ausschließlich am Handy. Über **Teilen → „Zum
Home-Bildschirm"** (iOS) bzw. **Menü → „App installieren"** (Android) landet die
App mit eigenem Symbol auf dem Startbildschirm und öffnet **ohne Adressleiste**.
Die Anleitung dazu steht in der App unter **Mein Konto → „Als App einrichten"**;
am Handy erscheint zusätzlich einmalig ein Hinweis oben auf der Seite (wegtippbar,
Merker im Browser).

Bestandteile (`app/ui/pwa.py`): `/manifest.webmanifest`, die Icons unter
`app/ui/static/` (der **Turm allein** auf Markenviolett – ein Schriftzug ist auf
60 px nicht zu lesen; die maskable-Variante hat mehr Rand, weil Android zum
Kreis beschneidet), `/sw.js` und die Offline-Seite `/offline`.

**Der Service Worker speichert die Anwendung bewusst NICHT.** NiceGUI baut die
Oberfläche über eine offene Verbindung zum Server auf – eine zwischengespeicherte
Hülle ohne Verbindung sähe aus wie die App, wäre aber leer, und veraltetes
JavaScript im Speicher bricht sie nach einem Deploy. Zwischengespeichert werden
ausschließlich die eigenen Dateien unter `/static/`; für alles andere gilt **erst
das Netz**, und schlägt das fehl, kommt statt der Browser-Fehlerseite eine eigene
Seite auf Deutsch und Englisch. Ohne Netz bleibt die App also **lesbar, nicht
schreibfähig** – Background-Sync gibt es auf iOS nicht verlässlich, „offline
erfassen und später senden" wäre nicht zu halten.

> **Falle:** Das Handy holt Manifest und Icon, **bevor** sich jemand anmeldet.
> Ohne Ausnahme in der Login-Schranke (`_UNRESTRICTED` und `/static/` in
> `app/web.py`) bekommt iOS dort HTML statt eines Icons: das Symbol bliebe grau
> und der Service Worker ließe sich gar nicht erst registrieren. Abgesichert
> durch `tests/test_pwa.py::test_icons_und_manifest_sind_ohne_login_erreichbar`.

Stand iOS 26 (an den WebKit-Quellen geprüft): Home-Screen-Web-Apps werden
unterstützt, seit iOS 26 sogar **ohne** Anforderungen an die Installierbarkeit.
Die kurzzeitige Abschaltung in der EU (iOS-17.4-Beta, Februar 2024) wurde im
März 2024 zurückgenommen. Safari kennt aber **keinen** Installations-Dialog –
daher die Anleitung – und **Push-Benachrichtigungen kommen nur an, wenn die App
auf dem Home-Bildschirm liegt**; im Safari-Tab nicht. Genau deshalb steht dieses
Paket vor den Benachrichtigungen (AP7).

## Kennzahlen: was bleibt übrig?

**Übersicht → Kennzahlen.** Ein Monat, vier Zahlen, eine Tabelle je Wohnung.
Die Daten lagen längst da – Buchungen in Smoobu, Arbeitszeiten im Zeitkonto,
Belege in der Ablage –, nur zusammengeführt hatte sie niemand.

| Größe | Woraus |
|---|---|
| **Auslastung** | belegte Nächte ÷ Nächte des Monats (je Wohnung) |
| **Umsatz** | Rechnungsbetrag **ohne** durchlaufende Beherbergungssteuer |
| **Reinigung** | erfasste Arbeitszeit × Stundensatz des Mitarbeiters |
| **Material** | Belege, die dieser Wohnung zugeordnet sind |
| **Deckungsbeitrag** | Umsatz − Reinigung − Material |

Drei Dinge, die man wissen muss, sonst deutet man die Zahlen falsch:

**Der Deckungsbeitrag ist kein Gewinn.** Portalprovisionen, Nebenkosten,
Abschreibung, Zinsen und die eigene Arbeitszeit stecken nicht darin. Er
beantwortet „trägt diese Wohnung ihren laufenden Betrieb?", nicht „was
verdiene ich?".

**Die Zahl passt bewusst nicht zur Steueranmeldung.** Hier werden Nächte dem
Monat zugeordnet, in dem sie liegen (eine Buchung vom 29.10. bis 2.11. bringt
drei Nächte in den Oktober und zwei in den November, der Umsatz im selben
Verhältnis). Die Steueranmeldung ordnet dagegen die **ganze Buchung dem
Abreisemonat** zu (§ 6 der Satzung) und lässt Airbnb außen vor. Beides ist
richtig – für verschiedene Fragen. Wer die Zahlen nebeneinanderlegt und
Gleichheit erwartet, sucht lange.

**Die Preisregel steht nur an einer Stelle** (`steuer.ohne_citytax`): dieselbe
Funktion beliefert Steueranmeldung und Auswertung. Zwei Rechenwege für „was
bleibt vom Rechnungsbetrag" wären der sichere Weg in zwei widersprüchliche
Zahlen. Bei **Airbnb** wird nichts abgezogen: dort steht die Steuer als „Airbnb
Collected Tax" getrennt und wird beim Gast **zusätzlich** eingezogen (in der
Dezember-Fixture exakt 6 % *auf* den Preis, nicht darin) – abzuziehen wäre
schlicht falsch.

Weitere Festlegungen: Belege **ohne** Wohnung landen unter „ohne Zuordnung"
statt still verteilt zu werden (eine erfundene Aufteilung sähe genauer aus, als
sie ist). Eine Wohnung ohne Buchungen bleibt mit 0 % in der Tabelle – das ist
eine Aussage, keine Leerstelle. **Stornierte Buchungen zählen nicht**, auch
nicht mit Airbnb-Ausfallzahlung; wer die sehen will, findet sie in Smoobu.

Darunter stehen die zehn **teuersten Reinigungen** mit Dauer, Kosten und
Zuständigem – die Frage „was kostet mich eine Reinigung in der Wernerstraße?"
brauchte bisher Zettel und Stift.

## Zuweisen mit Vorschlag

Jede Zuweisung war Handarbeit: Buchung öffnen, „Tauschen/Zuweisen", Person
wählen. Bei zwei Wohnungen geht das; bei zehn ist es jeden Sonntagabend eine
halbe Stunde, und der eine übersehene Tag fällt erst am Morgen auf.

**„Offene zuweisen"** steht jetzt im gelben Hinweis über der Liste „Alle
Reinigungen": alle unverteilten Reinigungen der nächsten 14 Tage auf einem
Blatt, je Zeile ein Vorschlag, den man ändern kann, ein Knopf am Ende.

Der Vorschlag (`app/planung.py`, ohne Oberfläche und damit prüfbar):

1. **Stammzuständigkeit** der Wohnung (Übersicht → Konfiguration) – wer macht
   sie normalerweise? Das beantwortet die meisten Fälle.
2. Ist diese Person **abwesend**, fällt sie raus.
3. Sonst: wer bis dahin **am wenigsten** zu tun hat, damit sich kein Stapel auf
   einer Person häuft. Bereits vergebene Reinigungen zählen mit.

Festlegungen, die im Alltag zählen:

* **Die Stammzuständigkeit schlägt die Last.** Sonst wandert eine Wohnung bei
  jedem Stapel zu jemand anderem – und mit ihr das Wissen, wo der Schlüssel
  hängt und welcher Rollladen klemmt.
* **Ist niemand verfügbar, gibt es keinen Vorschlag** statt eines falschen. Die
  Lücke muss auffallen.
* **Wer abwesend ist, steht trotzdem in der Auswahl** – mit dem Zusatz
  „abwesend". Manchmal weiß der Mensch mehr als der Kalender.
* **Gespeichert wird nie automatisch.** Man sieht den Vorschlag, ändert ihn,
  bestätigt. Automatisches Zuweisen macht genau die Fehler, die niemand sucht –
  weil ja „das System" zugewiesen hat.
* Beim Sammelzuweisen bekommt jeder **eine** Benachrichtigung mit allen seinen
  Reinigungen, nicht zehn hintereinander.

**Abwesenheiten** trägt jeder selbst ein: Mein Konto → Abwesenheiten (von, bis,
Grund). Die Verwaltung sieht die nächsten 14 Tage unter Übersicht →
Konfiguration. Der letzte Tag zählt als abwesend – der klassische Fehler an
dieser Stelle, deshalb mit eigenem Test.

> **Falle, die dabei hochkam:** Der Dialog hängt in der Liste, die er nach dem
> Zuweisen neu aufbaut. Ein direkter Aufruf löscht ihn mitten in seinem eigenen
> Klick-Handler – dieselbe Falle wie beim Abrechnungs-Dialog. Der Neuaufbau
> läuft deshalb über `ui.timer(..., once=True)`, also erst nach dem Klick.

## Benachrichtigungen (Web Push)

Eine neue Zuweisung landete bisher per E-Mail in einem Postfach, das am
Arbeitstag niemand aufmacht. Jetzt kommt sie auf dem **Sperrbildschirm** an –
wie eine Nachricht. E-Mail bleibt daneben bestehen, weil nicht jeder die App
eingerichtet hat.

Einschalten: **Mein Konto → Benachrichtigungen → „Auf diesem Gerät
einschalten"**. Dort stehen auch die angemeldeten Geräte, ein Knopf für eine
**Testnachricht** und die Schalter, wobei man Bescheid bekommen möchte.

| Meldeart | Wann | An wen |
|---|---|---|
| `zuweisung` | jemand weist eine Reinigung zu | den Zugewiesenen |
| `erinnerung` | täglich 18:00 (`rentaltool-erinnerung.timer`) | jeden mit Reinigungen am Folgetag; die Verwaltung zusätzlich, wenn für morgen etwas **niemandem** zugewiesen ist |
| `nachtragen` | Reinigung nach Check-out ohne erfasste Zeit | den Zugewiesenen |
| `schaden` | jemand meldet einen Schaden | Admin und Manager |

Wer für morgen nichts hat, bekommt auch nichts – eine Erinnerung, die jeden
Abend „nichts zu tun" sagt, wird nach einer Woche weggewischt, und dann auch die
wichtige.

**Verschlüsselung und VAPID übernimmt `pywebpush`.** Das ist bewusst keine
Eigenbau-Stelle: Web Push verlangt ECDH, HKDF und AES-GCM nach RFC 8291, und ein
Fehler darin zeigt sich nicht als Absturz, sondern als „kommt bei manchen
Geräten still nicht an". Der Test dazu verschlüsselt wie im Betrieb und macht
die Nachricht mit dem privaten Schlüssel des „Geräts" wieder auf.

Die **VAPID-Schlüssel** liegen in `config.json` unter `push` und entstehen beim
ersten Einschalten. Sie identifizieren unseren Server gegenüber Apple und
Google: **werden sie ausgetauscht, sind alle bestehenden Anmeldungen wertlos** –
deshalb werden sie nie stillschweigend neu erzeugt, und wenn doch
(`schluessel_erzeugen(neu=True)`), werden die Anmeldungen gleich mit aufgeräumt.

Weitere Festlegungen:

* **Die Anmeldung läuft über die bestehende Sitzung**, nicht über eine eigene
  API-Route. Eine solche Route müsste ohne Login erreichbar sein – und dann
  könnte jeder fremde Geräte auf fremde Konten anmelden.
* **Antwortet der Push-Dienst mit 404/410, wird die Anmeldung gelöscht** (App
  entfernt, Erlaubnis entzogen). Ein Netzausfall löscht dagegen nichts, sonst
  müsste sich nach jeder Störung jeder neu anmelden.
* **Dasselbe Gerät zweimal bleibt ein Eintrag** – sonst kommt jede Meldung
  doppelt. Meldet sich jemand anders auf demselben Gerät an, wechselt der
  Eintrag den Besitzer.
* Der Service Worker zeigt **jede** Push-Nachricht an (`userVisibleOnly`); tut er
  das nicht, entziehen die Browser die Erlaubnis wieder.

> **iOS:** Benachrichtigungen kommen **nur an, wenn die App auf dem
> Home-Bildschirm liegt** (siehe oben). Im Safari-Tab nicht. Steht die App dort
> nicht, zeigt „Mein Konto" statt des Knopfes einen Hinweis mit der Anleitung.

## Sprache (Deutsch / Englisch)

Die **Mitarbeiterbereiche** – Login, Mein Konto, Buchungen, Reinigungs-
Checklisten, Belege, Zeiterfassung – gibt es auf Deutsch und Englisch. Der
**Verwaltungsteil** (Beherbergungssteuer, Auswertung, Einstellungen,
Benutzerverwaltung) ist bewusst nur deutsch: Steuerbegriffe haben keine
belastbare englische Entsprechung, und diese Bereiche bedient nur der Betreiber.
Ebenfalls deutsch bleiben das **amtliche PDF** und die **Mail an den
Steuerberater** – beides geht an deutsche Empfänger.

Umschalten: **Mein Konto → Sprache** (gilt sofort und wird im Profil
gespeichert) oder als Admin je Mitarbeiter in der **Benutzerverwaltung**. Auf
der Login-Seite lässt sich die Sprache ebenfalls wählen; nach dem Anmelden
gewinnt die im Profil hinterlegte.

Technik: `app/i18n.py` mit `t("deutscher Text")`. **Der deutsche Text ist
zugleich der Schlüssel** – fehlt eine Übersetzung, erscheint unverändert das
Deutsche, eine Lücke kann die Oberfläche also nie leeren. Neue Sprache =
weiteres Wörterbuch in `TRANSLATIONS`.

> **Falle:** `t` ist die Übersetzungsfunktion – niemals als Schleifen- oder
> Parametername verwenden. In `reinigung_putzkraft` hieß die Aufgaben-Variable
> `t` (`for t in all_tasks:`); dadurch wurde `t` zur **lokalen Variable der
> ganzen Funktion**, und `t("Check-out")` weiter oben warf `UnboundLocalError`.
> Ergebnis: Die Checkliste stürzte genau auf dem Normalweg ab – geöffnet aus
> einer Buchung, denn nur dort sind Check-out-/Check-in-Zeiten gesetzt. Die
> Aufgaben-Variable heißt jetzt `task`; abgesichert durch
> `tests/test_web.py::test_checkliste_aus_buchung_stuerzt_nicht_ab`.

## Rücksprung: Aktionen landen wieder im Ausgangsbereich

Aktionen aus einem Buchungs-Dialog (Schließen, „Checkliste & Fotos") bauen die
Liste dahinter neu auf. Das Ziel war fest auf `buchungen` verdrahtet – wer aus
der **Übersicht** kam, landete danach in den **Buchungen**.

Die Sitzung merkt sich deshalb den aktuellen Bereich (`_cur_area()`, gesetzt in
`activate()`, gespeichert in `app.storage.user`). Bewusst **pro Sitzung** und
nicht global: sonst würden sich mehrere angemeldete Nutzer gegenseitig
umschalten. `reinigung` wird nicht gemerkt – das ist ein Zwischenschritt, kein
Bereich.

Nicht übersetzt werden **Inhalte aus den Datendateien** (Checklisten-Punkte,
Wohnungsnamen, Notizen, Inventar) – sie erscheinen so, wie sie angelegt wurden.

## Benutzer per Kommandozeile (`tools/useradmin.py`)

Für alles, was ohne laufende Oberfläche gehen muss – ausgesperrt, Konto direkt
auf dem Server anlegen, 2FA entfernen, Zugangslink erzeugen wenn der Mailversand
hakt. Arbeitet direkt auf `config.json`, legt vorher eine Sicherung an und
schreibt atomar.

```bash
python3 tools/useradmin.py liste                     # Konten, Rollen, 2FA, Zustand
python3 tools/useradmin.py passwort admin --email ich@example.com
python3 tools/useradmin.py passwort bea --rolle manager   # legt das Konto an
python3 tools/useradmin.py link admin                # Einmal-Link OHNE E-Mail
python3 tools/useradmin.py rolle anna manager
python3 tools/useradmin.py 2fa-aus admin
python3 tools/useradmin.py loeschen anna
```

Ohne `--passwort` wird verdeckt abgefragt (nichts landet in der Shell-History).
`liste` gibt weder Hashes noch TOTP-Secrets aus. Den letzten Administrator
löscht das Werkzeug nicht.

**Auf dem Server** (`/opt/rentaltool`, Dienst `rentaltool.service`) muss die App
danach neu starten – sie hält die Konfiguration im Speicher und würde die
Änderung sonst beim nächsten Speichern überschreiben:

```bash
cd /opt/rentaltool
.venv/bin/python tools/useradmin.py passwort admin --neustart
```

`link` ist der Rettungsweg, wenn keine Mail rausgeht: Der ausgegebene Link führt
direkt auf `/invite`, dort setzt man sein Passwort selbst. Er ersetzt einen
vorher erzeugten Link, ist einmal verwendbar und 7 Tage gültig.

> Ganz ausgesperrt und kein Werkzeug zur Hand? In `config.json` `auth.users` auf
> `{}` setzen – beim nächsten Aufruf legst du den Admin neu an, **verlierst aber
> alle Mitarbeiterkonten**. `config.json` ist gitignored.

## E-Mail-Versand (Gmail)

Über **„✉️ Ablegen & per E-Mail senden"** wird das Formular festgeschrieben und
als PDF-Anhang an einen **fest konfigurierten Empfänger** geschickt (Modul
`app/mailer.py`, SMTP über Gmail). Vor dem Senden erscheint ein Dialog mit
Betreff + Text (aus der Vorlage vorbefüllt, für diesen Versand editierbar).

Einrichtung in den Einstellungen (E-Mail): **Absender** (Gmail-Adresse),
**Gmail App-Passwort** (nicht das normale Passwort – erfordert 2FA), fester
**Empfänger**, optional Cc sowie **Betreff-/Text-Vorlage** mit Platzhaltern
`{monat} {jahr} {periode} {steuer} {umsatz} {kassenzeichen} {name}`. Die Vorlage
wird in `config.json` gespeichert (App-Passwort inklusive – gitignored).

## Einstellungen

Unter **⚙️ Einstellungen** (`/settings`) lassen sich die PDF-Felder bearbeiten:
Betreiberdaten (Name, Adresse, **Telefon**, Kassenzeichen …), Unterschrift-Position,
Steuersatz, Smoobu-API-Key, Airbnb-Kanalname. Gespeichert wird in `config.json`
(lokal, nicht im Repo).

## Rechenregeln (Satzung Dresden v. 7.5.2015 + Vorgaben Betreiber)

* **Monatszuordnung nach Abreisedatum** (§6: Steuer entsteht mit Abreise).
  Reicht eine Buchung in den Folgemonat, zählt sie im Folgemonat.
* **Nur bereits stattgefundene Buchungen** (Abreise ≤ heute). Geplante /
  künftige Buchungen werden nicht berechnet.
* **Übernachtungen = Personen (Erwachsene + Kinder) × Nächte**.
* Ausgeschlossen: Stornos (`type = cancellation`) und Blockierungen.
* **Airbnb** wird separat aus Smoobu berechnet und ausgewiesen; diese ÜN
  fließen NICHT in die steuerpflichtigen Umsätze ein (Airbnb meldet und führt
  selbst an Dresden ab). Override-Feld nur für Ausnahmen.
* **Steuerbasis je Buchung = Buchungspreis ohne durchlaufende
  Übernachtungssteuer** (Reinigungsgebühr bleibt enthalten). Die vom Gast
  gezahlte Übernachtungssteuer ist ein Durchlaufposten und wird nicht erneut
  besteuert. Der Smoobu-`price` ist **immer brutto inklusive** dieser Steuer:
  steht sie als Zeile in `price-details`, wird dieser Betrag abgezogen; fehlt
  die Zeile, wird `price / 1,06` herausgerechnet (siehe unten).
* **Steuer = 6 %** der steuerpflichtigen Umsätze, kaufmännisch gerundet.

Validiert gegen zwei Monate:
* **Dezember 2025**: 137 verbl. ÜN · 15 Airbnb · 152 insgesamt · 5.698,29 € ·
  **341,90 € Steuer**. (Das eingereichte Formular hatte Airbnb falsch mit 7
  angegeben – ohne Auswirkung auf die Steuer.)
* **Mai 2026**: 14 Buchungen · 7.155,86 € verbleibender Umsatz.

### Warum nicht auf die Summe der Rechnungsbeträge?

Die häufigste Verwechslung – deshalb hier festgehalten. Die Summe dessen, was
die Gäste **insgesamt gezahlt** haben, ist **nicht** die Bemessungsgrundlage:
darin steckt schon die Beherbergungssteuer, die die Portale beim Gast kassiert
haben. 6 % darauf wäre Steuer auf die Steuer.

Dezember 2025 zeigt es, weil es dazu die eingereichte Anmeldung gibt:

| | |
|---|---:|
| Summe Rechnungsbeträge | 5.991,89 € |
| − darin enthaltene Beherbergungssteuer | 293,61 € |
| **= Bemessungsgrundlage** | **5.698,28 €** |
| × 6 % | **341,90 €** ✅ eingereicht |

Auf die Rechnungsbeträge gerechnet kämen 359,51 € heraus – 17,61 € zu viel.

Rechtlich: Bemessungsgrundlage ist nach **§ 4 Abs. 1 der Satzung** das
Beherbergungsentgelt *einschließlich Umsatzsteuer* (die Reinigungsgebühr gehört
nach **FAQ 5.2** ausdrücklich dazu); die Beherbergungssteuer selbst ist nach
**FAQ 5.11** „lediglich durchlaufender Posten" und zählt nicht mit.

Begriffe deshalb bewusst so und nicht anders: **Rechnungsbetrag** (was der Gast
zahlt) − **enthaltene BSt** = **Bemessungsgrundlage** × 6 % = **Steuer**. Das
Wort „Bruttopreis" ist hier verboten – es liest sich wie „alles inklusive" und
meint je nach Leser beide Beträge.

Nach **„Berechnen"** zeigt die Oberfläche genau diese Kette zweimal: als
**Summen-Tabelle** (`_summen_tabelle` in `app/web.py`, mit Spalte „Formular /
nachrichtlich", damit klar ist welche Zeile eingereicht wird) und je Buchung
als vier Spalten in der Buchungstabelle. Abgesichert durch
`tests/test_web.py::test_summen_tabelle_zeigt_die_kette`.

### Wenn Smoobu die Steuer nicht ausweist

**Smoobu liefert die Beherbergungssteuer nicht als Datenfeld.** Das Feld
`city-tax` existiert in der API, ist aber bei **allen** Buchungen `null`; der
Einzelbuchungs-Endpunkt liefert kein einziges zusätzliches Feld. Einzige Quelle
ist der **Freitext** `price-details` – und der ist nur bei Portalen gefüllt:

| Kanal | Buchungen | mit `price-details` | mit Zeile „Übernachtungssteuer" |
|---|---:|---:|---:|
| Booking.com | 191 | 172 | 152 |
| Airbnb | 18 | 18 | 0 (heißt dort „Airbnb Collected Tax") |
| Direct booking | 6 | 0 | 0 |
| Website | 1 | 0 | 0 |

Fehlt die Zeile, ist die Steuer trotzdem im Preis – sie wird nur nicht
aufgeschlüsselt. Belegt durch die **Gastrechnungen**, die jede Buchung als
eigene Position mit 0 % USt ausweisen:

| Rechnung | Kanal | Übernachtung | Reinigung | Basis | Beherbergungssteuer | Satz |
|---|---|---:|---:|---:|---:|---:|
| 60 Anja Ernst | Direktbuchung | 312,42 € | 65,00 € | **377,42 €** | 22,65 € | 6,00 % |
| 74 Katarina Gockel | Direktbuchung | 293,00 € | 65,00 € | **358,00 €** | 21,48 € | 6,00 % |
| 77 Jan Peters | Booking.com | 226,50 € | 75,00 € | 301,50 € | 18,09 € | 6,00 % |
| 78 Alexander Josan | Booking.com | 358,66 € | 75,00 € | 433,66 € | 26,02 € | 6,00 % |
| 61 Kusala Sami | Booking.com | 108,08 € | 95,00 € | 203,08 € | 14,22 € | **7,00 %** |
| 71 Christian Michael | Booking.com | 584,39 € | 95,00 € | 679,39 € | 47,56 € | **7,00 %** |

`400,07 / 1,06 = 377,42` – die Umrechnung trifft die Rechnung auf den Cent.
Deshalb: **ausgewiesener Betrag schlägt Umrechnung** (nur so werden die 7 %
der Wernerstraße korrekt abgezogen), sonst `price / 1,06`. Airbnb bleibt außen
vor. Alle sechs Rechnungen liegen als Golden-Tests in
`tests/test_steuer.py::TestGastrechnungen`.

> **Offen:** Die Wernerstraße rechnet mit **7 %** statt 6 %. Die Gäste zahlen
> dort zu viel (bei Rechnung 71: 47,56 € statt 40,76 €), abgeführt werden
> korrekt 6 %. Die Einstellung gehört in Smoobu/Booking.com auf 6 % korrigiert.

> Randfall: Buchungen **ohne** ausgewiesene `Übernachtungssteuer`-Zeile
> (typisch Direktbuchungen) gehen mit dem **vollen Betrag** in die Basis. Ist
> dort die Steuer im Preis schon enthalten, wird sie mitbesteuert. Bei
> Direktbuchungen die Beherbergungssteuer daher separat ausweisen.

## Datenordner: Code und Betriebsdaten getrennt

Auf dem Server liegt das Repo unter `/opt/rentaltool` und wird per `git pull`
erneuert. Die Betriebsdaten liegen **daneben** in `/var/lib/rentaltool`:
Konten (`config.json`), Arbeitszeiten, Zuweisungen, Belege, Reinigungsdaten,
Fotos (`media/`), das Steuerarchiv (`archive/`) sowie Vorlage und Unterschrift
(`templates/`, `assets/` – beide personenbezogen und gitignored).

Gesteuert über die Umgebungsvariable **`RENTALTOOL_DATA`** (`app/paths.py`).
**Ohne die Variable bleibt alles wie bisher**: Datenordner = Projektordner, also
unverändert für lokale Entwicklung und Tests.

```bash
python3 tools/migrate_data.py /var/lib/rentaltool           # Probelauf: was würde umziehen
python3 tools/migrate_data.py /var/lib/rentaltool --jetzt   # verschieben
```

Verschoben, nicht kopiert – zwei Bestände wären schlimmer als einer. Vorhandene
Dateien im Ziel werden nie überschrieben.

> **Schutz gegen den gefährlichsten Fehler:** Steht `RENTALTOOL_DATA`, fehlt dort
> aber `config.json`, während sie noch im Projektordner liegt, **startet die App
> nicht** (`app/data.py`) und sagt, was zu tun ist. Ohne diese Prüfung liefe sie
> mit leerer Konfiguration hoch und böte an, einen neuen Administrator anzulegen –
> während die echten Konten unbemerkt daneben lägen.

## Datenhaltung: SQLite

Arbeitszeiten, Zuweisungen, Belege und die Reinigungsdaten liegen in
**einer SQLite-Datei** (`rentaltool.db` im Datenordner, Modul `app/db.py`).
Vorher war jeder Bestand eine JSON-Datei, die bei **jeder** Änderung komplett
neu geschrieben wurde – bei acht Zeiteinträgen egal, bei ein paar tausend nicht
mehr. Dazu ließen sich mehrere Dateien nie gemeinsam ändern: eine Zuweisung
löschen *und* die zugehörigen Zeiten entfernen waren zwei Schreibvorgänge mit
einer Lücke dazwischen.

**Der Datensatz bleibt ein Python-Dict.** Jede Zeile speichert den vollständigen
Satz als JSON in der Spalte `daten`; die Felder, nach denen gesucht wird, hängen
als **generierte Spalten** daran:

```sql
CREATE TABLE zeiten (
  id    TEXT PRIMARY KEY,
  daten TEXT NOT NULL,
  benutzer GENERATED ALWAYS AS (json_extract(daten, '$.user')) VIRTUAL,
  ende     GENERATED ALWAYS AS (json_extract(daten, '$.checkout')) VIRTUAL, …
```

Generiert heißt: SQLite leitet sie aus `daten` ab, sie können also gar nicht
auseinanderlaufen. Damit bleibt der Code der Fachmodule so, wie er war (Dicts
rein, Dicts raus), und Auswertungen bekommen trotzdem echte Indizes – die
Grundlage für das Kennzahlen-Dashboard (AP9).

Festlegungen, die man kennen sollte:

* **`speichern()` macht UPDATE, nicht `INSERT OR REPLACE`.** Letzteres löscht die
  Zeile und legt sie neu an – sie bekäme eine neue `rowid` und spränge in der
  Liste ans Ende. Die Reihenfolge ist aber sichtbar („neueste zuerst").
* **Transaktionen schachteln sich.** `start_run` ruft innen `get_open_run`; ohne
  Schachtelung würde ein inneres `COMMIT` die äußere Klammer vorzeitig
  festschreiben.
* **Jeder Thread hat seine eigene Verbindung** (NiceGUI arbeitet mit
  Hintergrund-Threads), im WAL-Modus ausdrücklich vorgesehen.

**Nicht** in der Datenbank: `config.json` (Konten – im Notfall mit einem
Texteditor zu reparieren, `tools/useradmin.py` arbeitet darauf),
`archive/ledger.jsonl` (die Hash-Kette der Steuerablage soll ein Prüfer ohne
unsere Software lesen können) und die Fotos unter `media/`.

### Übernahme der Altbestände

```bash
python3 tools/migrate_db.py            # Probelauf
python3 tools/migrate_db.py --jetzt    # übernehmen, gegenlesen, alte Dateien umbenennen
```

Läuft einmal je Installation und ist bewusst misstrauisch: die Datenbank muss
leer sein (sonst stünde nach dem zweiten Lauf alles doppelt darin), übernommen
wird **in Dateireihenfolge**, und danach wird **gegengelesen** – jeder Satz muss
sich unverändert und in derselben Reihenfolge wieder herausholen lassen. Erst
dann werden die alten Dateien in `<name>.vor-sqlite` umbenannt; gelöscht wird
nichts. Der Rückweg ist damit: vorherigen Stand ausrollen, Dateien
zurückbenennen.

## Speicherschicht: atomar schreiben, gesperrt ändern

`app/store.py` regelt den verbliebenen Dateizugriff – vor allem `config.json`.
(Die Bestände liegen seit AP5 in der Datenbank, siehe oben.) Vorher machte jedes
Modul „ganze Datei lesen → im Speicher ändern → ganze Datei überschreiben".
Darin steckten zwei Fehler:

**Nicht atomar.** `open(pfad, "w")` kürzt die Datei sofort auf 0 Bytes. Wer in
diesem Moment abstürzt – Neustart, OOM-Killer, volle Platte – hinterlässt eine
leere oder halbe Datei. Bei `config.json` hieße das: alle Konten weg.
Geschrieben wird jetzt in eine Nachbardatei, auf die Platte gezwungen (`fsync`)
und erst dann per `os.replace` umgehängt – ein Schritt, den das Dateisystem
entweder ganz oder gar nicht macht.

**Nicht gesperrt.** Zwischen Lesen und Zurückschreiben liegt eine Lücke.
Schreibt in dieser Lücke jemand anders, ist dessen Änderung still verloren.

```python
with store.edit(LOG, []) as a:      # Sperre über die GANZE Änderung
    a.wert.append(eintrag)          # geschrieben wird beim Verlassen
```

Wie groß der Unterschied ist, zeigt der Gegentest: vier Prozesse hängen
gleichzeitig je 25 Einträge an dieselbe Datei. Mit der alten Arbeitsweise
überlebten **38 von 100** Einträgen, und drei der vier Prozesse stürzten beim
Lesen einer halb geschriebenen Datei ab. Mit `store.edit` sind es 100.
`tests/test_store.py` prüft beides – die Parallelität mit echten Prozessen, den
Abbruch mit einem echten `SIGKILL` mitten im Schreiben.

Weitere Festlegungen:

* Eine **kaputte Datei fällt nicht still auf die Vorgabe zurück**, sondern wirft
  `store.DatenFehler`. Ein stiller Rückfall auf `[]` würde beim nächsten
  Schreiben den noch vorhandenen Bestand endgültig überschreiben – aus einer
  lesbaren Panne würde ein Datenverlust.
* Gesperrt wird über eine Beidatei `<name>.lock`, nicht über die Datei selbst:
  `os.replace` hängt eine **neue** Datei an den Namen, eine Sperre auf der alten
  wäre danach wertlos.
* Die Sperre ist **im selben Thread erneut betretbar**, sonst verklemmte sich die
  App, sobald zwei Funktionen dieselbe Datei schachteln.
* Nach 10 Sekunden Warten gibt es einen `store.SperrFehler` statt einer
  Oberfläche, die ohne Erklärung stehenbleibt.

Auch das **Steuerarchiv** hängt daran: Revision ermitteln, PDF ablegen und den
Ledger-Eintrag anhängen laufen unter einer Sperre. Liefen zwei Ablagen
gleichzeitig, bekämen beide dieselbe Revision und dasselbe `prev_hash` – die
Hash-Kette wäre gebrochen, und genau die soll ja etwas beweisen. Das PDF selbst
wird ebenfalls über eine Nachbardatei geschrieben, sonst bliebe nach einem
Abbruch ein halbes PDF zurück, dessen Prüfsumme nicht zum Ledger passt.

## Sicherung (Nextcloud)

`tools/backup.py` sichert den **gesamten Datenordner** täglich als `tar.gz` in die
Nextcloud. Ziel steht in `config.json` als `backup_ziel`:

```json
"backup_ziel": "nextcloud:03 Immobilien/DS Apartments & Suites/Backups/rentaltool"
```

Enthält der Wert einen `remote:`-Präfix, läuft die Übertragung **direkt über
rclone** – bewusst am FUSE-Mount `/mnt/nextcloud` vorbei: rclone prüft die
Prüfsumme nach dem Hochladen, der Mount tut das nicht. Ein Pfad ohne Präfix wird
als lokaler Ordner behandelt (Tests, lokale Installation).

```bash
python3 tools/backup.py sichern    # bauen, prüfen, hochladen, aufräumen
python3 tools/backup.py pruefen    # jüngste Sicherung zurückholen und auspacken
python3 tools/backup.py liste      # Bestand am Ziel
```

**Was „geprüft" heißt.** Ein `tar` ohne Fehlermeldung sagt nichts darüber, ob der
Inhalt brauchbar ist. Vor dem Hochladen wird das Paket deshalb wieder ausgepackt
und dreifach gelesen: jede JSON-Datei muss sich parsen lassen, es müssen
**Benutzerkonten** enthalten sein (ohne sie wäre die Wiederherstellung wertlos),
und die **Hash-Kette des Steuerarchivs** muss unversehrt sein. Schlägt eines
davon fehl, wird **nicht hochgeladen und nicht aufgeräumt** – die letzte heile
Sicherung bleibt damit stehen.

Eine defekte Datei im laufenden Betrieb bricht die Sicherung dagegen **nicht** ab:
genau dafür ist sie da. Sie wird mitgesichert und gemeldet.

**Aufbewahrung:** die 14 jüngsten Stände, dazu die letzten 8 Sonntage und die
letzten 12 Monatsersten. Bewusst „die 14 jüngsten" statt „alles der letzten 14
Tage" – bleibt die Sicherung mal zwei Wochen aus, wären nach der zweiten Lesart
beim nächsten Lauf fast alle Stände auf einen Schlag fällig. Fremde Dateien am
Ziel werden nie angefasst.

**Nicht** gesichert werden Programmcode (steht im Git) und `.nicegui/` (nur
Sitzungen, ~80 MB).

Zeitpläne (`deploy/`, nach `/etc/systemd/system/`):

| Timer | Wann | Was |
|---|---|---|
| `rentaltool-backup.timer` | täglich 03:30 | sichern |
| `rentaltool-backup-pruefen.timer` | montags 04:30 | Wiederherstellung üben |

Beides in **UTC** – der Server läuft so, nur der App-Prozess stellt sich auf
Berlin (`app/web.py`). 03:30 UTC = 05:30 Berlin im Sommer.

Die wöchentliche Probe ist Absicht: eine Sicherung, die nie zurückgeholt wurde,
ist keine Sicherung. Scheitert etwas, geht eine E-Mail an den
Benachrichtigungs-Absender und der Timer meldet den Fehlschlag. Der letzte Lauf
steht in `backup-status.json` im Datenordner.

## Ausrollen, Probe-Instanz, Wächter

### Ausrollen

```bash
tools/deploy.sh probe      # aktueller Zweig -> Probe-Instanz (Port 3002)
tools/deploy.sh echt       # main -> app.ds-apartments.de (Port 3001)
```

Vorher lief das von Hand: `git pull`, `systemctl restart`, hoffen. Das Skript
macht daraus einen Ablauf mit Netz:

1. Arbeitsverzeichnis sauber? Echtbetrieb nur aus `main`.
2. **Tests laufen zuerst** (`--ohne-tests` überspringt das).
3. Ausrollen, Dienst neu starten.
4. **Rauchprobe:** Antwortet `/login` mit dem Anmeldeformular, und steht kein
   Fehler im Journal? Bewusst der Seiteninhalt und nicht nur „Prozess läuft" –
   ein Prozess, der beim Rendern abstürzt, wäre sonst nicht zu unterscheiden.
5. Schlägt die Probe fehl: **automatisch zurück auf den vorherigen Stand**,
   erneut prüfen, Journal ausgeben.

### Probe-Instanz

Zweiter Dienst auf Port 3002 (`/opt/rentaltool-staging`, Daten in
`/var/lib/rentaltool-staging`). Erreichbar über einen SSH-Tunnel – damit ist sie
von außen gar nicht sichtbar, und weil sie dann auf `localhost` läuft,
funktioniert auch die **Kamera** des Belegscanners (die verlangt HTTPS oder
localhost):

```bash
ssh -L 3002:127.0.0.1:3002 rentaltool     # dann http://127.0.0.1:3002 öffnen
```

Gefüllt wird sie mit einer **Kopie der echten Daten** – nur so fällt auf, was
mit zwei Buchungen am selben Tag oder 300 Zeiteinträgen passiert:

```bash
ssh rentaltool 'cd /opt/rentaltool-staging && python3 tools/staging_refresh.py --jetzt'
systemctl restart rentaltool-staging
```

Genau das macht sie gefährlich: echte Gäste, echte Mitarbeiter, echte
E-Mail-Adressen. Deshalb **zwei Ebenen**:

* `staging_refresh.py` nimmt beim Kopieren alle Wege nach draußen aus der
  Konfiguration: Mail-App-Passwörter, Spiegel-Ordner, WebDAV und – besonders
  wichtig – das **Sicherungsziel** (sonst überschriebe eine Sicherung der Probe
  die echten Sicherungen am selben Ort).
* `app/mode.py` sperrt dieselben Wege **im Code** (`RENTALTOOL_STAGING=1` in der
  Unit): kein Mailversand, keine Gast-Nachrichten an Smoobu, kein
  Nextcloud-Spiegel. Wer die Konfiguration von Hand wieder füllt, kommt trotzdem
  nicht raus.

In der Oberfläche steht oben ein oranges **PROBE-INSTANZ**-Kennzeichen – die
Probe sieht sonst exakt aus wie der Echtbetrieb.

> Die Probe hängt bewusst nicht unter einer eigenen Adresse: dafür bräuchte es
> einen DNS-Eintrag und ein Zertifikat. Wenn das später nötig wird (z. B. um die
> App als PWA auf dem Handy zu testen), reicht ein A-Record auf den Server.

### Wächter

`tools/watchdog.py` läuft alle 10 Minuten (`rentaltool-watchdog.timer`) und prüft:

| Prüfung | Warum |
|---|---|
| Oberfläche | Antwortet `/login` **mit Anmeldeformular**? Ein Prozess, der beim Rendern abstürzt, sieht von außen gesund aus |
| Smoobu | Ohne API sind Buchungslisten leer – das sieht aus wie „nichts zu tun", ist aber ein Ausfall |
| Daten | Lassen sich Konten, Zeiten und Zuweisungen lesen? |
| Sicherung | Nicht älter als 36 h – eine Sicherung, die still aufgehört hat, ist der gefährlichste Ausfall |

Gemeldet wird **nur bei Wechseln**: einmal, wenn etwas kippt; danach höchstens
alle 6 Stunden erneut; und einmal, wenn es sich wieder fängt. Sonst gewöhnt man
sich an die Mails und liest sie irgendwann nicht mehr. Stand in
`watchdog-status.json` im Datenordner, Handlauf mit `--zeigen` (meldet nie).

## Konfiguration

`config.json` enthält API-Key, Steuersatz, Betreiber- und Empfängerdaten
(für das Formular). Anpassen statt im Code ändern.

## Webhook

`POST /api/smoobu/webhook` leert den Buchungs-Cache (TTL 5 min), damit
Änderungen aus Smoobu sofort einfließen. In Smoobu als Webhook-Ziel
`http://<host>:3001/api/smoobu/webhook` eintragen.

## Tests

```bash
python3 -m pytest        # Steuer-Golden-Tests (Dez 2025, Mai 2026) + UI-Test
```

`tests/test_steuer.py` prüft die Berechnung gegen zwei Monate, `tests/test_web.py`
testet die NiceGUI-Oberfläche headless (Seite lädt, „Berechnen" rendert Ergebnis).
