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

printf "Schritt erfolgreich abgeschlossen.\n"
