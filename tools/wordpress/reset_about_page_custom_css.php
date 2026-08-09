<?php
declare(strict_types=1);

require dirname(__DIR__, 3) . '/public/wp-load.php';

const AVF_ABOUT_PAGE_ID = 22;
const AVF_ABOUT_BACKUP_DIR = 'public/wp-content/uploads/avf-backups';

/**
 * Removes custom CSS-related settings from one Elementor node tree.
 *
 * @param array<string,mixed> $node
 */
function avf_reset_about_css_node(array &$node, array &$stats): void
{
    if (!isset($node['settings']) || !is_array($node['settings'])) {
        $node['settings'] = array();
    }

    $settings = &$node['settings'];

    if (isset($settings['_css_classes']) && $settings['_css_classes'] !== '') {
        unset($settings['_css_classes']);
        $stats['css_classes_removed']++;
    }

    if (isset($settings['_cssid'])) {
        unset($settings['_cssid']);
        $stats['css_ids_removed']++;
    }

    $classes = $settings['classes']['value'] ?? null;
    if (is_array($classes) && $classes !== array()) {
        $filtered = array_values(array_filter(
            $classes,
            static fn($class_name): bool => !in_array($class_name, array('g-c1a0288', 'g-f55697b', 'g-717097a'), true)
        ));

        if ($filtered !== $classes) {
            $settings['classes']['value'] = $filtered;
            $stats['global_history_classes_removed'] += count($classes) - count($filtered);
        }
    }

    if (!empty($node['elements']) && is_array($node['elements'])) {
        foreach ($node['elements'] as &$child) {
            if (is_array($child)) {
                avf_reset_about_css_node($child, $stats);
            }
        }
        unset($child);
    }
}

/**
 * Resets one Elementor `_elementor_data` payload and writes a JSON backup first.
 */
function avf_reset_about_css_for_post(int $post_id, string $backup_dir): array
{
    $raw = get_post_meta($post_id, '_elementor_data', true);
    if (!is_string($raw) || $raw === '') {
        return array(
            'changed' => false,
            'skipped' => true,
            'backup' => null,
            'stats' => array(),
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
            'skipped' => true,
            'backup' => null,
            'stats' => array(),
            'error' => "Failed to decode _elementor_data for post {$post_id}.",
        );
    }

    $stats = array(
        'css_classes_removed' => 0,
        'css_ids_removed' => 0,
        'global_history_classes_removed' => 0,
    );

    foreach ($decoded as &$node) {
        if (is_array($node)) {
            avf_reset_about_css_node($node, $stats);
        }
    }
    unset($node);

    $encoded = wp_json_encode($decoded, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    if (!is_string($encoded) || $encoded === '') {
        throw new RuntimeException("Failed to encode cleaned _elementor_data for post {$post_id}.");
    }

    if ($encoded === $raw) {
        return array(
            'changed' => false,
            'skipped' => false,
            'backup' => null,
            'stats' => $stats,
            'error' => null,
        );
    }

    $backup_path = dirname(__DIR__, 3) . DIRECTORY_SEPARATOR . AVF_ABOUT_BACKUP_DIR . DIRECTORY_SEPARATOR .
        'ueber-uns-reset-css-' . $post_id . '-' . gmdate('Ymd-His') . '.json';

    if (file_put_contents($backup_path, $raw) === false) {
        throw new RuntimeException("Failed to write backup {$backup_path}.");
    }

    global $wpdb;
    $updated = $wpdb->update(
        $wpdb->postmeta,
        array('meta_value' => wp_slash($encoded)),
        array(
            'post_id' => $post_id,
            'meta_key' => '_elementor_data',
        ),
        array('%s'),
        array('%d', '%s')
    );

    if ($updated === false) {
        throw new RuntimeException("Failed to update _elementor_data for post {$post_id}.");
    }

    clean_post_cache($post_id);

    return array(
        'changed' => true,
        'skipped' => false,
        'backup' => $backup_path,
        'stats' => $stats,
        'error' => null,
    );
}

$backup_dir = dirname(__DIR__, 3) . DIRECTORY_SEPARATOR . AVF_ABOUT_BACKUP_DIR;
if (!is_dir($backup_dir) && !wp_mkdir_p($backup_dir)) {
    throw new RuntimeException("Failed to create backup directory {$backup_dir}.");
}

$results = array();
$results[AVF_ABOUT_PAGE_ID] = avf_reset_about_css_for_post(AVF_ABOUT_PAGE_ID, $backup_dir);

$revisions = get_children(array(
    'post_parent' => AVF_ABOUT_PAGE_ID,
    'post_type' => 'revision',
    'post_status' => 'inherit',
    'numberposts' => -1,
    'fields' => 'ids',
));

if (is_array($revisions)) {
    foreach ($revisions as $revision_id) {
        $results[(int) $revision_id] = avf_reset_about_css_for_post((int) $revision_id, $backup_dir);
    }
}

$css_dir = dirname(__DIR__, 3) . '/public/wp-content/uploads/elementor/css';
$patterns = array(
    'post-22.css',
    'local-22-frontend-*.css',
    'local-22-frontend-*.css',
    'local-22-preview-*.css',
    'global-22-frontend-*.css',
    'global-22-preview-*.css',
);

$deleted_css = array();
foreach ($patterns as $pattern) {
    foreach (glob($css_dir . '/' . $pattern) ?: array() as $file_path) {
        if (is_file($file_path) && @unlink($file_path)) {
            $deleted_css[] = basename($file_path);
        }
    }
}

delete_post_meta(AVF_ABOUT_PAGE_ID, '_elementor_css');
clean_post_cache(AVF_ABOUT_PAGE_ID);

echo wp_json_encode(
    array(
        'results' => $results,
        'deleted_css' => array_values(array_unique($deleted_css)),
    ),
    JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES
);
