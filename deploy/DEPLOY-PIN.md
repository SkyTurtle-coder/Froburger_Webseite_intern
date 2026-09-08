# PIN-Funktion: geprüften Git-Stand auf beide Server übertragen

Diese Befehle sind vorbereitet, aber nicht auf den Servern ausgeführt. SSH wurde
bei der Prüfung mit `Permission denied` abgewiesen. Serverpfade stammen aus den
Projekt-Runbooks. Lokale, nicht committete Änderungen werden nicht übertragen.
Kein Git-Pull auf dem Server erforderlich; das Deployment erfolgt mit Git-Archiven.

## Bereits hochgeladene Pakete fortsetzen

Für das bereits geprüfte Release `avf-pin-20260909-003225` in einer lokalen
PowerShell ausführen (nicht innerhalb einer SSH-Sitzung):

```powershell
Set-Location 'C:\Users\phili\Local Sites\av-froburger\app'
powershell -NoProfile -ExecutionPolicy Bypass -File .\intern\deploy\Continue-PinDeployment.ps1 -Release avf-pin-20260909-003225 -Deploy
```

Der Helfer überträgt die Bash-Skripte als Dateien und führt die drei Server-Schritte
nacheinander aus. Jeder Schritt setzt seine eigenen Variablen. Dadurch entfallen
Platzhalter und mehrzeiliges Einfügen in SSH-Terminals. Ohne `-Deploy` werden nur
Zugänge, Pakete und Pfade geprüft. Bei Fehlern stoppt der Helfer; dann die konkrete
Fehlermeldung prüfen und gegebenenfalls den Rollback ausführen.

Produktiv: Django `/srv/avf-intern/app`, WordPress
`/home/avfrobur/www/gamma.avfroburger.ch`. **Nicht gegen den Test-Webroot ausführen:**
Test und Produktion teilen laut Runbook die WordPress-Datenbank.

## 1. PowerShell auf deinem PC: Pakete bauen und hochladen

Erst beide Pakete hochladen, dann die Server-Schritte in der angegebenen Reihenfolge
ausführen. Bei einem Fehler stoppen. Für SSH muss dein Schlüssel freigeschaltet sein.

```powershell
Set-Location 'C:\Users\phili\Local Sites\av-froburger\app'
$ErrorActionPreference = 'Stop'
function Run-Native {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe fehlgeschlagen: $LASTEXITCODE" }
}
$release = 'avf-pin-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
$packageDir = Join-Path $env:TEMP $release
New-Item -ItemType Directory -Path $packageDir | Out-Null
$internCommit = (git -C intern rev-parse 'feature/event-signup-pin^{commit}').Trim()
if ($LASTEXITCODE -ne 0) { throw 'Django-Branch fehlt' }
$publicCommit = (git -C public rev-parse 'feature/event-signup-pin^{commit}').Trim()
if ($LASTEXITCODE -ne 0) { throw 'WordPress-Branch fehlt' }
$internFiles = @(
    'events/models.py', 'events/forms.py', 'events/public_views.py', 'events/views.py',
    'events/migrations/0009_eventsignup_pin_failed_attempts_eventsignup_pin_hash_and_more.py',
    'templates/events/event_form.html'
)
$publicFiles = @(
    'wp-content/plugins/avf-events-integration/includes/class-avf-event-signup-handler.php',
    'wp-content/plugins/avf-events-integration/includes/class-avf-event-detail-shortcode.php',
    'wp-content/plugins/avf-events-integration/assets/js/events-lists.js',
    'wp-content/plugins/avf-events-integration/assets/css/events-lists.css'
)
Run-Native git (@('-C', 'intern', 'archive', '--format=tar.gz', "--output=$packageDir/intern.tar.gz", $internCommit, '--') + $internFiles)
Run-Native git (@('-C', 'public', 'archive', '--format=tar.gz', "--output=$packageDir/public.tar.gz", $publicCommit, '--') + $publicFiles)
"Django: $internCommit`nWordPress: $publicCommit" | Set-Content "$packageDir/commits.txt"
Run-Native scp @('-i', 'C:/Users/phili/.ssh/id_ed25519', "$packageDir/intern.tar.gz", "debian@179.237.81.250:/tmp/$release-intern.tar.gz")
Run-Native ssh @('avfroburger-hostpoint', "mkdir -p /home/avfrobur/deploy-tmp/$release")
Run-Native scp @("$packageDir/public.tar.gz", "avfroburger-hostpoint:/home/avfrobur/deploy-tmp/$release/public.tar.gz")
Write-Host "Release für die Server-Blöcke: $release"
Write-Host "Lokale Pakete und Commit-IDs: $packageDir"
```

Den ausgegebenen Release-Namen in den beiden folgenden Shells bei `release=` einsetzen.
Vor dem Überschreiben bei bekannten direkten Serveränderungen zunächst den Diff prüfen.
Die Archive ersetzen nur die sechs bzw. vier aufgelisteten Dateien.

## 2. WordPress-SSH-Shell: Backup und kurzes Wartungsfenster

Lokal öffnen: `ssh avfroburger-hostpoint`. Dann dort:

```bash
(
set -euo pipefail
release=avf-pin-YYYYMMDD-HHMMSS
if [[ ! "$release" =~ ^avf-pin-[0-9]{8}-[0-9]{6}$ ]]; then
  printf 'Bitte den echten Release-Namen einsetzen; YYYYMMDD-HHMMSS ist ein Platzhalter.\n' >&2
  exit 1
fi
wp_root=/home/avfrobur/www/gamma.avfroburger.ch
wp_backup=/home/avfrobur/backups/$release
wp_stage=/home/avfrobur/deploy-tmp/$release
cd "$wp_root"
test "$(wp option get home)" = 'https://www.avfroburger.ch'
test -s "$wp_stage/public.tar.gz"
test ! -e "$wp_backup"
mkdir -p "$wp_backup" "$wp_stage/files"
tar -xzf "$wp_stage/public.tar.gz" -C "$wp_stage/files"
php -l "$wp_stage/files/wp-content/plugins/avf-events-integration/includes/class-avf-event-signup-handler.php"
php -l "$wp_stage/files/wp-content/plugins/avf-events-integration/includes/class-avf-event-detail-shortcode.php"
tar -czf "$wp_backup/public-before.tar.gz" \
  wp-content/plugins/avf-events-integration/includes/class-avf-event-signup-handler.php \
  wp-content/plugins/avf-events-integration/includes/class-avf-event-detail-shortcode.php \
  wp-content/plugins/avf-events-integration/assets/js/events-lists.js \
  wp-content/plugins/avf-events-integration/assets/css/events-lists.css
test -s "$wp_backup/public-before.tar.gz"
wp maintenance-mode activate
)
```

Nach erfolgreichem Abschluss mit Schritt 3 fortfahren. Jeder Block setzt seine Variablen selbst. WordPress-Wartungsmodus
läuft nach etwa zehn Minuten ab; beide Updates unmittelbar nacheinander durchführen.

## 3. Django-SSH-Shell: Datenbankbackup, Dateien, Migration und Neustart

Lokal öffnen: `ssh -i C:/Users/phili/.ssh/id_ed25519 debian@179.237.81.250`.
Dann dort ausführen. `systemd-run` lädt dieselbe EnvironmentFile wie der Dienst;
die Env-Datei wird nicht als Shell-Skript ausgeführt und keine Secrets ausgegeben.

```bash
(
set -euo pipefail
release=avf-pin-YYYYMMDD-HHMMSS
if [[ ! "$release" =~ ^avf-pin-[0-9]{8}-[0-9]{6}$ ]]; then
  printf 'Bitte den echten Release-Namen einsetzen; YYYYMMDD-HHMMSS ist ein Platzhalter.\n' >&2
  exit 1
fi
app=/srv/avf-intern/app
backup=/srv/avf-intern/backups/$release
archive=/tmp/$release-intern.tar.gz
django() {
  sudo systemd-run --quiet --wait --pipe --collect \
    --property=User=avfapp --property=Group=avfapp \
    --property=WorkingDirectory=/srv/avf-intern/app \
    --property=EnvironmentFile=/etc/avf-intern/avf-intern.env \
    /srv/avf-intern/venv/bin/python manage.py "$@"
}
test -s "$archive"
sudo test -f /etc/avf-intern/avf-intern.env
sudo test ! -e "$backup"
sudo systemctl is-active --quiet avf-intern
django shell -c 'from django.conf import settings; d=settings.DATABASES["default"]; assert d["ENGINE"] == "django.db.backends.mysql" and d["NAME"] == "avf_intern", "Unerwartete Datenbank: Backup-Befehl anpassen"'
django showmigrations events
django shell -c 'from django.db.migrations.recorder import MigrationRecorder; assert not MigrationRecorder.Migration.objects.filter(app="events", name__gt="0009_eventsignup_pin_failed_attempts_eventsignup_pin_hash_and_more").exists(), "Spaetere events-Migration vorhanden: Deployment stoppen und Stand abgleichen"'
sudo install -d -m 700 "$backup"
sudo tar -czf "$backup/code-before.tar.gz" -C "$app" \
  events/models.py events/forms.py events/public_views.py events/views.py templates/events/event_form.html
# Auch eine schon vorhandene 0009 sichern (z.B. bei erneutem Deployment).
migration=events/migrations/0009_eventsignup_pin_failed_attempts_eventsignup_pin_hash_and_more.py
if sudo test -f "$app/$migration"; then
  sudo cp -p "$app/$migration" "$backup/migration-before.py"
fi
sudo systemctl stop avf-intern
# Dieser Befehl setzt lokalen MariaDB-Root-Zugriff via sudo/Unix-Socket voraus.
# Bei Fehler nicht fortfahren; Dienst wieder starten und Backup-Zugriff klären.
sudo sh -c 'umask 077; mariadb-dump --single-transaction --routines --triggers avf_intern > "$1"' sh "$backup/database.sql"
sudo test -s "$backup/database.sql"
sudo tar -xzf "$archive" -C "$app"
sudo chown avfapp:avfapp \
  "$app/events/models.py" "$app/events/forms.py" "$app/events/public_views.py" \
  "$app/events/views.py" "$app/$migration" "$app/templates/events/event_form.html"
django check
django migrate events 0009 --plan
django migrate events 0009 --noinput
sudo systemctl start avf-intern
sudo systemctl is-active --quiet avf-intern
curl --retry 5 --retry-connrefused --retry-delay 2 --fail --silent --show-error \
  https://intern.avfroburger.ch/healthz/
)
```

Falls bereits spätere events-Migrationen installiert sind, nicht zu 0009 zurückmigrieren:
Vor diesem Schritt den tatsächlichen Migrationsstand und die Code-Version abgleichen.
Bei Fehler während Schritt 3 bleibt WordPress im Wartungsmodus; siehe Rollback unten.

## 4. In der offenen WordPress-Shell: Dateien aktivieren und prüfen

Erst nach erfolgreichem Django-Neustart:

```bash
(
set -euo pipefail
release=avf-pin-YYYYMMDD-HHMMSS
if [[ ! "$release" =~ ^avf-pin-[0-9]{8}-[0-9]{6}$ ]]; then
  printf 'Bitte den echten Release-Namen einsetzen; YYYYMMDD-HHMMSS ist ein Platzhalter.\n' >&2
  exit 1
fi
wp_root=/home/avfrobur/www/gamma.avfroburger.ch
wp_backup=/home/avfrobur/backups/$release
wp_stage=/home/avfrobur/deploy-tmp/$release
cd "$wp_root"
tar -xzf "$wp_stage/public.tar.gz" -C "$wp_root"
chmod 644 \
  wp-content/plugins/avf-events-integration/includes/class-avf-event-signup-handler.php \
  wp-content/plugins/avf-events-integration/includes/class-avf-event-detail-shortcode.php \
  wp-content/plugins/avf-events-integration/assets/js/events-lists.js \
  wp-content/plugins/avf-events-integration/assets/css/events-lists.css
php -l wp-content/plugins/avf-events-integration/includes/class-avf-event-signup-handler.php
php -l wp-content/plugins/avf-events-integration/includes/class-avf-event-detail-shortcode.php
wp eval 'AVF_Events_API_Client::clear_cache();'
wp maintenance-mode deactivate
curl --fail --silent --show-error "https://www.avfroburger.ch/anlaesse/froburgfahrt/?pin_check=$(date +%s)" \
  | grep -F 'Bestehende Anmeldung bearbeiten'
)
```

Ein vorgeschalteter Seiten-/Hostingcache muss gegebenenfalls gezielt für diese Seite
geleert werden. Die CSS-/JS-URLs verwenden bereits Dateizeitstempel zur Versionierung.
Keine pauschalen Änderungen an Uploads, WordPress-Datenbank, URLs oder anderen Plugins.

## Rollback bei Fehlern

Beide Code-Versionen gemeinsam zurücksetzen, die hinzugefügten Datenbankfelder
erhalten. Keine automatische Rückwärtsmigration oder Wiederherstellung des gesamten
Datenbankbackups: Das könnte nachträgliche Änderungen oder PIN-Hashes verlieren.

In der Django-Shell:

```bash
(
set -euo pipefail
release=avf-pin-YYYYMMDD-HHMMSS
if [[ ! "$release" =~ ^avf-pin-[0-9]{8}-[0-9]{6}$ ]]; then
  printf 'Bitte den echten Release-Namen einsetzen; YYYYMMDD-HHMMSS ist ein Platzhalter.\n' >&2
  exit 1
fi
app=/srv/avf-intern/app
backup=/srv/avf-intern/backups/$release
migration=events/migrations/0009_eventsignup_pin_failed_attempts_eventsignup_pin_hash_and_more.py
sudo systemctl stop avf-intern
sudo tar -xzf "$backup/code-before.tar.gz" -C "$app"
if sudo test -f "$backup/migration-before.py"; then
  sudo cp -p "$backup/migration-before.py" "$app/$migration"
fi
sudo systemctl start avf-intern
sudo systemctl is-active --quiet avf-intern
)
```

In der WordPress-Shell:

```bash
(
set -euo pipefail
release=avf-pin-YYYYMMDD-HHMMSS
if [[ ! "$release" =~ ^avf-pin-[0-9]{8}-[0-9]{6}$ ]]; then
  printf 'Bitte den echten Release-Namen einsetzen; YYYYMMDD-HHMMSS ist ein Platzhalter.\n' >&2
  exit 1
fi
wp_root=/home/avfrobur/www/gamma.avfroburger.ch
wp_backup=/home/avfrobur/backups/$release
wp_stage=/home/avfrobur/deploy-tmp/$release
cd "$wp_root"
tar -xzf "$wp_backup/public-before.tar.gz" -C "$wp_root"
wp eval 'AVF_Events_API_Client::clear_cache();'
wp maintenance-mode deactivate
)
```

## Optional: zusätzlich auf GitHub sichern

Das ist vom Server-Deployment unabhängig. Aus dem lokalen `app`-Ordner:

```powershell
git -C intern push -u https://github.com/SkyTurtle-coder/Froburger_Webseite_intern.git feature/event-signup-pin
git -C public push -u https://github.com/SkyTurtle-coder/Froburger_Webseite_public.git feature/event-signup-pin
```
