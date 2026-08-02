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

| Datei | Aufgabe |
|---|---|
| `app/web.py` | NiceGUI-Oberfläche (Seite, Einstellungs-Dialog, Webhook), Entry-Point |
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
| `tools/make_blank.py` | Blanko-Vorlage + Unterschrift aus eingereichter PDF |
| `tools/useradmin.py` | Benutzer per Kommandozeile (Notfall/Server, ohne Oberfläche) |
| `tools/check_shadowing.py` | Findet überschattete Modulnamen (läuft als Test mit) |

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

**Mehrbenutzer & Rollen:** Über **„Benutzer"** (nur Admin) lassen sich weitere
Konten einladen, Zugänge zurücksetzen, Rollen ändern oder löschen. Rollen:
`admin` (sieht alles, verwaltet Nutzer/Einstellungen) und `putzkraft`. **Welche
Bereiche eine Rolle sieht, steuert `ROLE_AREAS` in `app/web.py`** (aktuell:
Admin = alles, Putzkraft = noch nichts – wird später definiert). Nutzer ohne
freigeschaltete Bereiche sehen eine Willkommens-/Hinweisseite.

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
