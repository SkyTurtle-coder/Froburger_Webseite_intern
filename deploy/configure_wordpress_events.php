<?php

declare(strict_types=1);

if (PHP_SAPI !== 'cli') {
    fwrite(STDERR, "Run this script from the command line.\n");
    exit(1);
}

$defaults = [
    'wp-path' => '',
    'api-endpoint' => '',
    'api-base' => '',
    'page-path' => '/anlaesse/',
    'cache-ttl' => '300',
];

$args = getopt('', ['wp-path:', 'api-endpoint:', 'api-base:', 'page-path::', 'cache-ttl::']);
$config = array_merge($defaults, array_filter($args, static fn($value) => $value !== false));

foreach (['wp-path', 'api-endpoint', 'api-base'] as $required) {
    if ($config[$required] === '') {
        fwrite(STDERR, "Missing required argument --{$required}\n");
        exit(1);
    }
}

$wpLoad = rtrim($config['wp-path'], DIRECTORY_SEPARATOR) . DIRECTORY_SEPARATOR . 'wp-load.php';
if (!file_exists($wpLoad)) {
    fwrite(STDERR, "Could not find wp-load.php at: {$wpLoad}\n");
    exit(1);
}

require $wpLoad;

update_option('avf_events_api_endpoint', $config['api-endpoint']);
update_option('avf_events_api_base', $config['api-base']);
update_option('avf_events_page_path', $config['page-path']);
update_option('avf_events_cache_ttl', (int) $config['cache-ttl']);

if (class_exists('AVF_Events_API_Client')) {
    AVF_Events_API_Client::clear_cache();
}

echo "Configured WordPress event integration options.\n";
echo 'avf_events_api_endpoint=' . get_option('avf_events_api_endpoint') . "\n";
echo 'avf_events_api_base=' . get_option('avf_events_api_base') . "\n";
echo 'avf_events_page_path=' . get_option('avf_events_page_path') . "\n";
echo 'avf_events_cache_ttl=' . get_option('avf_events_cache_ttl') . "\n";
