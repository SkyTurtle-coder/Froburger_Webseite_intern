<?php
declare(strict_types=1);

require dirname(__DIR__, 3) . '/public/wp-load.php';

const AVF_ABOUT_SLUG = 'ueber-uns';
const AVF_HISTORY_HEADING_OLD = 'Eine Erfolgsgeschichte seit 1993';
const AVF_HISTORY_HEADING_NEW = 'Unsere Geschichte seit 1938';
const AVF_HISTORY_ROOT_ID = 'b15e10c';
const AVF_HISTORY_HEADING_ID = '294fe8c';
const AVF_HISTORY_TIMELINE_GLOBAL_CLASS = 'g-c1a0288';
const AVF_HISTORY_ITEM_GLOBAL_CLASS = 'g-f55697b';
const AVF_HISTORY_MARKER_GLOBAL_CLASS = 'g-717097a';

const AVF_ABOUT_CLASS_MAP = array(
    '963215d' => array('avf-about-page'),
    '221e5f5' => array('avf-media-text', 'avf-media-text--intro'),
    'c562f80' => array('avf-media', 'avf-media--portrait', 'avf-media-text__media', 'avf-media--focus-center'),
    '03a85cb' => array('avf-media-text__content'),
    '6a91fa2' => array('avf-values-sections'),
    '9343111' => array('avf-media-text'),
    '832e8f3' => array('avf-media-text__content'),
    '9e87626' => array('avf-media', 'avf-media--landscape', 'avf-media-text__media', 'avf-media--focus-center'),
    '7e1e982' => array('avf-media-text', 'avf-media-text--reverse'),
    '0ed4bff' => array('avf-media-text__content'),
    '7dd1ee2' => array('avf-media', 'avf-media--landscape', 'avf-media-text__media', 'avf-media--focus-center'),
    '7535337' => array('avf-media-text'),
    '7170660' => array('avf-media-text__content'),
    '6f6e021' => array('avf-media', 'avf-media--landscape', 'avf-media-text__media', 'avf-media--focus-center'),
    '59278e0' => array('avf-couleur'),
    '4926446' => array('avf-couleur__layout'),
    '0d6f2e2' => array('avf-couleur__content'),
    '885e493' => array('avf-couleur__crest'),
);

/**
 * Removes one or more Elementor class tokens from settings.classes.value.
 */
function avf_remove_elementor_classes(array &$settings, array $class_names): int
{
    $classes = $settings['classes']['value'] ?? null;
    if (!is_array($classes) || $class_names === []) {
        return 0;
    }

    $before = count($classes);
    $filtered = array_values(array_filter(
        $classes,
        static fn($class_name): bool => !in_array($class_name, $class_names, true)
    ));

    $settings['classes']['value'] = $filtered;

    return $before - count($filtered);
}

/**
 * Recursively appends a CSS class string without duplicating entries.
 */
function avf_append_css_class(array &$settings, string $class_name): void
{
    $existing = isset($settings['_css_classes']) && is_string($settings['_css_classes'])
        ? preg_split('/\s+/', trim($settings['_css_classes'])) ?: []
        : [];

    if (!in_array($class_name, $existing, true)) {
        $existing[] = $class_name;
    }

    $settings['_css_classes'] = trim(implode(' ', array_filter($existing)));
}

/**
 * Returns whether the node declares the given Elementor class token.
 */
function avf_has_elementor_class(array $node, string $class_name): bool
{
    $classes = $node['settings']['classes']['value'] ?? null;

    return is_array($classes) && in_array($class_name, $classes, true);
}

/**
 * Removes local Elementor style payload that conflicts with the timeline CSS.
 */
function avf_strip_local_style_payload(array &$node): void
{
    unset($node['styles']);
}

/**
 * Removes layout-sensitive inline settings that must be owned by site CSS.
 */
function avf_remove_layout_overrides(array &$settings, array $keys): int
{
    $removed = 0;

    foreach ($keys as $key) {
        if (array_key_exists($key, $settings)) {
            unset($settings[$key]);
            $removed++;
        }
    }

    return $removed;
}

/**
 * Applies the history section migration recursively to Elementor nodes.
 */
function avf_patch_history_node(array &$node, array &$stats): void
{
    $settings = &$node['settings'];
    $node_id = $node['id'] ?? '';

    if (isset(AVF_ABOUT_CLASS_MAP[$node_id])) {
        foreach (AVF_ABOUT_CLASS_MAP[$node_id] as $class_name) {
            avf_append_css_class($settings, $class_name);
        }
        $stats['about_classes_applied']++;
    }

    if ($node_id === AVF_HISTORY_ROOT_ID) {
        unset($settings['_cssid']);
        avf_append_css_class($settings, 'avf-history');
        $stats['timeline_global_classes_removed'] += avf_remove_elementor_classes(
            $settings,
            array(AVF_HISTORY_TIMELINE_GLOBAL_CLASS, AVF_HISTORY_ITEM_GLOBAL_CLASS, AVF_HISTORY_MARKER_GLOBAL_CLASS)
        );
        $stats['history_section_marked'] = true;
    }

    if ($node_id === AVF_HISTORY_HEADING_ID && ($node['widgetType'] ?? '') === 'heading') {
        if (($settings['title'] ?? null) === AVF_HISTORY_HEADING_OLD) {
            $settings['title'] = AVF_HISTORY_HEADING_NEW;
            $stats['heading_updated'] = true;
        }
        avf_append_css_class($settings, 'avf-history__heading');
    }

    if (avf_has_elementor_class($node, AVF_HISTORY_TIMELINE_GLOBAL_CLASS)) {
        avf_append_css_class($settings, 'avf-timeline');
        $stats['timeline_global_classes_removed'] += avf_remove_elementor_classes(
            $settings,
            array(AVF_HISTORY_TIMELINE_GLOBAL_CLASS)
        );
        avf_remove_layout_overrides($settings, array('gap'));
        avf_strip_local_style_payload($node);
        $stats['timeline_marked'] = true;
    }

    if (avf_has_elementor_class($node, AVF_HISTORY_ITEM_GLOBAL_CLASS)) {
        avf_append_css_class($settings, 'avf-timeline__item');
        $stats['timeline_global_classes_removed'] += avf_remove_elementor_classes(
            $settings,
            array(AVF_HISTORY_ITEM_GLOBAL_CLASS)
        );
        $stats['timeline_layout_overrides_removed'] += avf_remove_layout_overrides(
            $settings,
            array('gap', 'justify_content', 'align_items', 'padding', '_padding', '_margin', 'margin')
        );
        avf_strip_local_style_payload($node);
        $stats['timeline_items_cleaned']++;
    }

    if (avf_has_elementor_class($node, AVF_HISTORY_MARKER_GLOBAL_CLASS)) {
        avf_append_css_class($settings, 'avf-timeline__marker');
        $stats['timeline_global_classes_removed'] += avf_remove_elementor_classes(
            $settings,
            array(AVF_HISTORY_MARKER_GLOBAL_CLASS)
        );
        $stats['timeline_layout_overrides_removed'] += avf_remove_layout_overrides(
            $settings,
            array('gap', 'justify_content', 'align_items', 'padding', '_padding', '_margin', 'margin')
        );
        avf_strip_local_style_payload($node);
        $stats['timeline_markers_cleaned']++;
    }

    if (str_contains(' ' . (string) ($settings['_css_classes'] ?? '') . ' ', ' avf-timeline__content ')) {
        unset($settings['_padding'], $settings['_padding_tablet'], $settings['_padding_mobile']);
        $stats['timeline_layout_overrides_removed'] += avf_remove_layout_overrides(
            $settings,
            array('align', 'align_tablet', 'align_mobile')
        );
        $settings['align_mobile'] = 'start';
        $stats['timeline_content_cleaned']++;
    }

    if (str_contains(' ' . (string) ($settings['_css_classes'] ?? '') . ' ', ' avf-timeline__year ')) {
        $stats['timeline_years_seen']++;
    }

    if (!empty($node['elements']) && is_array($node['elements'])) {
        foreach ($node['elements'] as &$child) {
            if (is_array($child)) {
                avf_patch_history_node($child, $stats);
            }
        }
        unset($child);
    }
}

/**
 * Applies the Elementor history cleanup to one post or revision.
 *
 * @return array{changed:bool,backup:?string,stats:array<string,int|bool>,skipped:bool,error:?string}
 */
function avf_patch_elementor_post(int $post_id, string $meta_key, string $backup_dir): array
{
    $raw = get_post_meta($post_id, $meta_key, true);
    if (!is_string($raw) || $raw === '') {
        return array(
            'changed' => false,
            'backup' => null,
            'stats' => array(),
            'skipped' => true,
            'error' => null,
        );
    }

    $decoded = json_decode($raw, true);
    if (!is_array($decoded)) {
        $decoded = json_decode(wp_unslash($raw), true);
    }
    if (!is_array($decoded)) {
        return array(
            'changed' => false,
            'backup' => null,
            'stats' => array(),
            'skipped' => true,
            'error' => "Failed to decode Elementor JSON for post {$post_id}.",
        );
    }

    $stats = array(
        'history_section_marked' => false,
        'heading_updated' => false,
        'timeline_marked' => false,
        'timeline_items_cleaned' => 0,
        'timeline_markers_cleaned' => 0,
        'timeline_content_cleaned' => 0,
        'timeline_years_seen' => 0,
        'timeline_global_classes_removed' => 0,
        'timeline_layout_overrides_removed' => 0,
        'about_classes_applied' => 0,
    );

    foreach ($decoded as &$node) {
        if (is_array($node)) {
            avf_patch_history_node($node, $stats);
        }
    }
    unset($node);

    $encoded = wp_json_encode($decoded, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    if (!is_string($encoded) || $encoded === '') {
        throw new RuntimeException("Failed to encode patched Elementor JSON for post {$post_id}.");
    }

    if ($encoded === $raw) {
        return array(
            'changed' => false,
            'backup' => null,
            'stats' => $stats,
            'skipped' => false,
            'error' => null,
        );
    }

    $backup_path = $backup_dir . '/ueber-uns-elementor-data-' . $post_id . '-' . gmdate('Ymd-His') . '.json';
    if (file_put_contents($backup_path, $raw) === false) {
        throw new RuntimeException("Failed to write backup file: {$backup_path}");
    }

    global $wpdb;
    $updated = $wpdb->update(
        $wpdb->postmeta,
        array('meta_value' => wp_slash($encoded)),
        array(
            'post_id' => $post_id,
            'meta_key' => $meta_key,
        ),
        array('%s'),
        array('%d', '%s')
    );

    if ($updated === false) {
        throw new RuntimeException("Failed to update Elementor meta for post {$post_id}.");
    }

    clean_post_cache($post_id);

    return array(
        'changed' => true,
        'backup' => $backup_path,
        'stats' => $stats,
        'skipped' => false,
        'error' => null,
    );
}

$post = get_page_by_path(AVF_ABOUT_SLUG, OBJECT, 'page');
if (!$post instanceof WP_Post) {
    fwrite(STDERR, "About page with slug '" . AVF_ABOUT_SLUG . "' not found.\n");
    exit(1);
}

$meta_key = '_elementor_data';

$backup_dir = dirname(__DIR__, 3) . '/public/wp-content/uploads/avf-backups';
if (!is_dir($backup_dir) && !wp_mkdir_p($backup_dir)) {
    fwrite(STDERR, "Failed to create backup directory: {$backup_dir}\n");
    exit(1);
}

$results = array();
$results[$post->ID] = avf_patch_elementor_post($post->ID, $meta_key, $backup_dir);

$revision_ids = get_children(array(
    'post_parent' => $post->ID,
    'post_type' => 'revision',
    'numberposts' => -1,
    'post_status' => 'inherit',
    'fields' => 'ids',
));

if (is_array($revision_ids)) {
    foreach ($revision_ids as $revision_id) {
        $results[(int) $revision_id] = avf_patch_elementor_post((int) $revision_id, $meta_key, $backup_dir);
    }
}

$elementor_css_dir = dirname(__DIR__, 3) . '/public/wp-content/uploads/elementor/css';
$css_cache_patterns = array(
    'post-' . $post->ID . '.css',
    'local-' . $post->ID . '-frontend-*.css',
    'local-' . $post->ID . '-preview-*.css',
    'global-' . $post->ID . '-frontend-*.css',
    'global-' . $post->ID . '-preview-*.css',
);

$purged_css_files = array();
foreach ($css_cache_patterns as $pattern) {
    foreach (glob($elementor_css_dir . '/' . $pattern) ?: array() as $file_path) {
        if (is_file($file_path) && @unlink($file_path)) {
            $purged_css_files[] = basename($file_path);
        }
    }
}

echo "Patched post {$post->ID} (" . $post->post_name . ")\n";
echo "Changed entries: " . count(array_filter($results, static fn(array $result): bool => $result['changed'])) . "\n";
echo "Primary backup: " . ($results[$post->ID]['backup'] ?? 'none') . "\n";
echo "Heading updated: " . (($results[$post->ID]['stats']['heading_updated'] ?? false) ? 'yes' : 'no') . "\n";
echo "History section marked: " . (($results[$post->ID]['stats']['history_section_marked'] ?? false) ? 'yes' : 'no') . "\n";
echo "Timeline container marked: " . (($results[$post->ID]['stats']['timeline_marked'] ?? false) ? 'yes' : 'no') . "\n";
echo "Timeline items cleaned: " . ($results[$post->ID]['stats']['timeline_items_cleaned'] ?? 0) . "\n";
echo "Timeline markers cleaned: " . ($results[$post->ID]['stats']['timeline_markers_cleaned'] ?? 0) . "\n";
echo "Timeline content widgets cleaned: " . ($results[$post->ID]['stats']['timeline_content_cleaned'] ?? 0) . "\n";
echo "Timeline years seen: " . ($results[$post->ID]['stats']['timeline_years_seen'] ?? 0) . "\n";
echo "Timeline global classes removed: " . ($results[$post->ID]['stats']['timeline_global_classes_removed'] ?? 0) . "\n";
echo "Timeline layout overrides removed: " . ($results[$post->ID]['stats']['timeline_layout_overrides_removed'] ?? 0) . "\n";
echo "About classes applied: " . ($results[$post->ID]['stats']['about_classes_applied'] ?? 0) . "\n";
$changed_revision_ids = array_keys(array_filter(
    $results,
    static fn(array $result, int $id): bool => $id !== $post->ID && $result['changed'],
    ARRAY_FILTER_USE_BOTH
));
$skipped_ids = array_keys(array_filter(
    $results,
    static fn(array $result): bool => $result['skipped'],
));
echo "Changed revision IDs: " . ($changed_revision_ids === [] ? 'none' : implode(', ', $changed_revision_ids)) . "\n";
echo "Skipped entries: " . ($skipped_ids === [] ? 'none' : implode(', ', $skipped_ids)) . "\n";
echo "Purged Elementor CSS files: " . ($purged_css_files === [] ? 'none' : implode(', ', $purged_css_files)) . "\n";
