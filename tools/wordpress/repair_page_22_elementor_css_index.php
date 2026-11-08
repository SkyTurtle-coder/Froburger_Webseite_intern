<?php
declare(strict_types=1);

use Elementor\Plugin;

function avf_require_wp_load(): void
{
	$candidates = [
		getcwd() . '/wp-load.php',
		dirname(__DIR__, 3) . '/public/wp-load.php',
	];

	foreach ($candidates as $candidate) {
		if (is_file($candidate)) {
			require $candidate;
			return;
		}
	}

	fwrite(STDERR, "Could not locate wp-load.php.\n");
	exit(1);
}

avf_require_wp_load();

$post_id = 22;
$backup_dir = WP_CONTENT_DIR . '/uploads/avf-backups';

if (!is_dir($backup_dir) && !wp_mkdir_p($backup_dir)) {
	fwrite(STDERR, "Could not create backup directory: {$backup_dir}\n");
	exit(1);
}

$admin_user = get_user_by('id', 1);
if (!$admin_user instanceof WP_User) {
	$admins = get_users([
		'role' => 'administrator',
		'number' => 1,
		'fields' => ['ID'],
	]);
	if (!empty($admins[0]->ID)) {
		$admin_user = get_user_by('id', (int) $admins[0]->ID);
	}
}

if ($admin_user instanceof WP_User) {
	wp_set_current_user($admin_user->ID);
}

$post = get_post($post_id);
if (!$post instanceof WP_Post) {
	fwrite(STDERR, "Post {$post_id} not found.\n");
	exit(1);
}

$document = Plugin::$instance->documents->get($post_id);
if (!$document) {
	fwrite(STDERR, "Elementor document for post {$post_id} not found.\n");
	exit(1);
}

$raw = get_post_meta($post_id, '_elementor_data', true);
$decoded = json_decode((string) $raw, true);
if (!is_array($decoded)) {
	$decoded = json_decode(wp_unslash((string) $raw), true);
}
if (!is_array($decoded)) {
	fwrite(STDERR, "Could not decode _elementor_data for post {$post_id}.\n");
	exit(1);
}

$timestamp = current_time('Ymd-His');
$backup_file = $backup_dir . '/page-22-elementor-css-index-repair-before-' . $timestamp . '.json';
$backup_payload = [
	'captured_at' => current_time('mysql'),
	'post' => [
		'ID' => $post->ID,
		'post_title' => $post->post_title,
		'post_modified' => $post->post_modified,
	],
	'meta' => [
		'_elementor_data' => get_post_meta($post_id, '_elementor_data', true),
		'_elementor_css' => get_post_meta($post_id, '_elementor_css', true),
		'_elementor_controls_usage' => get_post_meta($post_id, '_elementor_controls_usage', true),
		'_elementor_page_assets' => get_post_meta($post_id, '_elementor_page_assets', true),
		'_elementor_used_global_class' => get_post_meta($post_id, '_elementor_used_global_class', false),
		'_elementor_used_global_class_preview' => get_post_meta($post_id, '_elementor_used_global_class_preview', false),
		'_elementor_global_class_usage_indexed' => get_post_meta($post_id, '_elementor_global_class_usage_indexed', true),
		'_elementor_global_class_usage_indexed_preview' => get_post_meta($post_id, '_elementor_global_class_usage_indexed_preview', true),
	],
];

file_put_contents(
	$backup_file,
	wp_json_encode($backup_payload, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES)
);

$document->set_is_built_with_elementor(true);
$save_result = $document->save([
	'elements' => $decoded,
]);

if (!$save_result) {
	fwrite(STDERR, "Elementor document save failed for post {$post_id}.\n");
	exit(1);
}

$meta_keys = [
	'_elementor_css',
	'_elementor_controls_usage',
	'_elementor_page_assets',
	'_elementor_used_global_class',
	'_elementor_used_global_class_preview',
	'_elementor_global_class_usage_indexed',
	'_elementor_global_class_usage_indexed_preview',
];

foreach ($meta_keys as $meta_key) {
	delete_post_meta($post_id, $meta_key);
}

$css_dir = WP_CONTENT_DIR . '/uploads/elementor/css';
$patterns = [
	'post-22.css',
	'local-22-frontend-*.css',
	'local-22-preview-*.css',
	'global-22-frontend-*.css',
	'global-22-preview-*.css',
];

$deleted_css = [];
foreach ($patterns as $pattern) {
	foreach (glob($css_dir . '/' . $pattern) ?: [] as $file_path) {
		if (is_file($file_path) && @unlink($file_path)) {
			$deleted_css[] = basename($file_path);
		}
	}
}

clean_post_cache($post_id);

$result = [
	'backup_file' => $backup_file,
	'post_id' => $post_id,
	'post_modified_after' => get_post($post_id)?->post_modified,
	'deleted_css' => array_values(array_unique($deleted_css)),
	'deleted_meta_keys' => $meta_keys,
];

echo wp_json_encode($result, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . PHP_EOL;
