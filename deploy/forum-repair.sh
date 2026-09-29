#!/usr/bin/env bash
set -Eeuo pipefail
release="${1:?Release fehlt}"
[[ "$release" =~ ^avf-forum-[0-9]{8}-[0-9]{6}$ ]]
app=/srv/avf-intern/app
backup=/srv/avf-intern/backups/$release
sudo test -s "$backup/code-before.tar.gz"
django() {
    sudo systemd-run --quiet --wait --pipe --collect \
        --property=User=avfapp --property=Group=avfapp \
        --property=WorkingDirectory=/srv/avf-intern/app \
        --property=EnvironmentFile=/etc/avf-intern/avf-intern.env \
        /srv/avf-intern/venv/bin/python manage.py "$@"
}
rollback() {
    result=$?
    trap - ERR
    set +e
    printf 'Reparatur fehlgeschlagen. Stelle vorherigen Code wieder her.\n' >&2
    sudo systemctl stop avf-intern
    sudo tar -xzf "$backup/code-before.tar.gz" -C "$app"
    django collectstatic --noinput
    sudo systemctl start avf-intern
    sudo systemctl is-active avf-intern
    printf 'Forum-Tabellen bleiben erhalten. Backup: %s\n' "$backup" >&2
    exit "$result"
}
trap rollback ERR
# Only repair the inaccessible parent; private backups and settings stay private.
sudo install -d -m 755 -o avfapp -g avfapp "$app/static/vendor"
sudo -u avfapp test -r "$app/static/vendor/pdfjs/pdf.js"
sudo -u avfapp test -r "$app/static/vendor/pdfjs/pdf.worker.js"
django check
django migrate forum --noinput
django collectstatic --noinput
django shell -c 'from forum.models import Issue, Comment, CommentLike; from django.urls import reverse; Issue.objects.exists(); Comment.objects.exists(); CommentLike.objects.exists(); assert reverse("forum:list") == "/forum/"'
sudo systemctl restart avf-intern
ready=0
for attempt in 1 2 3 4 5; do
    if curl --fail --silent --max-time 10 http://127.0.0.1:8010/healthz/ > /dev/null; then ready=1; break; fi
    sleep 2
done
test "$ready" = 1
sudo systemctl is-active --quiet avf-intern
trap - ERR
printf 'Forum-Installation abgeschlossen, Dienst aktiv. Backup: %s\n' "$backup"
