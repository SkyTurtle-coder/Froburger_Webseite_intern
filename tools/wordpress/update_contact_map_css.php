<?php
declare(strict_types=1);

use Elementor\Plugin;

require dirname(__DIR__, 3) . '/public/wp-load.php';

$post_id = 1206;
$user_id = 1;

wp_set_current_user($user_id);

$document = Plugin::$instance->documents->get($post_id);
if (!$document) {
	exit("Elementor document for post {$post_id} not found.\n");
}

if (!$document->is_editable_by_current_user()) {
	exit("Current user {$user_id} cannot edit post {$post_id}.\n");
}

$raw = get_post_meta($post_id, '_elementor_data', true);
$data = json_decode((string) $raw, true);
if (!is_array($data)) {
	$data = json_decode(wp_unslash((string) $raw), true);
}

if (!is_array($data)) {
	exit("Could not decode _elementor_data for post {$post_id}.\n");
}

$updated = false;

$walk = static function (array &$nodes) use (&$walk, &$updated): void {
	foreach ($nodes as &$node) {
		if (!is_array($node)) {
			continue;
		}

		if (($node['id'] ?? '') === '04029bf') {
			unset($node['styles']['e-04029bf-4688eda']['variants'][0]['custom_css']);
			$updated = true;
		}

		if (!empty($node['elements']) && is_array($node['elements'])) {
			$walk($node['elements']);
		}
	}
};

$walk($data);

if (!$updated) {
	exit("Target container 04029bf not found.\n");
}

$document->save([
	'elements' => $data,
]);

foreach ([
	'_elementor_css',
	'_elementor_controls_usage',
	'_elementor_page_assets',
	'_elementor_element_cache',
] as $meta_key) {
	delete_post_meta($post_id, $meta_key);
}

foreach ([
	WP_CONTENT_DIR . '/uploads/elementor/css/global-1206-frontend-desktop.css',
	WP_CONTENT_DIR . '/uploads/elementor/css/local-1206-frontend-desktop.css',
	WP_CONTENT_DIR . '/uploads/elementor/css/local-1206-frontend-mobile.css',
	WP_CONTENT_DIR . '/uploads/elementor/css/post-1206.css',
] as $css_file) {
	if (file_exists($css_file)) {
		wp_delete_file($css_file);
	}
}

clean_post_cache($post_id);

echo "Updated contact map CSS for post {$post_id}.\n";
