<?php
require dirname(__DIR__, 3) . '/public/wp-load.php';
$post = get_page_by_path('mitglieder', OBJECT, 'page');
if (!($post instanceof WP_Post)) {
  fwrite(STDERR, "mitglieder page not found\n");
  exit(1);
}
delete_post_meta($post->ID, '_elementor_element_cache');
delete_post_meta($post->ID, '_elementor_css');
delete_post_meta($post->ID, '_elementor_page_assets');
clean_post_cache($post->ID);
if (class_exists('\Elementor\Plugin')) {
  \Elementor\Plugin::$instance->files_manager->clear_cache();
}
wp_update_post([
  'ID' => $post->ID,
  'post_modified' => current_time('mysql'),
  'post_modified_gmt' => current_time('mysql', true),
]);
echo wp_json_encode([
  'post_id' => $post->ID,
  'path' => get_permalink($post),
  'cleared' => ['_elementor_element_cache','_elementor_css','_elementor_page_assets']
], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT);
