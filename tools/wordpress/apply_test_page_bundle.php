<?php

if (! defined('ABSPATH')) {
	fwrite(STDERR, "Run this script via wp eval-file inside WordPress.\n");
	exit(1);
}

$bundlePath = null;
if (isset($args[0]) && is_string($args[0]) && '' !== $args[0]) {
	$bundlePath = $args[0];
} else {
	$bundlePath = resolve_bundle_path();
}
if (! $bundlePath || ! is_file($bundlePath)) {
	fwrite(STDERR, "Bundle file not found.\n");
	exit(1);
}

$bundle = json_decode((string) file_get_contents($bundlePath), true);
if (! is_array($bundle) || empty($bundle['pages']) || ! is_array($bundle['pages'])) {
	fwrite(STDERR, "Invalid page bundle: {$bundlePath}\n");
	exit(1);
}

$metaKeysToClear = array(
	'_elementor_css',
	'_elementor_controls_usage',
	'_elementor_page_assets',
	'_elementor_element_cache',
	'_elementor_dynamic_css',
	'_elementor_dynamic_css_ids',
);

$idMap        = array();
$restored     = array();
$frontPageNew = null;

foreach ($bundle['pages'] as $page) {
	$slug = (string) ($page['post_name'] ?? '');
	if ('' === $slug) {
		fwrite(STDERR, "Skipped bundle entry with empty post_name.\n");
		continue;
	}

	$existing = get_page_by_path($slug, OBJECT, 'page');
	$postarr  = array(
		'post_type'             => 'page',
		'post_status'           => (string) ($page['post_status'] ?? 'publish'),
		'post_title'            => (string) ($page['post_title'] ?? ''),
		'post_name'             => $slug,
		'post_content'          => (string) ($page['post_content'] ?? ''),
		'post_excerpt'          => (string) ($page['post_excerpt'] ?? ''),
		'post_author'           => (int) ($page['post_author'] ?? get_current_user_id()),
		'comment_status'        => (string) ($page['comment_status'] ?? 'closed'),
		'ping_status'           => (string) ($page['ping_status'] ?? 'closed'),
		'menu_order'            => (int) ($page['menu_order'] ?? 0),
		'post_parent'           => 0,
		'post_password'         => (string) ($page['post_password'] ?? ''),
		'post_date'             => (string) ($page['post_date'] ?? current_time('mysql')),
		'post_date_gmt'         => (string) ($page['post_date_gmt'] ?? get_gmt_from_date((string) ($page['post_date'] ?? current_time('mysql')))),
		'post_modified'         => current_time('mysql'),
		'post_modified_gmt'     => current_time('mysql', true),
		'post_content_filtered' => (string) ($page['post_content_filtered'] ?? ''),
	);

	if ($existing instanceof WP_Post) {
		$postarr['ID'] = $existing->ID;
		$result        = wp_update_post(wp_slash($postarr), true, false);
	} else {
		$result = wp_insert_post(wp_slash($postarr), true, false);
	}

	if (is_wp_error($result)) {
		fwrite(STDERR, "Failed to restore page {$slug}: " . $result->get_error_message() . "\n");
		continue;
	}

	$postId = (int) $result;
	$idMap[(string) ($page['source_id'] ?? $postId)] = $postId;
	$restored[] = array(
		'id'    => $postId,
		'slug'  => $slug,
		'title' => (string) ($page['post_title'] ?? ''),
	);

	foreach ($metaKeysToClear as $metaKey) {
		delete_post_meta($postId, $metaKey);
	}

	if (! empty($page['meta']) && is_array($page['meta'])) {
		foreach ($page['meta'] as $metaKey => $values) {
			delete_post_meta($postId, (string) $metaKey);
			if (! is_array($values)) {
				$values = array($values);
			}

			foreach ($values as $index => $value) {
				if (0 === $index) {
					update_post_meta($postId, (string) $metaKey, maybe_unserialize($value));
				} else {
					add_post_meta($postId, (string) $metaKey, maybe_unserialize($value));
				}
			}
		}
	}

	if (! empty($page['is_front_page'])) {
		$frontPageNew = $postId;
	}
}

if ('page' === ($bundle['options']['show_on_front'] ?? '') && $frontPageNew) {
	update_option('show_on_front', 'page');
	update_option('page_on_front', $frontPageNew);
}

if (isset($bundle['options']['page_for_posts']) && '' !== (string) $bundle['options']['page_for_posts']) {
	$pageForPostsOld = (string) $bundle['options']['page_for_posts'];
	if (isset($idMap[$pageForPostsOld])) {
		update_option('page_for_posts', $idMap[$pageForPostsOld]);
	}
}

if (! empty($bundle['options']['avf_events_page_path'])) {
	update_option('avf_events_page_path', (string) $bundle['options']['avf_events_page_path']);
}

flush_rewrite_rules(false);

if (class_exists('\Elementor\Plugin')) {
	\Elementor\Plugin::$instance->files_manager->clear_cache();
}

wp_cache_flush();

echo "Restored pages from bundle: {$bundlePath}\n";
foreach ($restored as $page) {
	echo '- ' . $page['id'] . ' ' . $page['slug'] . ' (' . $page['title'] . ')' . "\n";
}
if ($frontPageNew) {
	echo 'Front page set to post ID ' . $frontPageNew . "\n";
}

function resolve_bundle_path(): ?string {
	$fallbacks = array(
		'/home/avfrobur/deploy-tmp/test-page-bundle.latest.json',
		getcwd() . '/test-page-bundle.latest.json',
	);

	foreach ($fallbacks as $fallback) {
		if (is_string($fallback) && '' !== $fallback && is_file($fallback)) {
			return $fallback;
		}
	}

	if (isset($GLOBALS['args'][0]) && is_string($GLOBALS['args'][0]) && '' !== $GLOBALS['args'][0]) {
		return $GLOBALS['args'][0];
	}

	global $argv;
	if (is_array($argv) && isset($argv[1]) && is_string($argv[1]) && '' !== $argv[1]) {
		return $argv[1];
	}

	if (isset($_SERVER['argv']) && is_array($_SERVER['argv']) && isset($_SERVER['argv'][1]) && is_string($_SERVER['argv'][1]) && '' !== $_SERVER['argv'][1]) {
		return $_SERVER['argv'][1];
	}

	return null;
}
