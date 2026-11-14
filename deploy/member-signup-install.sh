#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
release="${1:?Release fehlt}"
[[ "$release" =~ ^avf-member-signup-[0-9]{8}-[0-9]{6}$ ]]
[[ "${2:?Hash fehlt}" =~ ^[a-f0-9]{64}$ && "${3:?Hash fehlt}" =~ ^[a-f0-9]{64}$ ]]
app=/srv/avf-intern/app
stage=/tmp/$release
backup=/srv/avf-intern/backups/$release
files=(events/models.py events/views.py events/public_views.py templates/events/public_event_detail.html)
additions=(events/member_signup.py events/migrations/0012_member_signup_policy.py)
python3 -c 'import hashlib,sys; assert hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest() == sys.argv[2]; assert hashlib.sha256(open(sys.argv[3],"rb").read()).hexdigest() == sys.argv[4]' "$stage/new.tar.gz" "$2" "$stage/base.tar.gz" "$3"
mkdir "$stage/new" "$stage/base" "$stage/current"
tar -xzf "$stage/new.tar.gz" -C "$stage/new"
tar -xzf "$stage/base.tar.gz" -C "$stage/base"
backup_files=("${files[@]}")
created_files=()
for file in "${files[@]}" "${additions[@]}"; do
    if sudo test -f "$app/$file"; then
        mkdir -p "$stage/current/$(dirname "$file")"
        sudo cat "$app/$file" | sed 's/\r$//' > "$stage/current/$file"
        if ! cmp -s "$stage/current/$file" "$stage/base/$file" && ! cmp -s "$stage/current/$file" "$stage/new/$file"; then
            printf 'Serverdatei weicht ab: %s. Nichts installiert.\n' "$file" >&2
            exit 1
        fi
        if [[ ! -f "$stage/base/$file" ]]; then backup_files+=("$file"); fi
    elif [[ -f "$stage/base/$file" ]]; then
        printf 'Erwartete Serverdatei fehlt: %s\n' "$file" >&2
        exit 1
    else
        created_files+=("$file")
    fi
done
django() {
    sudo systemd-run --quiet --wait --pipe --collect \
        --property=User=avfapp --property=Group=avfapp \
        --property=WorkingDirectory="$app" \
        --property=EnvironmentFile=/etc/avf-intern/avf-intern.env \
        /srv/avf-intern/venv/bin/python manage.py "$@"
}
sudo systemctl is-active --quiet avf-intern
django check
django shell -c 'from django.conf import settings; from django.db.migrations.recorder import MigrationRecorder; d=settings.DATABASES["default"]; assert d["ENGINE"] == "django.db.backends.mysql" and d["NAME"] == "avf_intern"; assert MigrationRecorder.Migration.objects.filter(app="events", name="0011_event_is_internal").exists(), "Zuerst Intern-Flag deployen"'
sudo test ! -e "$backup"
sudo install -d -m 700 "$backup"
sudo tar -czf "$backup/code-before.tar.gz" -C "$app" "${backup_files[@]}"
sudo test -s "$backup/code-before.tar.gz"
phase=before_migration
recover() {
    result=$?
    trap - ERR
    set +e
    if [[ "$phase" = before_migration ]]; then
        sudo tar -xzf "$backup/code-before.tar.gz" -C "$app"
        for file in "${created_files[@]}"; do sudo rm -f "$app/$file"; done
        sudo systemctl start avf-intern
        printf 'Vorheriger Code wiederhergestellt. Einschraenkung noch nicht freigegeben.\n' >&2
    elif [[ "$phase" = migrated ]]; then
        sudo systemctl start avf-intern
        printf 'Migration abgeschlossen; neuer Code bleibt erhalten. Dienst pruefen.\n' >&2
    else
        printf 'Migration abgebrochen. Dienst bleibt gestoppt; Schema pruefen.\n' >&2
    fi
    printf 'Deployment fehlgeschlagen. Backup: %s\n' "$backup" >&2
    exit "$result"
}
trap recover ERR
sudo systemctl stop avf-intern
sudo sh -c 'umask 077; mariadb-dump --single-transaction avf_intern > "$1"' sh "$backup/database.sql"
sudo test -s "$backup/database.sql"
for file in "${files[@]}" "${additions[@]}"; do
    sudo install -m 644 -o avfapp -g avfapp "$stage/new/$file" "$app/$file"
done
django check
django shell -c 'from django.db import connection; from django.db.migrations.executor import MigrationExecutor; target=("events","0012_member_signup_policy"); plan=MigrationExecutor(connection).migration_plan([target]); assert all((m.app_label,m.name)==target and not backwards for m,backwards in plan), "Unerwarteter Migrationsplan"'
phase=migrating
django migrate events 0012_member_signup_policy --noinput
phase=migrated
django shell -c 'from events.models import Event,EventSignup,SignupAttemptWindow; from events.public_views import _detail_payload; from events.member_signup import is_internal; list(EventSignup.objects.values_list("member_profile_id",flat=True)[:1]); SignupAttemptWindow.objects.count(); assert all(_detail_payload(e)["signups"] == [] for e in Event.objects.all() if is_internal(e))'
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
printf 'Mitgliederpruefung installiert. Backup: %s\n' "$backup"
