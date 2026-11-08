<?php

declare(strict_types=1);

if (PHP_SAPI !== 'cli') {
	fwrite(STDERR, "Run this script from the command line.\n");
	exit(1);
}

ini_set('memory_limit', '512M');

$appRoot    = dirname(__DIR__, 3);
$dumpPath   = $argv[1] ?? ($appRoot . '/sql/local.sql');
$outputPath = $argv[2] ?? ($appRoot . '/intern/tools/wordpress/backups/test-page-bundle-' . gmdate('Ymd-His') . '.json');

if (! is_file($dumpPath)) {
	fwrite(STDERR, "SQL dump not found: {$dumpPath}\n");
	exit(1);
}

$targetSlugs = array(
	'ueber-uns',
	'mitglieder',
	'aktuelles',
	'anlaesse',
	'mitglied-werden',
	'kontakt',
	'impressum',
	'datenschutz',
);

$cacheMetaKeys = array(
	'_edit_lock',
	'_edit_last',
	'_elementor_css',
	'_elementor_controls_usage',
	'_elementor_page_assets',
	'_elementor_element_cache',
	'_elementor_dynamic_css',
	'_elementor_dynamic_css_ids',
	'_elementor_global_class_usage_indexed',
	'_elementor_global_class_usage_indexed_preview',
	'_elementor_used_global_class_preview',
	'_elementor_css_file',
);

$sql = file_get_contents($dumpPath);
if (false === $sql) {
	fwrite(STDERR, "Could not read SQL dump: {$dumpPath}\n");
	exit(1);
}

$pageOnFront    = find_option_value($sql, 'page_on_front');
$showOnFront    = find_option_value($sql, 'show_on_front');
$pageForPosts   = find_option_value($sql, 'page_for_posts');
$eventsPagePath = find_option_value($sql, 'avf_events_page_path');

$postStatements = extract_all_insert_values($sql, 'wp_posts');
if (empty($postStatements)) {
	fwrite(STDERR, "Could not find wp_posts INSERT in dump.\n");
	exit(1);
}

$postRows   = array();
$targetIds  = array();
$targetData = array();

foreach ($postStatements as $postValues) {
	$postRows = array_merge($postRows, parse_insert_rows($postValues));
}

foreach ($postRows as $row) {
	$fields = split_sql_fields($row);
	if (count($fields) < 23) {
		continue;
	}

	$postId   = (int) sql_unescape($fields[0]);
	$postType = (string) sql_unescape($fields[20]);
	$postSlug = (string) sql_unescape($fields[11]);

	if ('page' !== $postType) {
		continue;
	}

	if ((string) $postId !== (string) $pageOnFront && ! in_array($postSlug, $targetSlugs, true)) {
		continue;
	}

	$targetIds[$postId] = true;
	$targetData[$postId] = array(
		'source_id'       => $postId,
		'post_author'     => (int) sql_unescape($fields[1]),
		'post_date'       => (string) sql_unescape($fields[2]),
		'post_date_gmt'   => (string) sql_unescape($fields[3]),
		'post_content'    => (string) sql_unescape($fields[4]),
		'post_title'      => (string) sql_unescape($fields[5]),
		'post_excerpt'    => (string) sql_unescape($fields[6]),
		'post_status'     => (string) sql_unescape($fields[7]),
		'comment_status'  => (string) sql_unescape($fields[8]),
		'ping_status'     => (string) sql_unescape($fields[9]),
		'post_password'   => (string) sql_unescape($fields[10]),
		'post_name'       => $postSlug,
		'to_ping'         => (string) sql_unescape($fields[12]),
		'pinged'          => (string) sql_unescape($fields[13]),
		'post_modified'   => (string) sql_unescape($fields[14]),
		'post_modified_gmt' => (string) sql_unescape($fields[15]),
		'post_content_filtered' => (string) sql_unescape($fields[16]),
		'post_parent'     => (int) sql_unescape($fields[17]),
		'menu_order'      => (int) sql_unescape($fields[19]),
		'post_mime_type'  => (string) sql_unescape($fields[21]),
		'is_front_page'   => ((string) $postId === (string) $pageOnFront),
		'meta'            => array(),
	);
}

if (empty($targetData)) {
	fwrite(STDERR, "No target pages were found in the dump.\n");
	exit(1);
}

$postmetaStatements = extract_all_insert_values($sql, 'wp_postmeta');
if (empty($postmetaStatements)) {
	fwrite(STDERR, "Could not find wp_postmeta INSERT in dump.\n");
	exit(1);
}

foreach ($postmetaStatements as $postmetaValues) {
	foreach (parse_insert_rows($postmetaValues) as $row) {
		$fields = split_sql_fields($row);
		if (count($fields) < 4) {
			continue;
		}

		$postId = (int) sql_unescape($fields[1]);
		if (! isset($targetIds[$postId])) {
			continue;
		}

		$metaKey = (string) sql_unescape($fields[2]);
		if (in_array($metaKey, $cacheMetaKeys, true)) {
			continue;
		}

		if (! array_key_exists($metaKey, $targetData[$postId]['meta'])) {
			$targetData[$postId]['meta'][$metaKey] = array();
		}

		$targetData[$postId]['meta'][$metaKey][] = sql_unescape($fields[3]);
	}
}

$bundle = array(
	'generated_at' => gmdate(DATE_ATOM),
	'dump_path'    => $dumpPath,
	'options'      => array(
		'show_on_front'     => $showOnFront,
		'page_on_front'     => (string) $pageOnFront,
		'page_for_posts'    => (string) $pageForPosts,
		'avf_events_page_path' => (string) $eventsPagePath,
	),
	'pages'        => array_values($targetData),
);

$outputDir = dirname($outputPath);
if (! is_dir($outputDir) && ! mkdir($outputDir, 0777, true) && ! is_dir($outputDir)) {
	fwrite(STDERR, "Could not create output directory: {$outputDir}\n");
	exit(1);
}

$json = json_encode($bundle, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
if (false === $json) {
	fwrite(STDERR, "Could not encode JSON bundle.\n");
	exit(1);
}

if (false === file_put_contents($outputPath, $json)) {
	fwrite(STDERR, "Could not write bundle: {$outputPath}\n");
	exit(1);
}

echo "Wrote test page bundle: {$outputPath}\n";
echo 'Pages: ' . count($bundle['pages']) . "\n";

function extract_all_insert_values(string $sql, string $table): array {
	$anchor    = 'INSERT INTO `' . $table . '` VALUES ';
	$valuesSet = array();
	$cursor    = 0;
	$length    = strlen($sql);

	while (false !== ($start = strpos($sql, $anchor, $cursor))) {
		$offset   = $start + strlen($anchor);
		$inString = false;
		$escaped  = false;

		for ($i = $offset; $i < $length; $i++) {
			$char = $sql[$i];

			if ($inString) {
				if ($escaped) {
					$escaped = false;
				} elseif ('\\' === $char) {
					$escaped = true;
				} elseif ("'" === $char) {
					$inString = false;
				}
				continue;
			}

			if ("'" === $char) {
				$inString = true;
				continue;
			}

			if (';' === $char) {
				$valuesSet[] = substr($sql, $offset, $i - $offset);
				$cursor      = $i + 1;
				continue 2;
			}
		}

		break;
	}

	return $valuesSet;
}

function parse_insert_rows(string $values): array {
	$rows     = array();
	$length   = strlen($values);
	$start    = null;
	$depth    = 0;
	$inString = false;
	$escaped  = false;

	for ($i = 0; $i < $length; $i++) {
		$char = $values[$i];

		if (null === $start) {
			if ('(' === $char) {
				$start    = $i + 1;
				$depth    = 1;
				$inString = false;
				$escaped  = false;
			}
			continue;
		}

		if ($inString) {
			if ($escaped) {
				$escaped = false;
			} elseif ('\\' === $char) {
				$escaped = true;
			} elseif ("'" === $char) {
				$inString = false;
			}
			continue;
		}

		if ("'" === $char) {
			$inString = true;
			continue;
		}

		if ('(' === $char) {
			$depth++;
			continue;
		}

		if (')' === $char) {
			$depth--;
			if (0 === $depth) {
				$rows[] = substr($values, $start, $i - $start);
				$start  = null;
			}
		}
	}

	return $rows;
}

function split_sql_fields(string $row): array {
	$fields   = array();
	$buffer   = '';
	$length   = strlen($row);
	$inString = false;
	$escaped  = false;

	for ($i = 0; $i < $length; $i++) {
		$char = $row[$i];

		if ($inString) {
			$buffer .= $char;
			if ($escaped) {
				$escaped = false;
			} elseif ('\\' === $char) {
				$escaped = true;
			} elseif ("'" === $char) {
				$inString = false;
			}
			continue;
		}

		if ("'" === $char) {
			$inString = true;
			$buffer  .= $char;
			continue;
		}

		if (',' === $char) {
			$fields[] = $buffer;
			$buffer   = '';
			continue;
		}

		$buffer .= $char;
	}

	$fields[] = $buffer;
	return $fields;
}

function sql_unescape(string $value) {
	$value = trim($value);
	if ('NULL' === strtoupper($value)) {
		return null;
	}

	if (strlen($value) >= 2 && "'" === $value[0] && "'" === $value[strlen($value) - 1]) {
		$value = substr($value, 1, -1);
		$value = preg_replace_callback(
			'/\\\\(.)/s',
			static function (array $matches): string {
				switch ($matches[1]) {
					case '0':
						return "\0";
					case 'n':
						return "\n";
					case 'r':
						return "\r";
					case 't':
						return "\t";
					case 'Z':
						return chr(26);
					default:
						return $matches[1];
				}
			},
			$value
		);
	}

	if (is_numeric($value) && (string) (int) $value === $value) {
		return (int) $value;
	}

	return $value;
}

function find_option_value(string $sql, string $optionName): ?string {
	$pattern = "/INSERT INTO `wp_options` VALUES \\([^\\n]*,'" . preg_quote($optionName, '/') . "','((?:\\\\'|[^'])*)','[^']*'\\);/";
	if (! preg_match($pattern, $sql, $matches)) {
		return null;
	}

	return (string) sql_unescape("'" . $matches[1] . "'");
}
