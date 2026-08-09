<?php
declare(strict_types=1);

$root = dirname(__DIR__) . '/public/wp-load.php';
if (! file_exists($root)) {
	fwrite(STDERR, "wp-load.php not found\n");
	exit(1);
}

require $root;

$postId = 22;
$widgetId = '11760c9';
$targetAttachmentId = 103;
$targetUrl = 'http://avfroburger.local/wp-content/uploads/2026/07/Schild.svg';

$raw = get_post_meta($postId, '_elementor_data', true);
if (! is_string($raw) || $raw === '') {
	fwrite(STDERR, "No _elementor_data found for post {$postId}\n");
	exit(1);
}

$data = json_decode($raw, true);
if (! is_array($data)) {
	fwrite(STDERR, "Failed to decode _elementor_data JSON\n");
	exit(1);
}

$updated = false;

$walk = function (&$node) use (&$walk, &$updated, $widgetId, $targetAttachmentId, $targetUrl): void {
	if (! is_array($node)) {
		return;
	}

	if (($node['id'] ?? null) === $widgetId && ($node['widgetType'] ?? null) === 'e-svg') {
		$node['settings']['svg'] = [
			'$$type' => 'svg-src',
			'value' => [
				'id' => [
					'$$type' => 'image-attachment-id',
					'value' => $targetAttachmentId,
				],
				'url' => [
					'$$type' => 'url',
					'value' => $targetUrl,
				],
			],
		];
		$updated = true;
	}

	foreach ($node as &$value) {
		if (is_array($value)) {
			$walk($value);
		}
	}
	unset($value);
};

$walk($data);

if (! $updated) {
	fwrite(STDERR, "Widget {$widgetId} not found\n");
	exit(1);
}

$backupPath = __DIR__ . '/post-22-elementor-data-backup-before-svg-fix.json';
file_put_contents($backupPath, $raw);

$encoded = wp_json_encode($data);
if (! is_string($encoded) || $encoded === '') {
	fwrite(STDERR, "Failed to encode updated _elementor_data JSON\n");
	exit(1);
}

update_post_meta($postId, '_elementor_data', wp_slash($encoded));
clean_post_cache($postId);

echo "Updated widget {$widgetId} on post {$postId} to attachment {$targetAttachmentId}\n";
echo "Backup written to {$backupPath}\n";
