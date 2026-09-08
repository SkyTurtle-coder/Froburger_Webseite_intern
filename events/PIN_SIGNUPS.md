# PIN-geschützte Anmeldungen

Neue öffentliche Anmeldungen verlangen einen PIN aus 4–6 ASCII-Ziffern. Der PIN
bleibt ein String (führende Nullen), wird mit Django-Passwort-Hashing gespeichert
und weder in öffentlichen Antworten noch im Änderungsprotokoll ausgegeben.

Der bestehende signierte POST-Endpunkt `/api/v1/public/events/<slug>/signup/`
akzeptiert zusätzlich `operation`: `create` (Standard), `read` oder `update`.
Alle Operationen prüfen Öffentlichkeit, Aktivierung und Anmeldeschluss.
`read` benötigt `vulgo` und `pin`; `update` zusätzlich `attending` und `values`.
Die Bearbeitung identifiziert den Eintrag anhand von Anlass, normalisiertem Vulgo
und PIN. Das Vulgo bleibt öffentlich unveränderlich; der Admin kann es ändern.
PINs und persönliche Antworten werden nur per POST transportiert; Antworten
tragen `Cache-Control: no-store`. Die Signatur enthält die gesamte Nutzlast,
einschliesslich Operation und PIN. Bestehende Replay-Prüfung bleibt aktiv.

Nach fünf falschen gültig formatierten PIN-Eingaben wird der Eintrag 15 Minuten
gesperrt. Zähler und Sperre liegen in der Datenbank und überleben Cache-Neustarts.
Eine erfolgreiche Prüfung oder ein Admin-Reset setzt sie zurück.

Im internen Anlasseditor setzt das optionale Feld „Neuen PIN setzen“ einen ersten
oder neuen PIN. Leer bedeutet unverändert. Bearbeiten und Löschen verlangen dort
weiterhin nur die bestehenden Rollen ADMIN/WEB_X, keinen PIN und keine offene
Anmeldefrist. PIN-Resets werden ohne PIN/Hash im Audit als `pin_reset` protokolliert.
Es gibt keine automatische Wiederherstellung und keine E-Mail-Zustellung.

## Einführung

Backend und WordPress-Plugin `avf-events-integration` müssen gemeinsam eingeführt
werden: Der alte Client sendet keinen PIN, das alte Backend kennt ihn nicht.
In einem kurzen Wartungsfenster Datenbank sichern, Backend-Dateien ausliefern,
`python manage.py migrate events` ausführen, Django neu starten und das passende
WordPress-Plugin ausliefern. Anschliessend öffentliche Seiten-/Plugin-Caches
leeren, damit die neuen Formulare und Skripte erscheinen.

Migration 0009 ergänzt ausschliesslich Felder mit leeren/default Werten. Bestehende
Anmeldungen werden nicht umgeschrieben und erhalten keinen Standard-PIN. Diese
bleiben zunächst über den Admin bearbeitbar. Der Admin darf einen PIN erst nach
Zuordnung zur anfragenden Person setzen und dieser direkt mitteilen.

Bei einem Rollback beide Code-Stände gemeinsam zurücksetzen. Die zusätzlichen
Datenbankfelder können zunächst bestehen bleiben; eine Rückwärtsmigration würde
die bereits vergebenen PIN-Hashes und Sperrzustände verlieren.

## Prüfung

`python manage.py test events --noinput` prüft unter anderem PIN-Längen, Hashing,
führende Nullen, Sperre, Legacy-Einträge, private Daten, Feldvalidierung,
Anmeldeschluss, Admin-Reset und Berechtigungen. Zusätzlich:
`python manage.py check` und `python manage.py makemigrations events --check --dry-run`.

WordPress-PHP-/Browserprüfungen stehen im Plugin unter `tests/signup-pin-check.php`
und `tests/signup-pin-browser.py`. Die Browserprüfung nutzt echte Formular- und
Asset-Dateien mit simulierten API-Antworten. Vor dem Live-Einsatz ist ein gemeinsamer
WordPress-/Django-Test auf einer nachweislich isolierten Umgebung inklusive neuer
Anmeldung, Bearbeitung und internem Reset erforderlich. `test.avfroburger.ch` teilt
laut Deployment-Runbook die Produktionsdatenbank und darf dafür nicht verwendet
werden. Die lokale WordPress-Domain war bei der Umsetzung
nicht erreichbar; es wurden keine Live-Anmeldungen geändert.
