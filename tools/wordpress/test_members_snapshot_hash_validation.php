<?php

require dirname(__DIR__, 3) . '/public/wp-load.php';

$plugin = dirname(__DIR__, 3) . '/public/wp-content/mu-plugins/avf-members-page.php';
if ( file_exists( $plugin ) && ! class_exists( 'AVF_Members_Page' ) ) {
	require_once $plugin;
}

if ( ! class_exists( 'AVF_Members_Page' ) ) {
	fwrite( STDERR, "AVF_Members_Page not loaded\n" );
	exit( 1 );
}

$class = new ReflectionClass( 'AVF_Members_Page' );
$normalize_payload = $class->getMethod( 'normalize_remote_payload' );
$normalize_payload->setAccessible( true );
$hash_matches = $class->getMethod( 'hash_matches' );
$hash_matches->setAccessible( true );

$snapshot_option = 'avf_members_snapshot_v2';
$status_option   = 'avf_members_snapshot_status_v2';
$lock_transient  = 'avf_members_refresh_lock_v1';

$snapshot_exists_before = get_option( $snapshot_option, null );
$status_exists_before   = get_option( $status_option, null );
$lock_exists_before     = get_transient( $lock_transient );

$tests = array();

function avf_members_assert( $condition, $message ) {
	if ( ! $condition ) {
		throw new RuntimeException( $message );
	}
}

function avf_members_test_payload() {
	$sections = array(
		'committee'     => avf_members_make_section( 'committee', 'Komitee', 5, 100 ),
		'salon'         => avf_members_make_section( 'salon', 'Der Salon', 13, 200 ),
		'stall'         => avf_members_make_section( 'stall', 'Der Stall', 4, 300 ),
		'altfroburger'  => avf_members_make_section( 'altfroburger', 'Altfroburger', 3, 400 ),
		'af_committee'  => avf_members_make_section( 'af_committee', 'Das Altfroburger-Komitee', 3, 500 ),
	);

	$payload = array(
		'schema_version' => 2,
		'generated_at'   => '2026-08-04T12:00:00+00:00',
		'member_count'   => 20,
		'section_order'  => array( 'committee', 'salon', 'stall', 'altfroburger', 'af_committee' ),
		'sections'       => $sections,
	);
	$payload['content_hash'] = avf_members_django_hash( $payload );

	return $payload;
}

function avf_members_make_section( $key, $title, $count, $base_id ) {
	$members = array();
	for ( $index = 0; $index < $count; $index++ ) {
		$member_id = $base_id + $index + 1;
		$with_photo = in_array( $key, array( 'committee', 'salon' ), true ) && $index === 0;
		$members[] = array(
			'id'           => $member_id,
			'display_name' => ucfirst( str_replace( '_', ' ', $key ) ) . ' Mitglied ' . ( $index + 1 ),
			'name'         => ucfirst( str_replace( '_', ' ', $key ) ) . ' Mitglied ' . ( $index + 1 ),
			'first_name'   => ucfirst( $key ) . ( $index + 1 ),
			'last_name'    => 'Tester',
			'vulgo'        => strtoupper( substr( $key, 0, 2 ) ) . ( $index + 1 ),
			'entry_year'   => 2020 + $index,
			'entry_semester' => 0 === $index % 2 ? 'FS' : 'HS',
			'entry_display'  => ( 2020 + $index ) . ' ' . ( 0 === $index % 2 ? 'FS' : 'HS' ),
			'academic_title' => 0 === $index ? 'MSc' : '',
			'degree_program' => 0 === $index ? 'Biotechnology' : '',
			'roles'        => array(
				array(
					'key'        => $key . '_role',
					'label'      => ucfirst( str_replace( '_', ' ', $key ) ) . ' Rolle',
					'sort_order' => 10 + $index,
				),
			),
			'photo'        => array(
				'fallback' => ! $with_photo,
				'variants' => $with_photo
					? array(
						'small' => array(
							'url'    => 'https://intern-avfroburger.ch/media/public/members/' . $member_id . '/small.webp',
							'width'  => 160,
							'height' => 160,
						),
					)
					: array(),
			),
		);
	}

	return array(
		'title'   => $title,
		'count'   => $count,
		'members' => $members,
	);
}

function avf_members_django_hash( array $payload ) {
	$sections = array();
	foreach ( $payload['section_order'] as $section_key ) {
		$section = $payload['sections'][ $section_key ];
		$sections[ $section_key ] = array(
			'title'   => $section['title'],
			'count'   => $section['count'],
			'members' => array_map(
				static function ( $member ) {
					return array(
						'id'           => $member['id'],
						'display_name' => $member['display_name'],
						'first_name'   => $member['first_name'],
						'last_name'    => $member['last_name'],
						'vulgo'        => $member['vulgo'],
						'entry_year'   => $member['entry_year'],
						'entry_semester' => $member['entry_semester'],
						'entry_display'  => $member['entry_display'],
						'academic_title' => $member['academic_title'],
						'degree_program' => $member['degree_program'],
						'roles'        => $member['roles'],
						'photo'        => array(
							'fallback' => $member['photo']['fallback'],
							'variants' => empty( $member['photo']['variants'] ) ? array() : $member['photo']['variants'],
						),
					);
				},
				$section['members']
			),
		);
	}

	$hash_payload = array(
		'schema_version' => $payload['schema_version'],
		'member_count'   => $payload['member_count'],
		'section_order'  => $payload['section_order'],
		'sections'       => $sections,
	);

	$canonical = avf_members_canonicalize( $hash_payload );
	$raw       = wp_json_encode( $canonical, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES );
	if ( false === $raw ) {
		throw new RuntimeException( 'Unable to encode canonical hash payload.' );
	}

	return hash( 'sha256', $raw );
}

function avf_members_canonicalize( $value ) {
	if ( ! is_array( $value ) ) {
		return $value;
	}

	if ( array_values( $value ) === $value ) {
		return array_map( 'avf_members_canonicalize', $value );
	}

	$result = array();
	foreach ( $value as $key => $item ) {
		$result[ $key ] = avf_members_canonicalize( $item );
	}
	ksort( $result );
	return $result;
}

function avf_members_http_stub( $response, $args, $url ) {
	$payload = $GLOBALS['avf_members_http_payload'];

	if ( false !== strpos( $url, '/healthz/' ) ) {
		return array(
			'headers'  => array(),
			'body'     => '{}',
			'response' => array(
				'code'    => 200,
				'message' => 'OK',
			),
			'cookies'  => array(),
		);
	}

	if ( false !== strpos( $url, '/api/v1/public/members/' ) ) {
		return array(
			'headers'  => array( 'content-type' => 'application/json' ),
			'body'     => wp_json_encode( $payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES ),
			'response' => array(
				'code'    => 200,
				'message' => 'OK',
			),
			'cookies'  => array(),
		);
	}

	return $response;
}

function avf_members_run_test( &$tests, $name, callable $callback ) {
	try {
		$callback();
		$tests[] = array( 'name' => $name, 'status' => 'passed' );
	} catch ( Throwable $exception ) {
		$tests[] = array(
			'name'    => $name,
			'status'  => 'failed',
			'message' => $exception->getMessage(),
		);
	}
}

try {
	$valid_payload = avf_members_test_payload();

	avf_members_run_test(
		$tests,
		'unveraenderter_rohpayload_mit_korrektem_hash',
		static function () use ( $normalize_payload, $valid_payload ) {
			$result = $normalize_payload->invoke( null, $valid_payload );
			avf_members_assert( is_array( $result ), 'Expected normalized payload array.' );
			avf_members_assert( 20 === (int) $result['member_count'], 'Expected member_count 20.' );
		}
	);

	avf_members_run_test(
		$tests,
		'photo_path_ignoriert',
		static function () use ( $hash_matches, $valid_payload ) {
			$payload = $valid_payload;
			$payload['sections']['committee']['members'][0]['photo']['variants']['small']['path'] = '/media/public/members/101/small.webp';
			$ok = $hash_matches->invoke( null, $payload, $payload['content_hash'] );
			avf_members_assert( true === $ok, 'Expected hash to ignore photo.path.' );
		}
	);

	avf_members_run_test(
		$tests,
		'normalize_member_standardwerte_beeinflussen_hash_nicht',
		static function () use ( $normalize_payload, $valid_payload ) {
			$payload = $valid_payload;
			$payload['sections']['committee']['members'][0]['name']       = 'Abweichender Anzeigename Rohfeld';
			$payload['sections']['committee']['members'][0]['legacy_only'] = 'Ignoriert';
			$result = $normalize_payload->invoke( null, $payload );
			avf_members_assert( is_array( $result ), 'Expected payload to remain valid with non-hash raw fields.' );
		}
	);

	avf_members_run_test(
		$tests,
		'display_name_aenderung_wird_abgelehnt',
		static function () use ( $normalize_payload, $valid_payload ) {
			$payload = $valid_payload;
			$payload['sections']['committee']['members'][0]['display_name'] = 'Manipuliert';
			$result = $normalize_payload->invoke( null, $payload );
			avf_members_assert( is_wp_error( $result ) && 'avf_members_hash_mismatch' === $result->get_error_code(), 'Expected display_name manipulation to fail.' );
		}
	);

	avf_members_run_test(
		$tests,
		'rollen_aenderung_wird_abgelehnt',
		static function () use ( $normalize_payload, $valid_payload ) {
			$payload = $valid_payload;
			$payload['sections']['committee']['members'][0]['roles'][0]['label'] = 'Manipulierte Rolle';
			$result = $normalize_payload->invoke( null, $payload );
			avf_members_assert( is_wp_error( $result ) && 'avf_members_hash_mismatch' === $result->get_error_code(), 'Expected role manipulation to fail.' );
		}
	);

	avf_members_run_test(
		$tests,
		'foto_url_aenderung_wird_abgelehnt',
		static function () use ( $normalize_payload, $valid_payload ) {
			$payload = $valid_payload;
			$payload['sections']['committee']['members'][0]['photo']['variants']['small']['url'] = 'https://example.invalid/changed.webp';
			$result = $normalize_payload->invoke( null, $payload );
			avf_members_assert( is_wp_error( $result ) && 'avf_members_hash_mismatch' === $result->get_error_code(), 'Expected photo URL manipulation to fail.' );
		}
	);

	avf_members_run_test(
		$tests,
		'mitgliederzahl_aenderung_wird_abgelehnt',
		static function () use ( $normalize_payload, $valid_payload ) {
			$payload = $valid_payload;
			$payload['member_count'] = 19;
			$result = $normalize_payload->invoke( null, $payload );
			avf_members_assert( is_wp_error( $result ) && 'avf_members_hash_mismatch' === $result->get_error_code(), 'Expected member_count manipulation to fail.' );
		}
	);

	avf_members_run_test(
		$tests,
		'fehlender_content_hash_wird_abgelehnt',
		static function () use ( $normalize_payload, $valid_payload ) {
			$payload = $valid_payload;
			unset( $payload['content_hash'] );
			$result = $normalize_payload->invoke( null, $payload );
			avf_members_assert( is_wp_error( $result ) && 'avf_members_hash_mismatch' === $result->get_error_code(), 'Expected missing hash to fail.' );
		}
	);

	avf_members_run_test(
		$tests,
		'ungueltiges_hashformat_wird_abgelehnt',
		static function () use ( $normalize_payload, $valid_payload ) {
			$payload = $valid_payload;
			$payload['content_hash'] = 'invalid';
			$result = $normalize_payload->invoke( null, $payload );
			avf_members_assert( is_wp_error( $result ) && 'avf_members_hash_mismatch' === $result->get_error_code(), 'Expected invalid hash format to fail.' );
		}
	);

	avf_members_run_test(
		$tests,
		'normalisierter_payload_bleibt_mit_hashfehler_ungueltig',
		static function () use ( $normalize_payload, $valid_payload ) {
			$payload = $valid_payload;
			$payload['sections']['committee']['members'][0]['display_name'] = 'Manipuliert';
			$result = $normalize_payload->invoke( null, $payload );
			avf_members_assert( is_wp_error( $result ) && 'avf_members_hash_mismatch' === $result->get_error_code(), 'Expected normalized payload hash mismatch.' );
		}
	);

	avf_members_run_test(
		$tests,
		'normalisierter_payload_enthaelt_member_count_20',
		static function () use ( $normalize_payload, $valid_payload ) {
			$result = $normalize_payload->invoke( null, $valid_payload );
			avf_members_assert( is_array( $result ), 'Expected normalized payload array.' );
			avf_members_assert( 20 === (int) $result['member_count'], 'Expected normalized member_count 20.' );
		}
	);
} finally {
	unset( $GLOBALS['avf_members_http_payload'] );
	delete_transient( $lock_transient );

	if ( null === $snapshot_exists_before ) {
		delete_option( $snapshot_option );
	} else {
		update_option( $snapshot_option, $snapshot_exists_before, false );
	}

	if ( null === $status_exists_before ) {
		delete_option( $status_option );
	} else {
		update_option( $status_option, $status_exists_before, false );
	}

	if ( false !== $lock_exists_before ) {
		set_transient( $lock_transient, $lock_exists_before, MINUTE_IN_SECONDS );
	}
}

$failed = array_values(
	array_filter(
		$tests,
		static function ( $test ) {
			return 'failed' === $test['status'];
		}
	)
);

echo wp_json_encode(
	array(
		'total'  => count( $tests ),
		'failed' => count( $failed ),
		'tests'  => $tests,
	),
	JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT
);
echo PHP_EOL;

exit( empty( $failed ) ? 0 : 1 );
