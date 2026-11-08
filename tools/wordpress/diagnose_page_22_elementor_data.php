<?php
declare(strict_types=1);

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

/**
 * @return array<int|string,mixed>
 */
function avf_decode_elementor_meta(int $post_id): array
{
	$raw = get_post_meta($post_id, '_elementor_data', true);
	$result = [
		'post_id' => $post_id,
		'raw_length' => is_string($raw) ? strlen($raw) : 0,
		'decode_ok' => false,
		'top_level_type' => gettype($raw),
		'total_nodes' => 0,
		'max_depth' => 0,
		'root_element_ids' => [],
		'invalid_root_entries' => 0,
		'invalid_child_entries' => 0,
		'invalid_samples' => [],
	];

	if (!is_string($raw) || $raw === '') {
		$result['error'] = 'empty_or_non_string_meta';
		return $result;
	}

	$decoded = json_decode($raw, true);
	if (!is_array($decoded)) {
		$decoded = json_decode(wp_unslash($raw), true);
	}

	if (!is_array($decoded)) {
		$result['error'] = 'json_decode_failed: ' . json_last_error_msg();
		return $result;
	}

	$result['decode_ok'] = true;

	$walk = static function ($node, int $depth, string $path) use (&$walk, &$result): void {
		if ($depth > $result['max_depth']) {
			$result['max_depth'] = $depth;
		}

		if (!is_array($node)) {
			return;
		}

		$is_element = isset($node['id']) || isset($node['elType']) || isset($node['widgetType']);
		if ($is_element) {
			$result['total_nodes']++;
		}

		if ($depth === 1 && isset($node['id']) && is_string($node['id'])) {
			$result['root_element_ids'][] = $node['id'];
		}

		if (array_key_exists('elements', $node)) {
			if (!is_array($node['elements'])) {
				$result['invalid_child_entries']++;
				if (count($result['invalid_samples']) < 10) {
					$result['invalid_samples'][] = [
						'path' => $path . '.elements',
						'type' => gettype($node['elements']),
						'value' => is_scalar($node['elements']) ? $node['elements'] : null,
					];
				}
			} else {
				foreach ($node['elements'] as $child_index => $child) {
					if (!is_array($child) || !isset($child['id'], $child['elType'])) {
						$result['invalid_child_entries']++;
						if (count($result['invalid_samples']) < 10) {
							$result['invalid_samples'][] = [
								'path' => $path . '.elements[' . $child_index . ']',
								'type' => gettype($child),
								'value' => is_scalar($child) ? $child : null,
							];
						}
						continue;
					}

					$child_id = is_string($child['id']) ? $child['id'] : ('index-' . $child_index);
					$walk($child, $depth + 1, $path . '.elements[' . $child_id . ']');
				}
			}
		}

		if (isset($node['styles']) && !is_array($node['styles'])) {
			$result['invalid_child_entries']++;
			if (count($result['invalid_samples']) < 10) {
				$result['invalid_samples'][] = [
					'path' => $path . '.styles',
					'type' => gettype($node['styles']),
					'value' => is_scalar($node['styles']) ? $node['styles'] : null,
				];
			}
		}
	};

	foreach ($decoded as $index => $node) {
		if (!is_array($node) || !isset($node['id'], $node['elType'])) {
			$result['invalid_root_entries']++;
			if (count($result['invalid_samples']) < 10) {
				$result['invalid_samples'][] = [
					'path' => 'root[' . $index . ']',
					'type' => gettype($node),
					'value' => is_scalar($node) ? $node : null,
				];
			}
			continue;
		}

		$root_id = is_string($node['id']) ? $node['id'] : ('index-' . $index);
		$walk($node, 1, 'root[' . $root_id . ']');
	}

	return $result;
}

/**
 * @return array<int,array<string,mixed>>
 */
function avf_collect_post_variants(int $post_id): array
{
	$ids = [$post_id];

	$revisions = get_children([
		'post_parent' => $post_id,
		'post_type' => 'revision',
		'post_status' => 'inherit',
		'numberposts' => -1,
		'fields' => 'ids',
	]);

	if (is_array($revisions)) {
		foreach ($revisions as $revision_id) {
			$ids[] = (int) $revision_id;
		}
	}

	$ids = array_values(array_unique(array_map('intval', $ids)));
	$results = [];

	foreach ($ids as $id) {
		$post = get_post($id);
		if (!$post instanceof WP_Post) {
			continue;
		}

		$row = avf_decode_elementor_meta($id);
		$row['post_type'] = $post->post_type;
		$row['post_status'] = $post->post_status;
		$row['post_name'] = $post->post_name;
		$row['post_modified_gmt'] = $post->post_modified_gmt;
		$row['is_autosave'] = wp_is_post_autosave($id) ? true : false;
		$row['is_revision'] = wp_is_post_revision($id) ? true : false;
		$results[] = $row;
	}

	usort(
		$results,
		static function (array $a, array $b): int {
			return strcmp((string) $b['post_modified_gmt'], (string) $a['post_modified_gmt']);
		}
	);

	return $results;
}

avf_require_wp_load();

$post_id = 22;
$report = [
	'generated_at_gmt' => gmdate('c'),
	'post_id' => $post_id,
	'home' => home_url('/'),
	'variants' => avf_collect_post_variants($post_id),
];

echo wp_json_encode($report, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . PHP_EOL;
