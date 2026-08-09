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

$snapshot_option = 'avf_members_snapshot_v2';
$status_option   = 'avf_members_snapshot_status_v2';

$snapshot_exists_before = get_option( $snapshot_option, null );
$status_exists_before   = get_option( $status_option, null );

function avf_cards_assert( $condition, $message ) {
	if ( ! $condition ) {
		throw new RuntimeException( $message );
	}
}

function avf_cards_test_payload() {
	return array(
		'schema_version' => 2,
		'generated_at'   => '2026-08-06T20:00:00+00:00',
		'member_count'   => 5,
		'content_hash'   => 'not-validated-for-stored-snapshot-tests',
		'section_order'  => array( 'committee', 'salon', 'stall', 'altfroburger', 'af_committee' ),
		'sections'       => array(
			'committee' => array(
				'title'   => 'Komitee',
				'count'   => 1,
				'members' => array(
					array(
						'id'             => 101,
						'display_name'   => 'Philipp ThÃ¼rlemann',
						'first_name'     => 'Philipp',
						'last_name'      => 'ThÃ¼rlemann',
						'vulgo'          => 'Newton',
						'entry_year'     => 2022,
						'entry_semester' => 'HS',
						'entry_display'  => '2022 HS',
						'academic_title' => 'MSc',
						'degree_program' => 'Biotechnology',
						'roles'          => array(
							array(
								'key'        => 'senior',
								'label'      => 'Senior',
								'sort_order' => 10,
							),
						),
						'photo'          => array(
							'available' => false,
							'fallback'  => true,
							'token'     => '',
							'variants'  => array(),
						),
					),
				),
			),
			'salon' => array(
				'title'   => 'Der Salon',
				'count'   => 1,
				'members' => array(
					array(
						'id'             => 201,
						'display_name'   => 'ZoÃ« Ã„ther',
						'first_name'     => 'ZoÃ«',
						'last_name'      => 'Ã„ther',
						'vulgo'          => 'Ã„tna',
						'entry_year'     => null,
						'entry_semester' => '',
						'entry_display'  => '',
						'academic_title' => '',
						'degree_program' => '',
						'roles'          => array(),
						'photo'          => array(
							'available' => false,
							'fallback'  => true,
							'token'     => '',
							'variants'  => array(),
						),
					),
				),
			),
			'stall' => array(
				'title'   => 'Der Stall',
				'count'   => 1,
				'members' => array(
					array(
						'id'             => 301,
						'display_name'   => 'Escaper Test',
						'first_name'     => 'Escaper',
						'last_name'      => 'Test',
						'vulgo'          => '',
						'entry_year'     => 2024,
						'entry_semester' => 'FS',
						'entry_display'  => '2024 FS',
						'academic_title' => '<script>alert(1)</script>',
						'degree_program' => 'Bio & <b>Chemie</b>',
						'roles'          => array(),
						'photo'          => array(
							'available' => false,
							'fallback'  => true,
							'token'     => '',
							'variants'  => array(),
						),
					),
				),
			),
			'altfroburger' => array(
				'title'   => 'Altfroburger',
				'count'   => 1,
				'members' => array(
					array(
						'id'             => 401,
						'display_name'   => 'Alt Beispiel',
						'first_name'     => 'Alt',
						'last_name'      => 'Beispiel',
						'vulgo'          => 'Senioris',
						'entry_year'     => 1998,
						'entry_semester' => 'HS',
						'entry_display'  => '1998 HS',
						'academic_title' => 'Dr. sc.',
						'degree_program' => 'Chemie',
						'roles'          => array(),
						'photo'          => array(
							'available' => false,
							'fallback'  => true,
							'token'     => '',
							'variants'  => array(),
						),
					),
				),
			),
			'af_committee' => array(
				'title'   => 'Das Altfroburger-Komitee',
				'count'   => 1,
				'members' => array(
					array(
						'id'             => 501,
						'display_name'   => 'Anton Froburger',
						'first_name'     => 'Anton',
						'last_name'      => 'Froburger',
						'vulgo'          => 'Asterix',
						'entry_year'     => 1990,
						'entry_semester' => 'FS',
						'entry_display'  => '1990 FS',
						'academic_title' => 'lic. iur.',
						'degree_program' => 'Jus',
						'roles'          => array(
							array(
								'key'        => 'af_praesident',
								'label'      => 'AF-PrÃ¤sident',
								'sort_order' => 130,
							),
						),
						'photo'          => array(
							'available' => false,
							'fallback'  => true,
							'token'     => '',
							'variants'  => array(),
						),
					),
				),
			),
		),
	);
}

try {
	update_option( $snapshot_option, avf_cards_test_payload(), false );
	delete_option( $status_option );

	$committee_html = do_shortcode( "[avf_members_cards section='committee' show_role='1']" );
	$committee_no_role_html = do_shortcode( "[avf_members_cards section='committee' show_role='0']" );
	$salon_html = do_shortcode( "[avf_members_cards section='salon']" );
	$stall_html = do_shortcode( "[avf_members_cards section='stall']" );
	$af_committee_html = do_shortcode( "[avf_members_cards section='af_committee' show_role='1']" );

	avf_cards_assert( false !== strpos( $committee_html, 'data-avf-member-toggle="1"' ), 'Expected details toggle markup for committee.' );
	avf_cards_assert( false !== strpos( $committee_html, 'Mehr Infos' ), 'Expected visible details button label.' );
	avf_cards_assert( false !== strpos( $salon_html, 'data-avf-member-panel="1"' ), 'Expected details panel markup for salon.' );
	avf_cards_assert( false !== strpos( $stall_html, 'Studiengang' ), 'Expected detail labels in details panel.' );
	avf_cards_assert( false !== strpos( $af_committee_html, 'AF-PrÃ¤sident' ), 'Expected AF committee role label.' );
	avf_cards_assert( false !== strpos( $committee_html, 'Senior' ), 'Expected committee role label when show_role=1.' );
	avf_cards_assert( false === strpos( $committee_no_role_html, 'Senior' ), 'Expected committee role label to be hidden when show_role=0.' );
	avf_cards_assert( false !== strpos( $committee_html, 'Philipp ThÃ¼rlemann' ), 'Expected full name in details panel.' );
	avf_cards_assert( false !== strpos( $committee_html, 'v/o Newton' ), 'Expected vulgo in details panel.' );
	avf_cards_assert( false !== strpos( $committee_html, '2022 HS' ), 'Expected entry display in details panel.' );
	avf_cards_assert( false !== strpos( $committee_html, 'MSc' ), 'Expected academic title in details panel.' );
	avf_cards_assert( false !== strpos( $committee_html, 'Biotechnology' ), 'Expected degree program in details panel.' );
	avf_cards_assert( false !== strpos( $salon_html, 'ZoÃ« Ã„ther' ), 'Expected umlauts to survive rendering.' );
	avf_cards_assert( false !== strpos( $salon_html, '>Nicht hinterlegt<' ), 'Expected readable placeholder for missing values.' );
	avf_cards_assert( false === strpos( $committee_html, 'birth_date' ), 'Expected no birth date field in rendered markup.' );
	avf_cards_assert( false === strpos( $committee_html, 'death_date' ), 'Expected no death date field in rendered markup.' );
	avf_cards_assert( false === strpos( $committee_html, 'exit_year' ), 'Expected no exit year field in rendered markup.' );
	avf_cards_assert( false === strpos( $stall_html, '<script>alert(1)</script>' ), 'Expected academic title to be escaped.' );
	avf_cards_assert( false === strpos( $stall_html, '<b>Chemie</b>' ), 'Expected degree program HTML to be escaped.' );
	avf_cards_assert( false !== strpos( $stall_html, '&lt;script&gt;alert(1)&lt;/script&gt;' ), 'Expected escaped academic title output.' );
	avf_cards_assert( false !== strpos( $stall_html, 'Bio &amp; &lt;b&gt;Chemie&lt;/b&gt;' ), 'Expected escaped degree program output.' );
	avf_cards_assert( false !== strpos( $committee_html, 'avf-member-card__placeholder' ), 'Expected cards without image to keep placeholder support.' );

	fwrite( STDOUT, "OK: members cards details shortcode checks passed\n" );
} catch ( Throwable $exception ) {
	fwrite( STDERR, $exception->getMessage() . "\n" );
	exit( 1 );
} finally {
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
}
