# Kalender-Deployment

## Django

1. Datenbank sichern.
2. Code nach `/srv/avf-intern/app` uebertragen.
3. Python-Abhaengigkeiten installieren:
   `pip install -r requirements.txt`
4. Migrationen ausfuehren:
   `python manage.py migrate`
5. Systemcheck:
   `python manage.py check`
6. Dienst neu starten.
7. Oeffentlichen Feed pruefen:
   `/calendar/public/events.ics`
8. Bestehende Kompatibilitaetsroute pruefen:
   `/api/v1/public/events/calendar.ics`
9. Einzeltermin pruefen:
   `/calendar/public/events/<slug>.ics`
10. Privaten Testfeed mit frisch erzeugtem Link pruefen.
11. Application-Logs ohne Tokenleak pruefen.

## WordPress

1. Plugin-Dateien in `wp-content/plugins/avf-events-integration/` sichern.
2. Neue Plugin-Dateien uebertragen.
3. In den Plugin-Einstellungen die kanonische Feed-URL setzen:
   `https://intern.avfroburger.ch/calendar/public/events.ics`
4. WordPress-Cache leeren.
5. Anlassuebersicht pruefen:
   Abo-Dialog, Kopierfunktion, `webcal://`-Link.
6. Anlassdetail pruefen:
   Einzeltermin-ICS-Link.

## Rollback

1. Vorherige Django-Dateien und Plugin-Dateien zurueckspielen.
2. Falls noetig Datenbankbackup rueckspielen.
3. Django-Dienst neu starten.
4. WordPress-Cache leeren.
