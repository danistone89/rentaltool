# Den Dienst entwurzeln – von `root` auf einen eigenen Benutzer

**Stand:** 7.8.2026 · vorbereitet, noch nicht ausgeführt.

Die App läuft auf dem Server als `root`. Sie nimmt Dateien entgegen, baut PDFs
und verarbeitet fremde HTTP-Antworten – für nichts davon braucht sie
Systemrechte. Mit `root` wird aus jedem Fehler in dieser Kette sofort ein
Fehler im ganzen System.

Die fertige Unit liegt in `deploy/rentaltool.service`. Diese Anleitung ist der
Weg dorthin, mit **kurzer Ausfallzeit** (unter einer Minute) und einem Rückweg.

## Vorher wissen

* Zugang: `ssh rentaltool` (Alias, Schlüssel `~/.ssh/hetzner_rentaltool`).
* Code liegt in `/opt/rentaltool`, **Betriebsdaten getrennt** in
  `/var/lib/rentaltool` (`RENTALTOOL_DATA`).
* Die App lauscht auf `127.0.0.1`; nach außen steht nginx. Ports unter 1024
  fasst sie nicht an – der Benutzerwechsel ändert daran nichts.
* Die Nextcloud hängt als rclone-Mount unter `/mnt/nextcloud`. **Das ist der
  wahrscheinlichste Stolperstein:** ein FUSE-Mount gehört dem Benutzer, der ihn
  gesetzt hat, und ist für andere per Voreinstellung unlesbar (Schritt 5).

## Die Schritte

```bash
ssh rentaltool

# 1) Sicherung ziehen und prüfen – vor allem anderen.
cd /opt/rentaltool && .venv/bin/python tools/backup.py sichern
.venv/bin/python tools/backup.py pruefen

# 2) Systembenutzer ohne Anmeldung und ohne Heimatverzeichnis.
useradd --system --no-create-home --shell /usr/sbin/nologin rentaltool

# 3) Daten übereignen. Der Code bleibt root: ein Deploy ist ein bewusster
#    Schritt von außen, kein Nebeneffekt der laufenden Anwendung.
chown -R rentaltool:rentaltool /var/lib/rentaltool
chmod 750 /var/lib/rentaltool
#    Lesen genügt am Code – aber .venv muss ausführbar bleiben.
chown -R root:rentaltool /opt/rentaltool
chmod -R g+rX /opt/rentaltool

# 4) Unit tauschen.
systemctl stop rentaltool
cp /opt/rentaltool/deploy/rentaltool.service /etc/systemd/system/rentaltool.service
systemctl daemon-reload
systemctl start rentaltool
systemctl status rentaltool --no-pager

# 5) Nextcloud-Mount: gehört dem Benutzer, der ihn gesetzt hat.
#    Ohne `allow-other` sieht `rentaltool` dort NICHTS, und die nächtliche
#    Sicherung scheitert still. Prüfen:
sudo -u rentaltool ls /mnt/nextcloud >/dev/null && echo "Mount lesbar" \
  || echo "Mount NICHT lesbar – rclone mit --allow-other neu setzen"
```

## Danach prüfen – in dieser Reihenfolge

1. `systemctl status rentaltool` läuft, kein `Permission denied` im Journal.
2. https://app.ds-apartments.de öffnet, **Anmeldung geht** (die Sitzungen
   liegen im Datenordner – wenn der nicht schreibbar ist, merkt man es hier).
3. Einen Beleg hochladen: schreibt nach `/var/lib/rentaltool/media`.
4. `systemctl start rentaltool-backup` von Hand auslösen und
   `journalctl -u rentaltool-backup -n 30` ansehen – das ist der Schritt, der
   am ehesten an den Rechten hängt (Nextcloud-Mount, siehe oben).
5. Am nächsten Morgen: kam die Sicherung durch?

## Rückweg

Geht etwas schief, ist der Weg zurück eine Zeile plus Neustart:

```bash
systemctl stop rentaltool
sed -i 's/^User=rentaltool/User=root/; s/^Group=rentaltool/Group=root/' \
    /etc/systemd/system/rentaltool.service
systemctl daemon-reload && systemctl start rentaltool
```

Die Dateirechte stören `root` nicht – der darf ohnehin alles. Ein Rückbau von
`chown` ist also nicht nötig.

## Die anderen Units

`rentaltool-backup`, `-erinnerung` und `-watchdog` laufen weiter als `root`.
Das ist **Absicht**: Die Sicherung muss den ganzen Datenbestand lesen und an
die Nextcloud schreiben, der Watchdog muss den Dienst neu starten dürfen. Sie
laufen kurz, zeitgesteuert und ohne offenen Port – das Risiko ist ein anderes
als bei einem Dienst, der dauerhaft am Netz hängt.

`rentaltool-staging` (`User=root`) bleibt ebenfalls vorerst. Wenn die
Umstellung im Echtbetrieb steht, ist sie dort in denselben Schritten
nachzuziehen – mit `rentaltool-staging` statt `rentaltool`.
