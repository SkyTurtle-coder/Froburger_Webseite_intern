<?php
require dirname(__DIR__, 3) . '/public/wp-load.php';
$plugin = dirname(__DIR__, 3) . '/public/wp-content/mu-plugins/avf-members-page.php';
if (file_exists($plugin) && !class_exists('AVF_Members_Page')) {
    require_once $plugin;
}
$option = get_option('avf_members_snapshot_v2', []);
echo wp_json_encode([
  'generated_at' => $option['generated_at'] ?? '',
  'committee_count' => isset($option['sections']['committee']['members']) ? count($option['sections']['committee']['members']) : null,
  'committee_names' => array_map(static fn($m) => ($m['vulgo'] ?? '') . '|' . ($m['display_name'] ?? ''), $option['sections']['committee']['members'] ?? []),
  'stall_names' => array_map(static fn($m) => ($m['vulgo'] ?? '') . '|' . ($m['display_name'] ?? ''), $option['sections']['stall']['members'] ?? []),
], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT);
