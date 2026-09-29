/* Farbaholix contact form: POST /wp-json/fx/v1/contact
   Stores every enquiry as "Anfrage" (wp-admin), mails it and forwards it to WhatsApp via CallMeBot
   (options fx_cmb_phone / fx_cmb_key, editable in Settings → General or via REST settings). */
add_action( 'init', function () {
	register_post_type( 'fx_lead', array(
		'label' => 'Anfragen', 'public' => false, 'show_ui' => true, 'show_in_menu' => true, 'menu_icon' => 'dashicons-email-alt',
		'supports' => array( 'title', 'editor' ), 'capability_type' => 'post', 'map_meta_cap' => true,
	) );
	foreach ( array( 'fx_cmb_phone', 'fx_cmb_key', 'fx_lead_mail' ) as $opt ) {
		register_setting( 'general', $opt, array( 'type' => 'string', 'show_in_rest' => true, 'default' => '', 'sanitize_callback' => 'sanitize_text_field' ) );
	}
} );
add_action( 'rest_api_init', function () {
	register_rest_route( 'fx/v1', '/contact', array( 'methods' => 'POST', 'permission_callback' => '__return_true', 'callback' => 'fx_contact_submit' ) );
} );
function fx_contact_submit( WP_REST_Request $r ) {
	$p = (array) $r->get_json_params();
	if ( ! empty( $p['website'] ) || ( isset( $p['t'] ) && (int) $p['t'] < 2500 ) ) {   // honeypot / filled in under 2.5 s = bot
		return array( 'ok' => true );
	}
	$name    = sanitize_text_field( $p['name'] ?? '' );
	$contact = sanitize_text_field( $p['contact'] ?? '' );
	$msg     = sanitize_textarea_field( $p['message'] ?? '' );
	$page    = esc_url_raw( $p['page'] ?? '' );
	$lang    = sanitize_key( $p['lang'] ?? '' );
	if ( mb_strlen( $contact ) < 5 || mb_strlen( $msg ) < 2 || mb_strlen( $msg ) > 5000 || mb_strlen( $name ) > 120 || mb_strlen( $contact ) > 160 ) {
		return new WP_Error( 'fx_invalid', 'invalid', array( 'status' => 400 ) );
	}
	$ip  = $_SERVER['REMOTE_ADDR'] ?? '';
	$key = 'fx_rl_' . md5( $ip );
	$n   = (int) get_transient( $key );
	if ( $n >= 5 ) {
		return new WP_Error( 'fx_rate', 'rate', array( 'status' => 429 ) );
	}
	set_transient( $key, $n + 1, 15 * MINUTE_IN_SECONDS );
	$text = "Neue Anfrage – farbaholix.de\nName: " . ( $name ?: '–' ) . "\nKontakt: $contact\nSprache: " . strtoupper( $lang ) . "\n\n$msg\n\nSeite: $page";
	wp_insert_post( array( 'post_type' => 'fx_lead', 'post_status' => 'private', 'post_title' => ( $name ?: $contact ) . ' – ' . wp_date( 'd.m.Y H:i' ), 'post_content' => $text ) );
	$to      = get_option( 'fx_lead_mail' ) ?: 'farbaholix@gmail.com';
	$headers = array( 'Content-Type: text/plain; charset=UTF-8' );
	if ( is_email( $contact ) ) {
		$headers[] = 'Reply-To: ' . ( $name ? $name . ' ' : '' ) . '<' . $contact . '>';
	}
	$mailed = wp_mail( $to, 'Neue Anfrage: ' . ( $name ?: $contact ), $text, $headers );
	$wa = false;
	$phone = preg_replace( '/[^0-9+]/', '', (string) get_option( 'fx_cmb_phone' ) );
	$apikey = (string) get_option( 'fx_cmb_key' );
	if ( $phone && $apikey ) {
		$res = wp_remote_get( 'https://api.callmebot.com/whatsapp.php?phone=' . rawurlencode( $phone ) . '&text=' . rawurlencode( $text ) . '&apikey=' . rawurlencode( $apikey ), array( 'timeout' => 12 ) );
		$wa  = ! is_wp_error( $res ) && 200 === wp_remote_retrieve_response_code( $res );
	}
	return array( 'ok' => true, 'mail' => (bool) $mailed, 'wa' => $wa );
}
