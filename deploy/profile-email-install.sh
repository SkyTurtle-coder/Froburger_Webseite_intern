#!/usr/bin/env bash
set -euo pipefail
release="${1:?Release fehlt}"
expected_hash="${2:?Pruefsumme fehlt}"
[[ "$release" =~ ^avf-email-[0-9]{8}-[0-9]{6}$ ]]
[[ "$expected_hash" =~ ^[a-f0-9]{64}$ ]]
app=/srv/avf-intern/app
backup=/srv/avf-intern/backups/$release
archive=/tmp/$release.tar.gz
files=(accounts/forms.py accounts/admin.py templates/accounts/profile_form.html)
printf '%s  %s\n' "$expected_hash" "$archive" | sha256sum --check --status
sudo test -f "$app/manage.py"
sudo test -f /etc/avf-intern/avf-intern.env
sudo test ! -e "$backup"
sudo systemctl is-active --quiet avf-intern

django() {
    sudo systemd-run --quiet --wait --pipe --collect \
        --property=User=avfapp --property=Group=avfapp \
        --property=WorkingDirectory=/srv/avf-intern/app \
        --property=EnvironmentFile=/etc/avf-intern/avf-intern.env \
        /srv/avf-intern/venv/bin/python manage.py "$@"
}

django check
sudo install -d -m 700 "$backup"
sudo tar -czf "$backup/code-before.tar.gz" -C "$app" "${files[@]}"
sudo test -s "$backup/code-before.tar.gz"
rollback() {
    result=$?
    trap - ERR
    set +e
    printf 'Deployment fehlgeschlagen. Stelle Code aus %s wieder her.\n' "$backup" >&2
    sudo systemctl stop avf-intern
    sudo tar -xzf "$backup/code-before.tar.gz" -C "$app"
    sudo systemctl start avf-intern
    sudo systemctl is-active --quiet avf-intern || printf 'Dienst pruefen: sudo systemctl status avf-intern\n' >&2
    exit "$result"
}
trap rollback ERR
sudo systemctl stop avf-intern
sudo tar -xzf "$archive" -C "$app" "${files[@]}"
for file in "${files[@]}"; do
    sudo chown avfapp:avfapp "$app/$file"
done
django check
django shell -c 'from accounts.forms import ProfileForm, AdminProfileForm; assert "email" in ProfileForm.base_fields and "email" in AdminProfileForm.base_fields'
sudo systemctl start avf-intern
curl --retry 5 --retry-connrefused --retry-delay 2 --max-time 10 --fail --silent --show-error \
    http://127.0.0.1:8010/healthz/
sudo systemctl is-active --quiet avf-intern
trap - ERR
printf '\nE-Mail-Bearbeitung installiert. Backup: %s\n' "$backup"
