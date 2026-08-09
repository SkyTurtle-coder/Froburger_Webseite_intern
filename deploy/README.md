# Deployment Notes

Die kanonischen produktiven Dateien liegen jetzt unter:

- `deploy/env.example`
- `deploy/avf-intern.service`
- `deploy/nginx-avf-intern.conf`
- `deploy/deploy.ps1`
- `deploy/DEPLOYMENT.md`

Wichtige Abweichungen gegenueber aelteren Beispielen:

- Zielsystem ist MariaDB auf `127.0.0.1:3306`, nicht PostgreSQL.
- Der Dienst laeuft als `avfapp:avfapp`, nicht als Webserver-Benutzer.
- Vor DNS- und Zertifikatsfreigabe wird keine HTTPS-Weiterleitung erzwungen.
- Nur `/media/public/` wird direkt ueber Nginx ausgeliefert.
- Geschuetzte Dokumente bleiben hinter Django-Berechtigungen.

Die WordPress-Helferskripte in diesem Verzeichnis bleiben unveraendert nutzbar, sobald die produktive Django-URL feststeht.
