<?php

declare(strict_types=1);

if (PHP_SAPI !== 'cli') {
    fwrite(STDERR, "Run this script from the command line.\n");
    exit(1);
}

$defaults = [
    'wp-path' => '',
    'expected-api-endpoint' => '',
    'expected-api-base' => '',
    'expected-page-path' => '/anlaesse/',
    'detail-slug' => '',
    'legacy-limit' => '3',
    'v1-limit' => '9',
    'past-limit' => '6',
];

$args = getopt(
    '',
    [
        'wp-path:',
        'expected-api-endpoint::',
        'expected-api-base::',
        'expected-page-path::',
        'detail-slug::',
        'legacy-limit::',
        'v1-limit::',
        'past-limit::',
    ]
);
$config = array_merge($defaults, array_filter($args, static fn($value) => $value !== false));

if ($config['wp-path'] === '') {
    fwrite(STDERR, "Missing required argument --wp-path\n");
    exit(1);
}

$wpLoad = rtrim($config['wp-path'], DIRECTORY_SEPARATOR) . DIRECTORY_SEPARATOR . 'wp-load.php';
if (!file_exists($wpLoad)) {
    fwrite(STDERR, "Could not find wp-load.php at: {$wpLoad}\n");
    exit(1);
}

require $wpLoad;

if (!class_exists('AVF_Events_API_Client')) {
    fwrite(STDERR, "AVF_Events_API_Client is not available. Is the plugin active?\n");
    exit(1);
}

$requiredFields = [
    'id',
    'title',
    'slug',
    'short_description',
    'start_at',
    'end_at',
    'timezone_name',
    'location_name',
];

$assertOption = static function (string $optionName, string $expectedValue): void {
    if ($expectedValue === '') {
        return;
    }

    $actualValue = (string) get_option($optionName, '');
    if ($actualValue !== $expectedValue) {
        fwrite(STDERR, "Option mismatch for {$optionName}: expected {$expectedValue}, got {$actualValue}\n");
        exit(1);
    }
};

$validateEvent = static function (array $event, string $label) use ($requiredFields): void {
    foreach ($requiredFields as $field) {
        if (!array_key_exists($field, $event)) {
            fwrite(STDERR, "{$label} is missing field {$field}\n");
            exit(1);
        }
        if (!is_scalar($event[$field]) || trim((string) $event[$field]) === '') {
            fwrite(STDERR, "{$label} field {$field} is empty or invalid\n");
            exit(1);
        }
    }

    foreach (['detail_path', 'source_url'] as $field) {
        if (array_key_exists($field, $event) && !is_scalar($event[$field])) {
            fwrite(STDERR, "{$label} optional field {$field} is invalid\n");
            exit(1);
        }
    }
};

$validateListResult = static function ($result, string $label, bool $expectStructured) use ($validateEvent): array {
    if (is_wp_error($result)) {
        fwrite(STDERR, "{$label} failed: " . $result->get_error_message() . "\n");
        exit(1);
    }

    if ($expectStructured) {
        if (!is_array($result) || !array_key_exists('events', $result) || !is_array($result['events'])) {
            fwrite(STDERR, "{$label} returned an invalid structured result\n");
            exit(1);
        }

        foreach ($result['events'] as $index => $event) {
            if (!is_array($event)) {
                fwrite(STDERR, "{$label} event {$index} is not an array\n");
                exit(1);
            }
            $validateEvent($event, "{$label} event {$index}");
        }

        return $result['events'];
    }

    if (!is_array($result)) {
        fwrite(STDERR, "{$label} returned an invalid list result\n");
        exit(1);
    }

    foreach ($result as $index => $event) {
        if (!is_array($event)) {
            fwrite(STDERR, "{$label} event {$index} is not an array\n");
            exit(1);
        }
        $validateEvent($event, "{$label} event {$index}");
    }

    return $result;
};

$assertOption('avf_events_api_endpoint', (string) $config['expected-api-endpoint']);
$assertOption('avf_events_api_base', (string) $config['expected-api-base']);
$assertOption('avf_events_page_path', (string) $config['expected-page-path']);

AVF_Events_API_Client::clear_cache();
$client = new AVF_Events_API_Client();

$legacyEvents = $validateListResult($client->get_upcoming_events((int) $config['legacy-limit']), 'legacy upcoming', false);
$upcomingResult = $client->get_upcoming_events_v1((int) $config['v1-limit']);
$upcomingEvents = $validateListResult($upcomingResult, 'v1 upcoming', true);
$pastEvents = $validateListResult($client->get_past_events((int) $config['past-limit']), 'v1 past', true);

$detailSlug = (string) $config['detail-slug'];
if ($detailSlug === '') {
    if (!empty($upcomingEvents)) {
        $detailSlug = (string) $upcomingEvents[0]['slug'];
    } elseif (!empty($pastEvents)) {
        $detailSlug = (string) $pastEvents[0]['slug'];
    } elseif (!empty($legacyEvents)) {
        $detailSlug = (string) $legacyEvents[0]['slug'];
    }
}

if ($detailSlug === '') {
    fwrite(STDERR, "Could not determine a detail slug. Pass --detail-slug explicitly.\n");
    exit(1);
}

$detailEvent = $client->get_event_detail($detailSlug);
if (is_wp_error($detailEvent) || !is_array($detailEvent)) {
    $message = is_wp_error($detailEvent) ? $detailEvent->get_error_message() : 'invalid response';
    fwrite(STDERR, "v1 detail failed: {$message}\n");
    exit(1);
}
$validateEvent($detailEvent, 'v1 detail');

$calendarUrl = $client->get_calendar_ics_url();
if (!is_string($calendarUrl) || trim($calendarUrl) === '') {
    fwrite(STDERR, "Calendar ICS URL is empty.\n");
    exit(1);
}

echo "WordPress event integration check passed.\n";
echo 'avf_events_api_endpoint=' . get_option('avf_events_api_endpoint') . "\n";
echo 'avf_events_api_base=' . get_option('avf_events_api_base') . "\n";
echo 'avf_events_page_path=' . get_option('avf_events_page_path') . "\n";
echo 'legacy_events=' . count($legacyEvents) . "\n";
echo 'v1_upcoming_events=' . count($upcomingEvents) . "\n";
echo 'v1_past_events=' . count($pastEvents) . "\n";
echo 'detail_slug=' . $detailSlug . "\n";
echo 'calendar_ics_url=' . $calendarUrl . "\n";
