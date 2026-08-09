<?php
declare(strict_types=1);

use Elementor\Plugin;

require dirname(__DIR__, 3) . '/public/wp-load.php';

$post_id = 22;
$user_id = 1;
$backup_dir = WP_CONTENT_DIR . '/uploads/avf-backups';

if (!is_dir($backup_dir) && !wp_mkdir_p($backup_dir)) {
	exit("Could not create backup directory.\n");
}

wp_set_current_user($user_id);

$post = get_post($post_id);
if (!$post) {
	exit("Post {$post_id} not found.\n");
}

$document = Plugin::$instance->documents->get($post_id);
if (!$document) {
	exit("Elementor document for post {$post_id} not found.\n");
}

if (!$document->is_editable_by_current_user()) {
	exit("Current user {$user_id} cannot edit post {$post_id}.\n");
}

$timestamp = current_time('Ymd-His');
$raw = get_post_meta($post_id, '_elementor_data', true);
$decoded = json_decode((string) $raw, true);

if (!is_array($decoded)) {
	$decoded = json_decode(wp_unslash((string) $raw), true);
}

if (!is_array($decoded)) {
	exit("Could not decode _elementor_data for post {$post_id}.\n");
}

$meta_snapshot = [
	'_elementor_data' => get_post_meta($post_id, '_elementor_data', true),
	'_elementor_edit_mode' => get_post_meta($post_id, '_elementor_edit_mode', true),
	'_elementor_template_type' => get_post_meta($post_id, '_elementor_template_type', true),
	'_elementor_version' => get_post_meta($post_id, '_elementor_version', true),
	'_elementor_page_settings' => get_post_meta($post_id, '_elementor_page_settings', true),
	'_elementor_css' => get_post_meta($post_id, '_elementor_css', true),
	'_elementor_controls_usage' => get_post_meta($post_id, '_elementor_controls_usage', true),
	'_elementor_page_assets' => get_post_meta($post_id, '_elementor_page_assets', true),
	'_elementor_used_global_class' => get_post_meta($post_id, '_elementor_used_global_class', false),
	'_elementor_used_global_class_preview' => get_post_meta($post_id, '_elementor_used_global_class_preview', false),
	'_elementor_global_class_usage_indexed' => get_post_meta($post_id, '_elementor_global_class_usage_indexed', true),
	'_elementor_global_class_usage_indexed_preview' => get_post_meta($post_id, '_elementor_global_class_usage_indexed_preview', true),
];

$backup_payload = [
	'captured_at' => current_time('mysql'),
	'post' => [
		'ID' => $post->ID,
		'post_title' => $post->post_title,
		'post_status' => $post->post_status,
		'post_modified' => $post->post_modified,
		'post_content' => $post->post_content,
	],
	'meta' => $meta_snapshot,
];

$backup_file = $backup_dir . '/ueber-uns-css-reset-repair-before-' . $timestamp . '.json';
file_put_contents(
	$backup_file,
	wp_json_encode($backup_payload, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES)
);

$stats = [
	'removed_classes' => 0,
	'removed__cssid' => 0,
	'removed_cssid' => 0,
	'visited_nodes' => 0,
];

$sanitize_nodes = static function (array $nodes) use (&$sanitize_nodes, &$stats): array {
	$out = [];

	foreach ($nodes as $node) {
		if (!is_array($node)) {
			$out[] = $node;
			continue;
		}

		$stats['visited_nodes']++;

		if (!empty($node['settings']) && is_array($node['settings'])) {
			foreach (['classes', '_cssid', 'cssid'] as $key) {
				if (array_key_exists($key, $node['settings'])) {
					unset($node['settings'][$key]);
					$stats['removed_' . $key]++;
				}
			}

			if ([] === $node['settings']) {
				$node['settings'] = [];
			}
		}

		if (!empty($node['elements']) && is_array($node['elements'])) {
			$node['elements'] = $sanitize_nodes($node['elements']);
		}

		$out[] = $node;
	}

	return $out;
};

$sanitized = $sanitize_nodes($decoded);

$document->set_is_built_with_elementor(true);
$save_result = $document->save([
	'elements' => $sanitized,
]);

if (!$save_result) {
	exit("Elementor document save failed for post {$post_id}.\n");
}

foreach ([
	'_elementor_css',
	'_elementor_controls_usage',
	'_elementor_page_assets',
	'_elementor_global_class_usage_indexed',
	'_elementor_global_class_usage_indexed_preview',
	'_elementor_used_global_class',
	'_elementor_used_global_class_preview',
] as $meta_key) {
	delete_post_meta($post_id, $meta_key);
}

clean_post_cache($post_id);

$after_raw = get_post_meta($post_id, '_elementor_data', true);
$after_decoded = json_decode((string) $after_raw, true);
if (!is_array($after_decoded)) {
	$after_decoded = json_decode(wp_unslash((string) $after_raw), true);
}

$remaining = [
	'classes' => 0,
	'_cssid' => 0,
	'cssid' => 0,
];

$count_remaining = static function (array $nodes) use (&$count_remaining, &$remaining): void {
	foreach ($nodes as $node) {
		if (!is_array($node)) {
			continue;
		}

		$settings = $node['settings'] ?? [];
		if (is_array($settings)) {
			foreach (array_keys($remaining) as $key) {
				if (array_key_exists($key, $settings)) {
					$remaining[$key]++;
				}
			}
		}

		if (!empty($node['elements']) && is_array($node['elements'])) {
			$count_remaining($node['elements']);
		}
	}
};

if (is_array($after_decoded)) {
	$count_remaining($after_decoded);
}

$result = [
	'backup_file' => $backup_file,
	'post_id' => $post_id,
	'post_modified_after' => get_post($post_id)?->post_modified,
	'post_content_length_after' => strlen((string) get_post($post_id)?->post_content),
	'stats' => $stats,
	'remaining_settings_keys' => $remaining,
	'meta_exists_after' => [
		'_elementor_css' => metadata_exists('post', $post_id, '_elementor_css'),
		'_elementor_controls_usage' => metadata_exists('post', $post_id, '_elementor_controls_usage'),
		'_elementor_page_assets' => metadata_exists('post', $post_id, '_elementor_page_assets'),
		'_elementor_used_global_class' => metadata_exists('post', $post_id, '_elementor_used_global_class'),
		'_elementor_used_global_class_preview' => metadata_exists('post', $post_id, '_elementor_used_global_class_preview'),
		'_elementor_global_class_usage_indexed' => metadata_exists('post', $post_id, '_elementor_global_class_usage_indexed'),
		'_elementor_global_class_usage_indexed_preview' => metadata_exists('post', $post_id, '_elementor_global_class_usage_indexed_preview'),
	],
];

echo wp_json_encode($result, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
