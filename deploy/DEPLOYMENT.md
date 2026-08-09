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
- `PUBLIC_EVENT_SIGNUP_SHARED_SECRET` - shared secret for the WordPress -> Django
  event-signup API (see SEC-005 in the security audit). Must be the same long
  random value configured on the WordPress side
  (`AVF_EVENTS_SIGNUP_SHARED_SECRET`). Leaving it unset does **not** open the
  endpoint - the view now fails closed and returns HTTP 503 for every signup
  attempt until a real secret is set on both sides.

DNS and TLS for `intern.avfroburger.ch` are live in production. The current
required values are:

- `DJANGO_SECURE_SSL_REDIRECT=True`
- `DJANGO_SESSION_COOKIE_SECURE=True`
- `DJANGO_CSRF_COOKIE_SECURE=True`
- `DJANGO_SECURE_HSTS_SECONDS=15552000` (180 days; ramp towards `63072000` once
  stable, see "Naechster Schritt nach DNS" below)
- `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=True`

Optional, only during the brief bring-up window for a *brand-new* host before
DNS/Certbot are done (never on the existing production host):

- `DJANGO_CSRF_TRUSTED_ORIGINS=https://intern.avfroburger.ch,https://intern-avfroburger.ch,http://intern.avfroburger.ch`
- the five settings above temporarily set to `False`/`0` per `deploy/env.example`'s comments

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

**Status: abgeschlossen.** Live-Checks im Rahmen des Security-Audits (2026-08-09)
bestaetigen HTTPS, HSTS und Secure-Cookies auf `intern-avfroburger.ch`. Fuer
einen komplett neuen Host waeren die Schritte:

1. `PUBLIC_EVENT_SOURCE_BASE_URL` und `PUBLIC_MEDIA_BASE_URL` auf `https://intern.avfroburger.ch` umstellen.
2. `DJANGO_CSRF_TRUSTED_ORIGINS` auf `https://intern.avfroburger.ch` belassen oder bereinigen.
3. Certbot fuer `intern.avfroburger.ch` ausfuehren.
4. Nginx auf HTTPS erweitern.
5. Danach `DJANGO_SECURE_SSL_REDIRECT=True`, `DJANGO_SESSION_COOKIE_SECURE=True`, `DJANGO_CSRF_COOKIE_SECURE=True` und HSTS sinnvoll aktivieren (siehe Werte oben).

**Offen, bitte auf dem Server pruefen und ggf. nachziehen:** ob die reale
`/etc/avf-intern/avf-intern.env` bereits `PUBLIC_EVENT_SIGNUP_SHARED_SECRET`
gesetzt hat. Ein Live-Check ohne echte Anmeldung zu erzeugen (nicht
existierender Event-Slug, keine Auth-Header) ergab am 2026-08-09 `event_not_found`
statt einer Auth-Ablehnung - das Secret war zu diesem Zeitpunkt **NOT SET**,
d.h. die Anmelde-API lief offen. Nach diesem Fix (Code faellt jetzt closed)
muss ein echtes Secret auf Server *und* WordPress-Seite gesetzt werden, sonst
bleiben Anmeldungen mit HTTP 503 blockiert.
