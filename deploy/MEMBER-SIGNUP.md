# Mitgliederprüfung bei internen Anlässen

Backend-Commit: `d6699d9`. WordPress-Commit: `6ae1c67` im separaten Public-Repository.

## Verhalten

- `is_internal` und der historische Status `INTERN` aktivieren dieselbe Prüfung.
- Exakter Vulgo nach Vereinheitlichung von Gross-/Kleinschreibung und Leerzeichen; mehrdeutige Treffer werden abgewiesen.
- Zulässig: FUX, BURSCH, studentische Chargen und ALTFROBURGER. Eine ausschliessliche ADMIN-, WEB_X-, EHRENPHILISTER- oder AF-Amtsrolle reicht nicht aus.
- Deaktivierte Benutzer, Verstorbene und Profile mit Austrittsangaben werden abgewiesen.
- Öffentliche Ablehnung: `Sorry, nur für Froburger.` HTTP 403 und ein gemeinsamer API-Code für unbekannte, unberechtigte, doppelte und gesperrte Anmeldungen sowie ungültige Eingaben.
- Erstellung, PIN-Abfrage und Änderung erfolgen über die bestehende HMAC-signierte API. WordPress erzeugt den signierten Besucher-Schlüssel selbst aus REMOTE_ADDR. Keine Übernahme von Browserangaben oder X-Forwarded-For.
- Gemeinsames Datenbanklimit: 120 Versuche je Besucher-Schlüssel in zehn Minuten, über alle Anlässe und Operationen hinweg. Fehler zählen mit; Cache-Neustarts setzen das Limit nicht zurück. Ohne Besucher-Schlüssel gilt ein gemeinsames Limit für die Proxy-Adresse. Abgelaufene Schlüssel werden nach einem Tag bei der nächsten Anfrage entfernt, sobald auch ihre Sperrhistorie abgelaufen ist.
- Event-Zeilensperre serialisiert Anmeldungen auch unter MariaDB. Neue interne Anmeldungen werden mit dem Profil verknüpft, sodass eine Vulgo-Änderung keine zweite Anmeldung ermöglicht. Altanmeldungen werden erst nach richtigem PIN verknüpft. Bestehende PINs bleiben erhalten.
- Interne Teilnehmerlisten werden weder in der öffentlichen JSON-Antwort noch im HTML ausgegeben. Öffentliche Detailantworten sind nicht cachebar. Normale Anlässe bleiben offen.
- Der direkte Django-Formularweg nimmt keine internen Anmeldungen an; der sichtbare Link führt zum öffentlichen WordPress-Formular.

Die vereinbarte Prüfung bestätigt die Berechtigung des angegebenen Vulgos, nicht die Identität der Person am Browser. Wer einen berechtigten Vulgo kennt, kann eine neue Anmeldung damit erstellen. Eine erfolgreiche Anmeldung bestätigt zwangsläufig diesen Treffer; die Begrenzung erschwert automatisierte Abfragen, beseitigt diese grundsätzliche Eigenschaft aber nicht.

## Gestaffelte IP-Sperre

Je fuenf abgelehnte interne Anmeldeversuche wird dieselbe IP gesperrt: 30 Sekunden, 1, 2, 5, 10, 30 Minuten, 1, 2, 6, 12 und maximal 24 Stunden. Weitere Stufen bleiben bei 24 Stunden. Die Sperre gilt fuer Erstellung, PIN-Abfrage und Aenderung ueber alle internen Anlaesse hinweg. Browserwechsel, neue Session und Cache-Neustart setzen sie nicht zurueck.

Alle nach aussen gleich behandelten Ablehnungen zaehlen, einschliesslich unbekannter/mehrdeutiger/unberechtigter Vulgos, doppelter Anmeldungen und falscher PINs. Andernfalls wuerde das Sperrverhalten die Mitgliedschaft verraten. Die Antwort bleibt HTTP 403 mit derselben allgemeinen Meldung, ohne Restzeit oder Auskunft zum Mitglied. Die bestehende PIN-Sperre eines einzelnen Eintrags gilt weiterhin unabhaengig davon.

Anfragen waehrend einer Sperre zaehlen nicht erneut und verlaengern sie nicht. Erfolgreiche Anfragen loeschen die Historie nicht. Nach 24 Stunden ohne weitere gezaehlte Fehlversuche wird sie zurueckgesetzt; bei einer verhaengten Sperre beginnt diese Frist an deren Ende. Die 120-Versuche-Grenze ist ein zusaetzlicher allgemeiner Schutz und ueberlagert die kurzen ersten Sperrstufen bei normaler Nutzung nicht.

Die Sperre betrifft eine gemeinsame oeffentliche IP (z.B. mehrere Personen im selben WLAN). Ein Wechsel der oeffentlichen IP kann diese IP-basierte Begrenzung umgehen. Es werden weiterhin nur gehashte IP-Schluessel gespeichert. Die Datenbank-Zeilensperre serialisiert Pruefung und Fehlversuch auch zwischen verschiedenen Anlaessen/Workern.

Die Erweiterung benoetigt nur ein erneutes Backend-Deployment. Das WordPress-Paket der Mitgliederanmeldung muss einmal installiert sein, damit die individuelle Besucher-IP statt des gemeinsamen Proxy-Fallbacks verwendet wird.

## Deployment

1. `powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\Deploy-MemberSignup.ps1 -Deploy` aus `app/intern`.
2. Erst nach Erfolg: `powershell -NoProfile -ExecutionPolicy Bypass -File .\docs\member-signup\Deploy-MemberSignup.ps1 -Deploy` aus `app/public`.

Ohne `-Deploy` werden ausschliesslich lokale Pakete gebaut. Skripte verwenden feste Commits, prüfen Hashes und stoppen bei abweichenden Serverdateien. Das Backend verlangt die bereits installierte Migration 0011. Migration 0012 fügt nur die Profilzuordnung und die Tabelle für Anmeldeversuche hinzu; Migration 0013 ergänzt Fehlversuche und Sperrstufen. Das Paket unterstützt sowohl den Stand vor Migration 0012 als auch die bereits installierte Mitgliederprüfung. Andere ausstehende Migrationen werden nicht ausgeführt. Es gibt vorab ein Code- und Datenbankbackup. Eine fehlgeschlagene Migration lässt den Dienst zur Prüfung gestoppt; kein automatischer Datenbank-Restore.

WordPress prüft vorab die Backend-Policy am internen Beispielanlass `schluss-acbc`, sichert die betroffenen Dateien, löscht die Plugin- und Elementor-Caches und prüft anschliessend die öffentliche Seite auf Formular, fehlende Teilnehmerliste und `no-store`. Bei einer Backend-Störung werden keine alten Teilnehmerdaten als Ersatz ausgegeben. In der lokalen Installation ist kein separates Seiten-Cache-Plugin vorhanden; falls später ein CDN oder Seiten-Cache ergänzt wird, müssen die Anlassdetailseiten dort ebenfalls ausgeschlossen werden.

Die Skripte wurden lokal auf Syntax und Paketinhalt geprüft. Ein Produktionslauf und ein MariaDB-Integrationstest wurden nicht durchgeführt. Lokal bestanden 105 Django-Tests sowie die PHP-Integrationstests und Syntaxprüfungen.
