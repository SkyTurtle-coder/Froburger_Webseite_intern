# AV Froburger Intern

Eigenstaendiges Django-Projekt fuer den internen Bereich der Website. Die oeffentliche Website bleibt in `app/public` auf WordPress. Django in `app/intern` verwaltet Login, Rollen, Profile, Anlaesse, Dokumente und die oeffentliche Event-API, die das WordPress-Plugin erwartet.

## Architektur

- `config`
  - Django-Projekt, Settings, URL-Konfiguration
- `core`
  - Dashboard, gemeinsame Berechtigungen, Healthcheck, Integrations-Commands
- `accounts`
  - Profile und Rollen
- `events`
  - Anlassverwaltung, oeffentliche API, ICS-Feed, oeffentliche Detailseiten
- `documents`
  - allgemeine und sensible Dokumente mit geschuetztem Download

## Wichtige URL-Vertraege

WordPress in `app/public/wp-content/plugins/avf-events-integration` erwartet exakt diese Endpunkte:

- Legacy
  - `/api/public/events/upcoming/`
- v1
  - `/api/v1/public/events/upcoming/`
  - `/api/v1/public/events/past/`
  - `/api/v1/public/events/<slug>/`
  - `/api/v1/public/events/calendar.ics`

Pflichtfelder pro Event:

- `id`
- `title`
- `slug`
- `short_description`
- `start_at`
- `end_at`
- `timezone_name`
- `location_name`

Optionale Felder:

- `detail_path`
- `source_url`

Die Mitgliederintegration verwendet zusaetzlich:

- `/api/v1/public/members/`

Antwortschema:

- `schema_version`
- `generated_at`
- `content_hash`
- `member_count`
- `section_order`
- `sections`

Jede Sektion enthaelt:

- `title`
- `count`
- `members`

Jedes Mitglied enthaelt mindestens:

- `id`
- `display_name`
- `vulgo`
- `roles[]`
- `photo.fallback`
- `photo.variants.small|medium|large`

## Event-Regeln fuer WordPress

- Nur Events mit `is_public=True` werden oeffentlich ausgeliefert.
- Oeffentliche Events brauchen zwingend:
  - `short_description`
  - `location`
- Solange `PUBLIC_EVENT_SOURCE_BASE_URL` leer bleibt, kann WordPress weiter auf seinen bestehenden Fallback unter `/anlaesse/` verlinken.
- Wenn Django kanonische Detailseiten ausliefern soll:
  - `PUBLIC_EVENT_SOURCE_BASE_URL=https://intern.example.ch`
  - `PUBLIC_EVENT_DETAIL_PATH_PREFIX=/anlaesse`

## Mitglieder-Regeln fuer WordPress

- Django bleibt Source of Truth fuer Mitglieder, Rollen und Profilbilder.
- Die oeffentliche Bild-Domain wird ausschliesslich ueber `PUBLIC_MEDIA_BASE_URL` bestimmt, nie ueber den eingehenden Request-Host.
- Die Members-API liefert nur optimierte quadratische Bildderivate (`small`, `medium`, `large`) fuer oeffentliche Karten.
- WordPress rendert nur den zuletzt gueltigen lokalen Snapshot und fuehrt im Frontend keinen HTTP-Request an Django aus.
- Snapshot-Aktualisierungen laufen ueber WP-Cron, den CLI-Sync oder eine manuelle Admin-Aktion.

## Lokale Inbetriebnahme

```powershell
cd "C:\Users\phili\Local Sites\av-froburger\app\intern"
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py bootstrap_internal --username admin --email "admin@example.org"
# prompts for the admin password (no echo) - or set AVF_BOOTSTRAP_ADMIN_PASSWORD
# beforehand for a non-interactive/scripted run (SEC-014: never as a CLI flag)
python manage.py runserver 127.0.0.1:8000
```

Danach ist Django unter `http://127.0.0.1:8000/` erreichbar.

Fuer lokale WordPress-Integration zusaetzlich in `.env` setzen:

```text
PUBLIC_MEDIA_BASE_URL=http://127.0.0.1:8000/media/
PUBLIC_EVENT_SOURCE_BASE_URL=http://127.0.0.1:8000
```

## Bereits lokal verifiziert

Stand vom 24. Juli 2026:

- `python manage.py migrate`
- `python manage.py bootstrap_internal ...`
- `python manage.py test`
- `python manage.py verify_wordpress_event_contract --base-url=http://127.0.0.1:8000 --slug=froburger-kommender-anlass`
- WordPress in `/public` wurde lokal auf die Django-API konfiguriert und erfolgreich gegen die Plugin-Shortcodes und den API-Client geprueft.

## Nuetzliche Commands

Empfohlene WordPress-Werte ausgeben:

```powershell
python manage.py print_wordpress_event_config
```

Oeffentlichen API-Vertrag gegen eine laufende Django-Instanz pruefen:

```powershell
python manage.py verify_wordpress_event_contract --base-url=http://127.0.0.1:8000 --slug=froburger-kommender-anlass
```

## WordPress in `/public` konfigurieren

Lokale Beispielwerte:

- `API-Endpunkt`
  - `http://127.0.0.1:8000/api/public/events/upcoming/`
- `API-Basis (v1)`
  - `http://127.0.0.1:8000/api/v1/public/`
- `Zielseite fuer Anlassdetails`
  - `/anlaesse/`

Automatisiert per CLI:

```powershell
php deploy/configure_wordpress_events.php --wp-path=..\public --api-endpoint=http://127.0.0.1:8000/api/public/events/upcoming/ --api-base=http://127.0.0.1:8000/api/v1/public/
```

Mitgliederseite mit Snapshot und Elementor-Layout synchronisieren:

```powershell
python manage.py sync_public_members_page --site-url=http://127.0.0.1:8000
```

Die Synchronisation:

- setzt `avf_members_api_base`
- behaelt einen alten Snapshot bis zu einem erfolgreichen Refresh
- erzeugt beziehungsweise aktualisiert den WordPress-Snapshot ausserhalb des Frontend-Renderpfads
- speichert das Elementor-Layout fuer die Mitgliederseite konsistent neu

WordPress-Seite gegen die echte Plugin-Konfiguration pruefen:

```powershell
php deploy/check_wordpress_events.php --wp-path=..\public --expected-api-endpoint=http://127.0.0.1:8000/api/public/events/upcoming/ --expected-api-base=http://127.0.0.1:8000/api/v1/public/ --expected-page-path=/anlaesse/ --detail-slug=froburger-kommender-anlass
```

## Tests

```powershell
python manage.py test
```

Abgedeckt sind unter anderem:

- Rollen- und Adminzugriffe
- Anlassverwaltung
- geschuetzte Dokumente
- oeffentliche Event-API fuer WordPress
- oeffentliche Detailseiten
- ICS-Feed
- versionierte Members-API
- host-unabhaengige oeffentliche Media-URLs
- Bildderivate fuer Mitgliederkarten
- Deduplizierung bei mehrfachen Komitee-Rollen
- WordPress-Vertragspruefung auf Command-Ebene

## Deployment-Hinweise

- `app/public` und `app/intern` als getrennte Deployments behandeln
- WordPress oeffentlich unter Hauptdomain
- Django intern unter eigener Subdomain wie `intern.avfroburger.ch`
- Django hinter Uvicorn und Nginx
- `collectstatic` vor dem Start ausfuehren
- sensible Dokumente nicht direkt ueber den Webserver freigeben

Weitere produktionsnahe Beispiele liegen unter `deploy/`.
