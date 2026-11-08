#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
release="${1:?Release fehlt}"
[[ "$release" =~ ^avf-timing-[0-9]{8}-[0-9]{6}$ ]]
[[ "${2:?Hash fehlt}" =~ ^[a-f0-9]{64}$ && "${3:?Baseline-Hash fehlt}" =~ ^[a-f0-9]{64}$ ]]
app=/srv/avf-intern/app
stage=/tmp/$release
backup=/srv/avf-intern/backups/$release
files=(events/models.py events/forms.py events/admin.py events/public_views.py templates/events/event_list.html templates/events/public_event_detail.html templates/core/dashboard.html)
migration=events/migrations/0010_event_start_timing.py
printf '%s  %s\n' "$2" "$stage/backend.tar.gz" "$3" "$stage/backend-base.tar.gz" | sha256sum --check --status
mkdir "$stage/new" "$stage/base" "$stage/current"
tar -xzf "$stage/backend.tar.gz" -C "$stage/new"
tar -xzf "$stage/backend-base.tar.gz" -C "$stage/base"
for file in "${files[@]}"; do
    mkdir -p "$stage/current/$(dirname "$file")"
    sudo cat "$app/$file" | sed 's/\r$//' > "$stage/current/$file"
    sed -i 's/\r$//' "$stage/new/$file" "$stage/base/$file"
    if ! cmp -s "$stage/current/$file" "$stage/base/$file" && ! cmp -s "$stage/current/$file" "$stage/new/$file"; then
        printf 'Serverdatei weicht ab: %s. Nichts installiert.\n' "$file" >&2
        exit 1
    fi
done
django() {
    sudo systemd-run --quiet --wait --pipe --collect \
        --property=User=avfapp --property=Group=avfapp \
        --property=WorkingDirectory=/srv/avf-intern/app \
        --property=EnvironmentFile=/etc/avf-intern/avf-intern.env \
        /srv/avf-intern/venv/bin/python manage.py "$@"
}
sudo systemctl is-active --quiet avf-intern
django check
django shell -c 'from django.conf import settings; from django.db.migrations.recorder import MigrationRecorder; d=settings.DATABASES["default"]; assert d["ENGINE"] == "django.db.backends.mysql" and d["NAME"] == "avf_intern"; assert MigrationRecorder.Migration.objects.filter(app="events",name="0009_eventsignup_pin_failed_attempts_eventsignup_pin_hash_and_more").exists(), "PIN-Migration 0009 fehlt"'
sudo test ! -e "$backup"
sudo install -d -m 700 "$backup"
backup_files=("${files[@]}")
if sudo test -f "$app/$migration"; then backup_files+=("$migration"); fi
sudo tar -czf "$backup/code-before.tar.gz" -C "$app" "${backup_files[@]}"
schema_ready=0
recover() {
    result=$?
    trap - ERR
    set +e
    if [[ "$schema_ready" = 0 ]]; then
        sudo tar -xzf "$backup/code-before.tar.gz" -C "$app"
        printf 'Vorheriger Code wiederhergestellt. Backup: %s\n' "$backup" >&2
    else
        printf 'Migration erfolgreich; installierter Code bleibt passend zur Datenbank erhalten. Backup: %s\n' "$backup" >&2
    fi
    sudo systemctl start avf-intern
    sudo systemctl status avf-intern --no-pager
    exit "$result"
}
trap recover ERR
sudo systemctl stop avf-intern
sudo sh -c 'umask 077; mariadb-dump --single-transaction avf_intern > "$1"' sh "$backup/database.sql"
sudo test -s "$backup/database.sql"
for file in "${files[@]}" "$migration"; do
    sudo install -m 644 -o avfapp -g avfapp "$stage/new/$file" "$app/$file"
done
django check
django migrate events --noinput
schema_ready=1
django shell -c 'from events.models import Event; from events.forms import EventForm; from events.public_views import _event_to_payload; assert "start_timing" in EventForm.base_fields; list(Event.objects.values_list("start_timing", flat=True)[:1]); e=Event.objects.first(); assert e is None or "start_timing" in _event_to_payload(e)'
sudo systemctl start avf-intern
ready=0
for attempt in 1 2 3 4 5; do
    if curl --fail --silent --max-time 10 http://127.0.0.1:8010/healthz/ > /dev/null; then ready=1; break; fi
    sleep 2
done
test "$ready" = 1
sudo systemctl is-active --quiet avf-intern
trap - ERR
printf 'Django aktualisiert. Backup: %s\n' "$backup"
