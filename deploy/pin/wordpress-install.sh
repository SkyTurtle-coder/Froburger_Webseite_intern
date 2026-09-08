#!/usr/bin/env bash
set -euo pipefail
release="${1:?Release-Name fehlt}"
if [[ ! "$release" =~ ^avf-pin-[0-9]{8}-[0-9]{6}$ ]]; then
  printf 'Ungueltiger Release-Name: %s\n' "$release" >&2
  exit 1
fi
trap 'printf "Fehler in Zeile %s. Deployment gestoppt.\n" "$LINENO" >&2' ERR
wp_root=/home/avfrobur/www/gamma.avfroburger.ch
wp_backup=/home/avfrobur/backups/$release
wp_stage=/home/avfrobur/deploy-tmp/$release
test -s "$wp_backup/public-before.tar.gz"
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

printf "Schritt erfolgreich abgeschlossen.\n"
