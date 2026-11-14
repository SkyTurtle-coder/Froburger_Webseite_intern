#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
release="${1:?Release fehlt}"
[[ "$release" =~ ^avf-event-internal-[0-9]{8}-[0-9]{6}$ ]]
[[ "${2:?Hash fehlt}" =~ ^[a-f0-9]{64}$ && "${3:?Hash fehlt}" =~ ^[a-f0-9]{64}$ ]]
[[ "${4:?Previous hash fehlt}" =~ ^[a-f0-9]{64}$ ]]
app=/srv/avf-intern/app
stage=/tmp/$release
backup=/srv/avf-intern/backups/$release
files=(events/models.py events/forms.py events/views.py events/public_views.py events/admin.py templates/events/event_list.html templates/events/public_event_detail.html)
migration=events/migrations/0011_event_is_internal.py
python3 -c 'import hashlib,sys; assert hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest() == sys.argv[2]; assert hashlib.sha256(open(sys.argv[3],"rb").read()).hexdigest() == sys.argv[4]' "$stage/new.tar.gz" "$2" "$stage/base.tar.gz" "$3"
python3 -c 'import hashlib,sys; assert hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest() == sys.argv[2]' "$stage/previous.tar.gz" "$4"
mkdir "$stage/new" "$stage/base" "$stage/previous" "$stage/current"
tar -xzf "$stage/new.tar.gz" -C "$stage/new"
tar -xzf "$stage/base.tar.gz" -C "$stage/base"
tar -xzf "$stage/previous.tar.gz" -C "$stage/previous"
for file in "${files[@]}"; do
    mkdir -p "$stage/current/$(dirname "$file")"
    sudo cat "$app/$file" | sed 's/\r$//' > "$stage/current/$file"
    if ! cmp -s "$stage/current/$file" "$stage/base/$file" && ! cmp -s "$stage/current/$file" "$stage/new/$file" && ! cmp -s "$stage/current/$file" "$stage/previous/$file"; then
        printf 'Serverdatei weicht ab: %s. Nichts installiert.\n' "$file" >&2
        exit 1
    fi
done
had_migration=0
if sudo test -f "$app/$migration"; then
    sudo cat "$app/$migration" | sed 's/\r$//' > "$stage/current-migration"
    cmp "$stage/current-migration" "$stage/new/$migration"
    had_migration=1
fi
django() {
    sudo systemd-run --quiet --wait --pipe --collect \
        --property=User=avfapp --property=Group=avfapp \
        --property=WorkingDirectory="$app" \
        --property=EnvironmentFile=/etc/avf-intern/avf-intern.env \
        /srv/avf-intern/venv/bin/python manage.py "$@"
}
sudo systemctl is-active --quiet avf-intern
django check
django shell -c 'from django.conf import settings; from django.db.migrations.recorder import MigrationRecorder; d=settings.DATABASES["default"]; assert d["ENGINE"] == "django.db.backends.mysql" and d["NAME"] == "avf_intern"; assert MigrationRecorder.Migration.objects.filter(app="events", name="0010_event_start_timing").exists(), "Migration 0010 fehlt"'
sudo test ! -e "$backup"
sudo install -d -m 700 "$backup"
backup_files=("${files[@]}")
if [[ "$had_migration" = 1 ]]; then backup_files+=("$migration"); fi
sudo tar -czf "$backup/code-before.tar.gz" -C "$app" "${backup_files[@]}"
sudo test -s "$backup/code-before.tar.gz"
phase=before_migration
recover() {
    result=$?
    trap - ERR
    set +e
    if [[ "$phase" = before_migration ]]; then
        sudo tar -xzf "$backup/code-before.tar.gz" -C "$app"
        if [[ "$had_migration" = 0 ]]; then sudo rm -f "$app/$migration"; fi
        sudo systemctl start avf-intern
        printf 'Vorheriger Code wiederhergestellt.\n' >&2
    elif [[ "$phase" = migrated ]]; then
        sudo systemctl start avf-intern
        printf 'Migration abgeschlossen. Neuer Code bleibt passend zur Datenbank erhalten; Dienst pruefen.\n' >&2
    else
        printf 'Migration abgebrochen. Dienst bleibt gestoppt: Datenbankschema vor erneutem Start pruefen. Kein automatischer Datenbank-Restore.\n' >&2
    fi
    printf 'Deployment fehlgeschlagen. Backup: %s\n' "$backup" >&2
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
# Only this migration may be pending: refuse unrelated migrations or backwards plans.
django shell -c 'from django.db import connection; from django.db.migrations.executor import MigrationExecutor; target=("events","0011_event_is_internal"); plan=MigrationExecutor(connection).migration_plan([target]); assert all((m.app_label,m.name)==target and not backwards for m,backwards in plan), "Unerwarteter Migrationsplan"'
phase=migrating
django migrate events 0011_event_is_internal --noinput
phase=migrated
django shell -c 'from events.models import Event; from events.forms import EventForm; from events.public_views import _event_to_payload; assert "is_internal" in EventForm.base_fields; assert not Event.objects.filter(status="INTERN", is_internal=False).exists(); list(Event.objects.values_list("is_internal",flat=True)[:1]); e=Event.objects.first(); assert e is None or "is_internal" in _event_to_payload(e)'
sudo systemctl start avf-intern
ready=0
for attempt in 1 2 3 4 5; do
    result=$(curl --silent --max-time 10 --header 'Host: intern.avfroburger.ch' --header 'X-Forwarded-Proto: https' http://127.0.0.1:8010/healthz/) || result=''
    if [[ "$result" = '{"status": "ok"}' ]]; then ready=1; break; fi
    sleep 2
done
test "$ready" = 1
sudo systemctl is-active --quiet avf-intern
trap - ERR
printf 'Intern-Zusatz installiert. Backup: %s\n' "$backup"
