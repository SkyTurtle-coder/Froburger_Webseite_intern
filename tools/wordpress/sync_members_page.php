<?php

if ( $argc < 2 ) {
	fwrite( STDERR, "Usage: php sync_members_page.php <api-base-url>\n" );
	exit( 1 );
}

$api_base = trim( (string) $argv[1] );
if ( '' === $api_base ) {
	fwrite( STDERR, "API base URL is empty.\n" );
	exit( 1 );
}

require dirname( __DIR__, 3 ) . '/public/wp-load.php';

$members_plugin = dirname( __DIR__, 3 ) . '/public/wp-content/mu-plugins/avf-members-page.php';
if ( file_exists( $members_plugin ) && ! class_exists( 'AVF_Members_Page' ) ) {
	require_once $members_plugin;
}

$api_base = trailingslashit( esc_url_raw( $api_base ) );
if ( '' === $api_base ) {
	fwrite( STDERR, "API base URL is invalid.\n" );
	exit( 1 );
}

update_option( 'avf_members_api_base', $api_base, false );

$page = get_page_by_path( 'mitglieder', OBJECT, 'page' );
if ( ! ( $page instanceof WP_Post ) ) {
	fwrite( STDERR, "WordPress page 'mitglieder' was not found.\n" );
	exit( 1 );
}

$layout_before    = (string) get_post_meta( $page->ID, '_elementor_data', true );
$should_bootstrap = false;
$layout_elements  = null;
$recovered_invalid_layout = false;

if ( '' === trim( $layout_before ) ) {
	$should_bootstrap = true;
} elseif ( false === strpos( $layout_before, 'avf-members-layout' ) ) {
	$should_bootstrap = true;
}

if ( ! $should_bootstrap ) {
	$decoded = json_decode( $layout_before, true );
	if ( JSON_ERROR_NONE !== json_last_error() || ! is_array( $decoded ) ) {
		$should_bootstrap        = true;
		$recovered_invalid_layout = true;
	} else {
		$layout_elements = $decoded;
	}
}

if ( $should_bootstrap ) {
	$backup_dir = WP_CONTENT_DIR . '/uploads/avf-backups/members/';
	wp_mkdir_p( $backup_dir );
	$timestamp = current_time( 'Y-m-d_His' );
	file_put_contents( $backup_dir . 'mitglieder-elementor-before-' . $timestamp . '.json', $layout_before );

	$layout_elements = avf_members_bootstrap_layout();
}

update_post_meta( $page->ID, '_elementor_edit_mode', 'builder' );
update_post_meta( $page->ID, '_elementor_template_type', 'wp-page' );
update_post_meta( $page->ID, '_wp_page_template', 'default' );
if ( defined( 'ELEMENTOR_VERSION' ) ) {
	update_post_meta( $page->ID, '_elementor_version', ELEMENTOR_VERSION );
}

$saved = avf_members_save_elementor_document( $page->ID, $layout_elements );
if ( is_wp_error( $saved ) ) {
	fwrite( STDERR, $saved->get_error_message() . "\n" );
	exit( 1 );
}

avf_members_regenerate_elementor_css( $page->ID );

if ( class_exists( 'AVF_Members_Page' ) ) {
	$refresh = AVF_Members_Page::refresh_snapshot( 'cli' );
	if ( is_wp_error( $refresh ) ) {
		fwrite( STDERR, 'Members snapshot refresh failed: ' . $refresh->get_error_message() . "\n" );
		exit( 1 );
	}
}

echo "Members API configured: {$api_base}\n";
if ( $should_bootstrap ) {
	echo "Members page layout bootstrapped with editable Elementor modules.\n";
	if ( $recovered_invalid_layout ) {
		echo "Invalid stored Elementor JSON was backed up and replaced with a clean layout.\n";
	}
} else {
	echo "Members page layout re-saved through Elementor for consistent frontend output.\n";
}

function avf_members_bootstrap_id( $semantic_id ) {
	return substr( md5( 'avf-members-layout:v4:' . $semantic_id ), 0, 7 );
}

function avf_members_bootstrap_container( $semantic_id, array $children, $title, $css_classes = '' ) {
	$settings = array();
	if ( '' !== $css_classes ) {
		$settings['_css_classes'] = $css_classes;
	}

	return array(
		'id'              => avf_members_bootstrap_id( $semantic_id ),
		'elType'          => 'e-flexbox',
		'settings'        => $settings,
		'elements'        => $children,
		'isInner'         => false,
		'styles'          => array(),
		'interactions'    => array(),
		'editor_settings' => array( 'title' => $title ),
		'version'         => '0.0',
	);
}

function avf_members_bootstrap_text( $semantic_id, $html, $css_classes ) {
	return array(
		'id'         => avf_members_bootstrap_id( $semantic_id ),
		'elType'     => 'widget',
		'settings'   => array(
			'editor'       => $html,
			'_css_classes' => $css_classes,
		),
		'elements'   => array(),
		'widgetType' => 'text-editor',
	);
}

function avf_members_bootstrap_heading( $semantic_id, $title, $css_classes, $size = 'h2' ) {
	return array(
		'id'         => avf_members_bootstrap_id( $semantic_id ),
		'elType'     => 'widget',
		'settings'   => array(
			'title'        => $title,
			'header_size'  => $size,
			'_css_classes' => $css_classes,
		),
		'elements'   => array(),
		'widgetType' => 'heading',
	);
}

function avf_members_bootstrap_shortcode( $semantic_id, $shortcode, $css_classes = '' ) {
	$settings = array(
		'shortcode' => $shortcode,
	);
	if ( '' !== $css_classes ) {
		$settings['_css_classes'] = $css_classes;
	}

	return array(
		'id'         => avf_members_bootstrap_id( $semantic_id ),
		'elType'     => 'widget',
		'settings'   => $settings,
		'elements'   => array(),
		'widgetType' => 'shortcode',
	);
}

function avf_members_bootstrap_button( $semantic_id, $text, $url, $css_classes = '' ) {
	return array(
		'id'         => avf_members_bootstrap_id( $semantic_id ),
		'elType'     => 'widget',
		'settings'   => array(
			'text'         => $text,
			'link'         => array(
				'url'               => $url,
				'is_external'       => '',
				'nofollow'          => '',
				'custom_attributes' => '',
			),
			'_css_classes' => $css_classes,
		),
		'elements'   => array(),
		'widgetType' => 'button',
	);
}

function avf_members_bootstrap_section( $key, $eyebrow, $title, $intro, $cards_shortcode ) {
	return avf_members_bootstrap_container(
		'section-' . $key,
		array(
			avf_members_bootstrap_container(
				'section-' . $key . '-heading',
				array(
					avf_members_bootstrap_container(
						'section-' . $key . '-copy',
						array(
							avf_members_bootstrap_text(
								'section-' . $key . '-eyebrow',
								'<p>' . esc_html( $eyebrow ) . '</p>',
								'avf-members-eyebrow'
							),
							avf_members_bootstrap_heading(
								'section-' . $key . '-title',
								$title,
								'avf-members-section__title'
							),
							avf_members_bootstrap_text(
								'section-' . $key . '-intro',
								'<p>' . esc_html( $intro ) . '</p>',
								'avf-members-section__intro'
							),
						),
						$title . ' Copy',
						'avf-members-section__copy'
					),
					avf_members_bootstrap_shortcode(
						'section-' . $key . '-count',
						"[avf_members_count section='{$key}']",
						'avf-members-section__count-widget'
					),
				),
				$title . ' Heading',
				'avf-members-section__heading'
			),
			avf_members_bootstrap_shortcode(
				'section-' . $key . '-cards',
				$cards_shortcode,
				'avf-members-section__cards-widget'
			),
		),
		$title,
		'avf-members-section avf-members-section--' . str_replace( '_', '-', $key )
	);
}

function avf_members_bootstrap_layout() {
	return array(
		avf_members_bootstrap_container(
			'root',
			array(
				avf_members_bootstrap_section(
					'committee',
					'Leitung',
					'Komitee',
					'Das Komitee fuehrt die Aktivitas und traegt die Verantwortung fuer das laufende Semester.',
					"[avf_members_cards section='committee' show_role='1']"
				),
				avf_members_bootstrap_section(
					'salon',
					'Burschenschaft',
					'Der Salon',
					'Hier erscheinen alle Burschen mit Portrait, Namen und Vulgo aus dem Django-Backend.',
					"[avf_members_cards section='salon']"
				),
				avf_members_bootstrap_section(
					'stall',
					'Fuxenstand',
					'Der Stall',
					'Hier erscheinen alle Fuxen mit Portrait, Namen und Vulgo aus dem Django-Backend.',
					"[avf_members_cards section='stall']"
				),
				avf_members_bootstrap_section(
					'altfroburger',
					'Altfroburger',
					'Altfroburger',
					'Hier erscheinen alle Profile mit der Rolle Altfroburger.',
					"[avf_members_cards section='altfroburger']"
				),
				avf_members_bootstrap_section(
					'af_committee',
					'AF-Komitee',
					'Das Altfroburger-Komitee',
					'Hier erscheinen alle Profile mit der Rolle AF-Komitee.',
					"[avf_members_cards section='af_committee' show_role='1']"
				),
				avf_members_bootstrap_container(
					'cta',
					array(
						avf_members_bootstrap_container(
							'cta-copy',
							array(
								avf_members_bootstrap_text( 'cta-eyebrow', '<p>Interesse?</p>', 'avf-members-eyebrow' ),
								avf_members_bootstrap_heading( 'cta-title', 'Mitglied werden', 'avf-members-cta__title' ),
								avf_members_bootstrap_text(
									'cta-text',
									'<p>Wer die AV Froburger kennenlernen moechte, kann direkt Kontakt aufnehmen oder zuerst unsere Veranstaltungen ansehen.</p>',
									'avf-members-cta__text'
								),
							),
							'CTA Copy',
							'avf-members-cta__copy'
						),
						avf_members_bootstrap_container(
							'cta-actions',
							array(
								avf_members_bootstrap_button( 'cta-contact', 'Kontakt aufnehmen', home_url( '/kontakt/' ) ),
								avf_members_bootstrap_button( 'cta-events', 'Veranstaltungen ansehen', home_url( '/veranstaltungen/' ) ),
							),
							'CTA Actions',
							'avf-members-cta__actions'
						),
					),
					'Mitglied werden',
					'avf-members-cta'
				),
			),
			'Mitgliederseite',
			'avf-has-zirkel-bg avf-members-layout'
		),
	);
}

function avf_members_get_acting_admin_user_id() {
	$admins = get_users(
		array(
			'role'    => 'administrator',
			'number'  => 1,
			'orderby' => 'ID',
			'order'   => 'ASC',
			'fields'  => 'ID',
		)
	);

	return ! empty( $admins ) ? (int) $admins[0] : 0;
}

function avf_members_save_elementor_document( $post_id, array $elements ) {
	if ( ! class_exists( '\Elementor\Plugin' ) ) {
		return new WP_Error( 'avf_members_no_elementor', 'Elementor is not loaded.' );
	}

	$encoded = wp_json_encode( $elements );
	if ( false === $encoded ) {
		return new WP_Error( 'avf_members_encode_failed', 'Could not encode the Elementor members layout.' );
	}

	$roundtrip = json_decode( $encoded, true );
	if ( JSON_ERROR_NONE !== json_last_error() || ! is_array( $roundtrip ) ) {
		return new WP_Error( 'avf_members_validate_failed', 'The Elementor members layout failed JSON validation.' );
	}

	$restore_user = get_current_user_id();
	$acting_user  = avf_members_get_acting_admin_user_id();
	if ( $acting_user ) {
		wp_set_current_user( $acting_user );
	}

	$document = \Elementor\Plugin::$instance->documents->get( $post_id );
	$saved    = $document ? $document->save( array( 'elements' => $elements ) ) : false;

	if ( $acting_user ) {
		wp_set_current_user( $restore_user );
	}

	if ( ! $saved ) {
		return new WP_Error( 'avf_members_save_failed', 'Elementor Document::save() returned false for the members page.' );
	}

	return true;
}

function avf_members_regenerate_elementor_css( $post_id ) {
	if ( class_exists( '\Elementor\Core\Files\CSS\Post' ) ) {
		$post_css = \Elementor\Core\Files\CSS\Post::create( $post_id );
		$post_css->delete();
	}

	if ( class_exists( '\Elementor\Plugin' ) && isset( \Elementor\Plugin::$instance->files_manager ) ) {
		\Elementor\Plugin::$instance->files_manager->clear_cache();
	}
}
