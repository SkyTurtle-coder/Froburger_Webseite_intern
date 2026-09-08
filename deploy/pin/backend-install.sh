#!/usr/bin/env bash
set -euo pipefail
release="${1:?Release-Name fehlt}"
if [[ ! "$release" =~ ^avf-pin-[0-9]{8}-[0-9]{6}$ ]]; then
  printf 'Ungueltiger Release-Name: %s\n' "$release" >&2
  exit 1
fi
trap 'printf "Fehler in Zeile %s. Deployment gestoppt.\n" "$LINENO" >&2' ERR
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

printf "Schritt erfolgreich abgeschlossen.\n"
