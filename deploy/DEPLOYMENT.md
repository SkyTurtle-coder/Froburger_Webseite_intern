# AV Froburger Intern Deployment

## Architektur

- Django-Projekt unter `/srv/avf-intern/app`
- `manage.py` unter `/srv/avf-intern/app/manage.py`
- Settings-Modul: `config.settings`
- Startkommando: `/srv/avf-intern/venv/bin/uvicorn config.asgi:application --host 127.0.0.1 --port 8010`
- Datenbank lokal in Entwicklung: SQLite (`db.sqlite3`)
- Produktive Datenbank: MariaDB auf `127.0.0.1:3306`

## Dateien in diesem Verzeichnis

- `env.example`
- `avf-intern.service`
- `nginx-avf-intern.conf`
- `deploy.ps1`

## Produktive Umgebungsvariablen

Pflichtig:

- `DJANGO_SETTINGS_MODULE=config.settings`
- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG=False`
- `DJANGO_ALLOWED_HOSTS=intern.avfroburger.ch,intern-avfroburger.ch,179.237.81.250,127.0.0.1,localhost`
- `DJANGO_CSRF_TRUSTED_ORIGINS=https://intern.avfroburger.ch,https://intern-avfroburger.ch`
- `DB_NAME=avf_intern`
- `DB_USER=avf_django`
- `DB_PASSWORD`
- `DB_HOST=127.0.0.1`
- `DB_PORT=3306`
- `STATIC_ROOT=/srv/avf-intern/static`
- `MEDIA_ROOT=/srv/avf-intern/media`

Optional fuer HTTP-Tests ueber die spaetere Domain, solange noch kein Zertifikat aktiv ist:

- `DJANGO_CSRF_TRUSTED_ORIGINS=https://intern.avfroburger.ch,https://intern-avfroburger.ch,http://intern.avfroburger.ch`

Bis DNS und HTTPS final bereit sind, keine HSTS- oder Redirect-Zwaenge aktivieren.

## Zugriffspolitik fuer Medien

- `/static/` darf direkt durch Nginx ausgeliefert werden.
- `/media/public/` darf direkt durch Nginx ausgeliefert werden.
- `/media/protected/` und andere nicht-oeffentliche Medien duerfen nicht direkt durch Nginx ausgeliefert werden.
- Geschuetzte Dokumente bleiben bei Django-Downloads unter `/dokumente/...`.

## Uebertragung

`deploy.ps1` uebertraegt nur den Django-Teil unter `intern/` und schliesst unter anderem aus:

- `.git`
- `.env` und `.env.*`
- `venv`, `.venv`
- `__pycache__`, `*.pyc`
- `db.sqlite3`, `*.sqlite3`
- `media/`
- lokale Logs und temporaere Artefakte

Vor der Uebertragung wird auf dem Server ein datierter Backup-Ordner unter `/srv/avf-intern/backups/` angelegt.

## Server-Schritte

1. Produktive Env-Datei manuell als `/etc/avf-intern/avf-intern.env` pflegen.
2. Quellcode mit `deploy.ps1` oder einem gleichwertigen Befehl uebertragen.
3. Auf dem Server im Verzeichnis `/srv/avf-intern/app` arbeiten.
4. Abhaengigkeiten ausschliesslich in `/srv/avf-intern/venv` installieren.
5. Service-Datei nach `/etc/systemd/system/avf-intern.service` kopieren.
6. Nginx-Datei nach `/etc/nginx/sites-available/avf-intern.conf` kopieren.
7. Erst nach erfolgreichem Test die Site aktivieren und die Default-Site deaktivieren.

## Validierung

```bash
sudo -u avfapp /srv/avf-intern/venv/bin/python /srv/avf-intern/app/manage.py check
sudo -u avfapp /srv/avf-intern/venv/bin/python /srv/avf-intern/app/manage.py check --deploy
sudo -u avfapp /srv/avf-intern/venv/bin/python /srv/avf-intern/app/manage.py migrate --plan
sudo -u avfapp /srv/avf-intern/venv/bin/python /srv/avf-intern/app/manage.py migrate
sudo -u avfapp /srv/avf-intern/venv/bin/python /srv/avf-intern/app/manage.py collectstatic --noinput
curl -I http://127.0.0.1:8010/healthz/
curl -I http://179.237.81.250/healthz/
sudo nginx -t
sudo systemctl status avf-intern
sudo ss -ltnp
```

## Rollback

1. `sudo systemctl stop avf-intern`
2. Letzten Backup-Ordner aus `/srv/avf-intern/backups/` nach `/srv/avf-intern/app` zurueckkopieren.
3. `sudo chown -R avfapp:avfapp /srv/avf-intern/app`
4. `sudo systemctl start avf-intern`
5. Falls erforderlich `sudo systemctl reload nginx`

## Naechster Schritt nach DNS

Sobald `intern.avfroburger.ch` nachweislich auf `179.237.81.250` zeigt:

1. `PUBLIC_EVENT_SOURCE_BASE_URL` und `PUBLIC_MEDIA_BASE_URL` auf `https://intern.avfroburger.ch` umstellen.
2. `DJANGO_CSRF_TRUSTED_ORIGINS` auf `https://intern.avfroburger.ch` belassen oder bereinigen.
3. Certbot fuer `intern.avfroburger.ch` ausfuehren.
4. Nginx auf HTTPS erweitern.
5. Danach `DJANGO_SECURE_SSL_REDIRECT=True`, `DJANGO_SESSION_COOKIE_SECURE=True`, `DJANGO_CSRF_COOKIE_SECURE=True` und HSTS sinnvoll aktivieren.
