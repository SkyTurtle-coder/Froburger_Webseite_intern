#!/usr/bin/env bash
set -euo pipefail
release="${1:?Release fehlt}"
hash="${2:?Paket-Pruefsumme fehlt}"
baseline_hash="${3:?Baseline-Pruefsumme fehlt}"
[[ "$release" =~ ^avf-forum-[0-9]{8}-[0-9]{6}$ ]]
[[ "$hash" =~ ^[a-f0-9]{64}$ && "$baseline_hash" =~ ^[a-f0-9]{64}$ ]]
app=/srv/avf-intern/app
stage=/tmp/$release
backup=/srv/avf-intern/backups/$release
shared=(config/settings.py config/urls.py core/context_processors.py templates/base.html templates/partials/navigation_links.html)
paths=("${shared[@]}" forum templates/forum static/forum static/vendor/pdfjs)
printf '%s  %s\n' "$hash" "$stage/forum.tar.gz" "$baseline_hash" "$stage/baseline.tar.gz" | sha256sum --check --status
mkdir "$stage/new" "$stage/baseline"
tar -xzf "$stage/forum.tar.gz" -C "$stage/new"
tar -xzf "$stage/baseline.tar.gz" -C "$stage/baseline"
sudo test -f "$app/manage.py"
sudo test -f /etc/avf-intern/avf-intern.env
sudo test ! -e "$backup"
sudo systemctl is-active --quiet avf-intern
# Never replace server-specific changes to shared configuration or navigation.
for file in "${shared[@]}"; do
    if ! sudo cmp -s "$app/$file" "$stage/baseline/$file" && ! sudo cmp -s "$app/$file" "$stage/new/$file"; then
        printf 'Serverdatei weicht ab: %s. Vor dem Deployment abgleichen. Nichts installiert.\n' "$file" >&2
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
django check
django shell -c 'from django.conf import settings; d=settings.DATABASES["default"]; assert d["ENGINE"] == "django.db.backends.mysql" and d["NAME"] == "avf_intern", "Unerwartete Datenbank"'
sudo install -d -m 700 "$backup"
existing=()
for path in "${paths[@]}"; do
    if sudo test -e "$app/$path"; then existing+=("$path"); fi
done
sudo tar -czf "$backup/code-before.tar.gz" -C "$app" "${existing[@]}"
sudo test -s "$backup/code-before.tar.gz"
rollback() {
    result=$?
    trap - ERR
    set +e
    printf 'Deployment fehlgeschlagen. Stelle vorherigen Code aus %s wieder her.\n' "$backup" >&2
    sudo systemctl stop avf-intern
    sudo tar -xzf "$backup/code-before.tar.gz" -C "$app"
    django collectstatic --noinput
    sudo systemctl start avf-intern
    sudo systemctl is-active --quiet avf-intern || printf 'Dienst pruefen: sudo systemctl status avf-intern\n' >&2
    printf 'Neue Forum-Tabellen bleiben zur Datensicherung erhalten. Datenbank-Backup: %s/database.sql\n' "$backup" >&2
    exit "$result"
}
trap rollback ERR
sudo systemctl stop avf-intern
sudo sh -c 'umask 077; mariadb-dump --single-transaction avf_intern > "$1"' sh "$backup/database.sql"
sudo test -s "$backup/database.sql"
sudo tar -xzf "$stage/forum.tar.gz" -C "$app" "${paths[@]}"
for path in "${paths[@]}"; do sudo chown -R avfapp:avfapp "$app/$path"; done
django check
django migrate forum --noinput
django collectstatic --noinput
django shell -c 'from forum.models import Issue, Comment, CommentLike; from django.urls import reverse; Issue.objects.exists(); Comment.objects.exists(); CommentLike.objects.exists(); assert reverse("forum:list") == "/forum/"'
sudo systemctl start avf-intern
ready=0
for attempt in 1 2 3 4 5; do
    if curl --fail --silent --max-time 10 http://127.0.0.1:8010/healthz/ > /dev/null; then ready=1; break; fi
    sleep 2
done
test "$ready" = 1
sudo systemctl is-active --quiet avf-intern
trap - ERR
printf 'Forum installiert. Backup: %s\n' "$backup"
