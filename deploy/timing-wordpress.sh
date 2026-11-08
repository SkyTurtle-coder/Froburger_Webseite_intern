#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
release="${1:?Release fehlt}"
[[ "$release" =~ ^avf-timing-[0-9]{8}-[0-9]{6}$ ]]
[[ "${2:?Hash fehlt}" =~ ^[a-f0-9]{64}$ && "${3:?Baseline-Hash fehlt}" =~ ^[a-f0-9]{64}$ ]]
mode="${4:?Modus fehlt}"
[[ "$mode" = check || "$mode" = install ]]
app=/home/avfrobur/www/gamma.avfroburger.ch
stage=/home/avfrobur/deploy-tmp/$release
backup=/home/avfrobur/backups/$release
prefix=wp-content/plugins/avf-events-integration/includes
files=(class-avf-events-api-client.php class-avf-events-view-helpers.php class-avf-events-list-shortcode.php class-avf-upcoming-events-shortcode.php class-avf-event-detail-shortcode.php)
cd "$app"
test "$(wp option get home)" = 'https://www.avfroburger.ch'
php -r 'exit(hash_file("sha256", $argv[1]) === $argv[2] ? 0 : 1);' "$stage/wordpress.tar.gz" "$2"
php -r 'exit(hash_file("sha256", $argv[1]) === $argv[2] ? 0 : 1);' "$stage/wordpress-base.tar.gz" "$3"
mkdir -p "$stage/new" "$stage/base"
tar -xzf "$stage/wordpress.tar.gz" -C "$stage/new"
tar -xzf "$stage/wordpress-base.tar.gz" -C "$stage/base"
paths=()
for file in "${files[@]}"; do
    path="$prefix/$file"
    paths+=("$path")
    php -l "$stage/new/$path"
    # PHP normalization works on both GNU/Linux and the Hostpoint host.
    php -r '$read = fn($p) => str_replace("\r\n", "\n", file_get_contents($p)); $current=$read($argv[1]); if ($current !== $read($argv[2]) && $current !== $read($argv[3])) { fwrite(STDERR, "Serverdatei weicht ab: ".$argv[1].". Nichts installiert.\n"); exit(1); }' "$path" "$stage/base/$path" "$stage/new/$path"
done
if [[ "$mode" = check ]]; then printf 'WordPress-Vorpruefung erfolgreich.\n'; exit 0; fi
test ! -e "$backup"
if wp maintenance-mode is-active > /dev/null 2>&1; then
    printf 'WordPress ist bereits im Wartungsmodus. Installation gestoppt.\n' >&2
    exit 1
fi
mkdir -p "$backup"
tar -czf "$backup/code-before.tar.gz" "${paths[@]}"
recover() {
    result=$?
    trap - ERR
    set +e
    tar -xzf "$backup/code-before.tar.gz" -C "$app"
    wp eval 'AVF_Events_API_Client::clear_cache();'
    wp maintenance-mode deactivate
    printf 'Vorherige WordPress-Dateien wiederhergestellt: %s\n' "$backup" >&2
    exit "$result"
}
trap recover ERR
wp maintenance-mode activate
for path in "${paths[@]}"; do cp "$stage/new/$path" "$app/$path"; chmod 644 "$app/$path"; done
wp eval 'AVF_Events_API_Client::clear_cache(); if (function_exists("wp_cache_clear_cache")) { wp_cache_clear_cache(); } if (function_exists("rocket_clean_domain")) { rocket_clean_domain(); } do_action("litespeed_purge_all");'
wp cache flush
wp eval 'if (AVF_Events_View_Helpers::timing_suffix(["start_timing"=>"ct"]) !== " c.t.") { throw new Exception("Zeitangabe nicht geladen"); }'
wp maintenance-mode deactivate
curl --fail --silent --show-error --max-time 20 "https://www.avfroburger.ch/anlaesse/?timing_check=$release" > /dev/null
trap - ERR
printf 'WordPress aktualisiert. Backup: %s\n' "$backup"
