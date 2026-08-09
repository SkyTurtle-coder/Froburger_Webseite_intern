<?php
require dirname(__DIR__, 3) . '/public/wp-load.php';
$plugin = dirname(__DIR__, 3) . '/public/wp-content/mu-plugins/avf-members-page.php';
if (file_exists($plugin) && !class_exists('AVF_Members_Page')) {
    require_once $plugin;
}
if (!class_exists('AVF_Members_Page')) {
    fwrite(STDERR, "AVF_Members_Page not loaded\n");
    exit(1);
}
$result = AVF_Members_Page::refresh_snapshot('manual');
if (is_wp_error($result)) {
    fwrite(STDERR, $result->get_error_code() . ': ' . $result->get_error_message() . "\n");
    exit(1);
}
echo wp_json_encode([
    'generated_at' => $result['generated_at'] ?? '',
    'content_hash' => $result['content_hash'] ?? '',
    'committee_count' => isset($result['sections']['committee']['members']) ? count($result['sections']['committee']['members']) : null,
    'committee_roles' => array_map(static function($member) {
        return [
            'name' => $member['display_name'] ?? '',
            'roles' => array_map(static fn($role) => $role['label'] ?? '', $member['roles'] ?? []),
        ];
    }, $result['sections']['committee']['members'] ?? []),
], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT);
