/* Farbaholix contact hub (WPCode snippet 918, source: farbaholix-site/wp-snippets/fx-contact.php)
   - POST /wp-json/fx/v1/contact     website form → "Anfrage" (wp-admin) + e-mail + WhatsApp (CallMeBot) + Telegram
   - GET/POST /wp-json/fx/v1/thread   the visitor's conversation on the website (token from /contact)
   - POST /wp-json/fx/v1/tg/<secret>  Telegram webhook: Slavik answers with "reply" → website / e-mail / Telegram visitor;
                                      visitors who write to the bot are forwarded to Slavik (and to WhatsApp + e-mail)
   - POST /wp-json/fx/v1/tg-setup     admin only: save bot token, find Slavik's chat, set the webhook
   Options: fx_cmb_phone, fx_cmb_key, fx_lead_mail, fx_tg_token, fx_tg_chat, fx_tg_bot, fx_tg_secret */
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
	register_rest_route( 'fx/v1', '/thread', array(
		array( 'methods' => 'GET', 'permission_callback' => '__return_true', 'callback' => 'fx_thread_get' ),
		array( 'methods' => 'POST', 'permission_callback' => '__return_true', 'callback' => 'fx_thread_post' ),
	) );
	register_rest_route( 'fx/v1', '/tg/(?P<s>[A-Za-z0-9]{20,64})', array( 'methods' => 'POST', 'permission_callback' => '__return_true', 'callback' => 'fx_tg_webhook' ) );
	register_rest_route( 'fx/v1', '/tg-setup', array( 'methods' => 'POST', 'permission_callback' => function () { return current_user_can( 'manage_options' ); }, 'callback' => 'fx_tg_setup' ) );
} );

/* ---------- helpers ---------- */
function fx_rate( $key, $max, $sec ) {
	$k = 'fx_rl_' . md5( $key );
	$n = (int) get_transient( $k );
	if ( $n >= $max ) {
		return false;
	}
	set_transient( $k, $n + 1, $sec );
	return true;
}
function fx_tg( $method, $args ) {
	$tok = (string) get_option( 'fx_tg_token' );
	if ( ! $tok ) {
		return null;
	}
	$res = wp_remote_post( 'https://api.telegram.org/bot' . $tok . '/' . $method, array( 'timeout' => 12, 'headers' => array( 'Content-Type' => 'application/json' ), 'body' => wp_json_encode( $args ) ) );
	if ( is_wp_error( $res ) ) {
		return null;
	}
	$j = json_decode( wp_remote_retrieve_body( $res ), true );
	return ! empty( $j['ok'] ) ? $j['result'] : null;
}
function fx_lead_by( $key, $value ) {
	$ids = get_posts( array( 'post_type' => 'fx_lead', 'post_status' => 'any', 'meta_key' => $key, 'meta_value' => (string) $value, 'fields' => 'ids', 'posts_per_page' => 1, 'orderby' => 'date', 'order' => 'DESC' ) );
	return $ids ? (int) $ids[0] : 0;
}
function fx_thread_add( $id, $who, $text ) {
	$th = get_post_meta( $id, 'fx_thread', true );
	$th = is_array( $th ) ? $th : array();
	$th[] = array( 'w' => $who, 'x' => $text, 't' => time() );
	update_post_meta( $id, 'fx_thread', array_slice( $th, -200 ) );
	wp_update_post( array( 'ID' => $id, 'post_content' => get_post_field( 'post_content', $id ) . "\n\n[" . wp_date( 'd.m.Y H:i' ) . '] ' . ( 's' === $who ? 'Slavik' : 'Kunde' ) . ":\n" . $text ) );
}
/* one message to Slavik on every channel: e-mail, WhatsApp (CallMeBot), Telegram (the Telegram message is linked to the lead for replies) */
function fx_notify( $id, $subject, $text, $reply_to = '' ) {
	$out     = array( 'mail' => false, 'wa' => false, 'tg' => false );
	$headers = array( 'Content-Type: text/plain; charset=UTF-8' );
	if ( $reply_to ) {
		$headers[] = 'Reply-To: ' . $reply_to;
	}
	$out['mail'] = (bool) wp_mail( get_option( 'fx_lead_mail' ) ?: 'farbaholix@gmail.com', $subject, $text, $headers );
	$phone       = preg_replace( '/[^0-9+]/', '', (string) get_option( 'fx_cmb_phone' ) );
	$apikey      = (string) get_option( 'fx_cmb_key' );
	if ( $phone && $apikey ) {
		$res       = wp_remote_get( 'https://api.callmebot.com/whatsapp.php?phone=' . rawurlencode( $phone ) . '&text=' . rawurlencode( mb_substr( $text, 0, 1500 ) ) . '&apikey=' . rawurlencode( $apikey ), array( 'timeout' => 12 ) );
		$out['wa'] = ! is_wp_error( $res ) && 200 === wp_remote_retrieve_response_code( $res );
	}
	$chat = (string) get_option( 'fx_tg_chat' );
	if ( $chat ) {
		$m = fx_tg( 'sendMessage', array( 'chat_id' => $chat, 'text' => mb_substr( $text, 0, 3900 ) . "\n\n↩️ Ответь реплаем на это сообщение – клиент получит ответ.", 'disable_web_page_preview' => true ) );
		if ( $m ) {
			add_post_meta( $id, 'fx_tg_mid', (string) $m['message_id'] );
			$out['tg'] = true;
		}
	}
	return $out;
}
function fx_live() {
	return (bool) ( get_option( 'fx_tg_token' ) && get_option( 'fx_tg_chat' ) );
}

/* ---------- website form ---------- */
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
	if ( ! fx_rate( 'ip' . ( $_SERVER['REMOTE_ADDR'] ?? '' ), 5, 15 * MINUTE_IN_SECONDS ) ) {
		return new WP_Error( 'fx_rate', 'rate', array( 'status' => 429 ) );
	}
	$text  = "Neue Anfrage – farbaholix.de\nName: " . ( $name ?: '–' ) . "\nKontakt: $contact\nSprache: " . strtoupper( $lang ) . "\n\n$msg\n\nSeite: $page";
	$id    = wp_insert_post( array( 'post_type' => 'fx_lead', 'post_status' => 'private', 'post_title' => ( $name ?: $contact ) . ' – ' . wp_date( 'd.m.Y H:i' ), 'post_content' => $text ) );
	$token = wp_generate_password( 32, false, false );
	foreach ( array( 'fx_src' => 'web', 'fx_token' => $token, 'fx_name' => $name, 'fx_contact' => $contact, 'fx_lang' => $lang, 'fx_page' => $page ) as $k => $v ) {
		update_post_meta( $id, $k, $v );
	}
	update_post_meta( $id, 'fx_thread', array( array( 'w' => 'v', 'x' => $msg, 't' => time() ) ) );
	$sent = fx_notify( $id, 'Neue Anfrage: ' . ( $name ?: $contact ), "📩 Anfrage #$id (Website)\n" . $text, is_email( $contact ) ? ( $name ? $name . ' ' : '' ) . '<' . $contact . '>' : '' );
	return array_merge( array( 'ok' => true, 'token' => $token, 'live' => fx_live() ), $sent );
}

/* ---------- the visitor's conversation on the website ---------- */
function fx_thread_lead( $t ) {
	return preg_match( '/^[A-Za-z0-9]{32}$/', (string) $t ) ? fx_lead_by( 'fx_token', $t ) : 0;
}
function fx_thread_get( WP_REST_Request $r ) {
	nocache_headers();
	$id = fx_thread_lead( $r->get_param( 't' ) );
	if ( ! $id ) {
		return new WP_Error( 'fx_none', 'none', array( 'status' => 404 ) );
	}
	$th = get_post_meta( $id, 'fx_thread', true );
	return array( 'ok' => true, 'live' => fx_live(), 'msgs' => is_array( $th ) ? $th : array() );
}
function fx_thread_post( WP_REST_Request $r ) {
	$p   = (array) $r->get_json_params();
	$id  = fx_thread_lead( $p['t'] ?? '' );
	$msg = sanitize_textarea_field( $p['message'] ?? '' );
	if ( ! $id || mb_strlen( $msg ) < 1 || mb_strlen( $msg ) > 3000 ) {
		return new WP_Error( 'fx_invalid', 'invalid', array( 'status' => 400 ) );
	}
	if ( ! fx_rate( 'th' . $id, 20, HOUR_IN_SECONDS ) ) {
		return new WP_Error( 'fx_rate', 'rate', array( 'status' => 429 ) );
	}
	fx_thread_add( $id, 'v', $msg );
	$name    = get_post_meta( $id, 'fx_name', true );
	$contact = get_post_meta( $id, 'fx_contact', true );
	fx_notify( $id, 'Neue Nachricht: ' . ( $name ?: $contact ), "💬 Nachricht zu Anfrage #$id (Website)\nVon: " . ( $name ?: '–' ) . " · $contact\n\n$msg", is_email( $contact ) ? '<' . $contact . '>' : '' );
	$th = get_post_meta( $id, 'fx_thread', true );
	return array( 'ok' => true, 'msgs' => $th );
}

/* ---------- Telegram ---------- */
function fx_tg_texts( $lang ) {
	$l = in_array( $lang, array( 'uk', 'ru' ), true ) ? 'uk' : ( 'de' === $lang ? 'de' : 'en' );
	$t = array(
		'de' => array( 'hi' => "Hallo! 👋 Hier schreiben Sie direkt an Slavik von Farbaholix – Graffiti und Wandgestaltung in Frankfurt.\n\nWorum geht es? Wand, Ort, Größe, Idee – gern auch mit Fotos.", 'ack' => 'Danke! Ihre Nachricht ist angekommen – Slavik antwortet hier persönlich, meist noch am selben Tag.' ),
		'en' => array( 'hi' => "Hi! 👋 This chat goes straight to Slavik from Farbaholix – graffiti and murals in Frankfurt.\n\nWhat's it about? Wall, place, size, idea – photos are welcome.", 'ack' => 'Thank you! Your message has arrived – Slavik will answer here personally, usually the same day.' ),
		'uk' => array( 'hi' => "Привіт! 👋 Тут ви пишете напряму Славіку з Farbaholix – графіті та розписи стін у Франкфурті.\n\nПро що йдеться? Стіна, місце, розмір, ідея – можна з фото.", 'ack' => 'Дякую! Повідомлення надійшло – Славік відповість тут особисто, зазвичай того ж дня.' ),
	);
	return $t[ $l ];
}
function fx_tg_webhook( WP_REST_Request $r ) {
	$secret = (string) get_option( 'fx_tg_secret' );
	if ( ! $secret || ! hash_equals( $secret, (string) $r['s'] ) || ! hash_equals( $secret, (string) $r->get_header( 'x_telegram_bot_api_secret_token' ) ) ) {
		return new WP_Error( 'fx_forbidden', 'forbidden', array( 'status' => 403 ) );
	}
	$u = (array) $r->get_json_params();
	$m = $u['message'] ?? null;
	if ( ! $m || 'private' !== ( $m['chat']['type'] ?? '' ) ) {
		return array( 'ok' => true );
	}
	$chat  = (string) $m['chat']['id'];
	$admin = (string) get_option( 'fx_tg_chat' );
	$text  = (string) ( $m['text'] ?? ( $m['caption'] ?? '' ) );
	$media = ! isset( $m['text'] );

	if ( $admin && $chat === $admin ) {   // Slavik
		$rid = (string) ( $m['reply_to_message']['message_id'] ?? '' );
		$id  = $rid ? fx_lead_by( 'fx_tg_mid', $rid ) : 0;
		if ( ! $id ) {
			fx_tg( 'sendMessage', array( 'chat_id' => $admin, 'text' => $rid ? 'Не нашёл, к какой заявке это относится. Ответь реплаем на сообщение клиента.' : 'Чтобы ответить клиенту, сделай реплай на его сообщение (свайп влево по сообщению).' ) );
			return array( 'ok' => true );
		}
		$ok = false;
		if ( 'tg' === get_post_meta( $id, 'fx_src', true ) ) {
			$to = get_post_meta( $id, 'fx_tg_user', true );
			$ok = (bool) ( $media ? fx_tg( 'copyMessage', array( 'chat_id' => $to, 'from_chat_id' => $admin, 'message_id' => $m['message_id'] ) ) : fx_tg( 'sendMessage', array( 'chat_id' => $to, 'text' => $text ) ) );
			if ( $ok ) {
				fx_thread_add( $id, 's', $text ?: '[Foto/Datei]' );
			}
		} elseif ( '' === trim( $text ) ) {
			fx_tg( 'sendMessage', array( 'chat_id' => $admin, 'text' => 'На сайт уходит только текст. Фото отправь клиенту на почту или в мессенджер.' ) );
			return array( 'ok' => true );
		} else {
			fx_thread_add( $id, 's', $text );
			$ok      = true;
			$contact = get_post_meta( $id, 'fx_contact', true );
			if ( is_email( $contact ) ) {
				$lang = get_post_meta( $id, 'fx_lang', true );
				$sub  = array( 'de' => 'Antwort von Slavik (Farbaholix)', 'uk' => 'Відповідь від Славіка (Farbaholix)' )[ $lang ] ?? 'Reply from Slavik (Farbaholix)';
				wp_mail( $contact, $sub, $text . "\n\n—\nSlavik · Farbaholix\nhttps://farbaholix.de\n+49 151 724 50347", array( 'Content-Type: text/plain; charset=UTF-8', 'Reply-To: Slavik (Farbaholix) <farbaholix@gmail.com>' ) );
			}
		}
		if ( $ok ) {
			fx_tg( 'setMessageReaction', array( 'chat_id' => $admin, 'message_id' => $m['message_id'], 'reaction' => array( array( 'type' => 'emoji', 'emoji' => '👍' ) ) ) );
		}
		return array( 'ok' => true );
	}

	// a visitor writing to the bot
	$from = (array) ( $m['from'] ?? array() );
	$lang = sanitize_key( $from['language_code'] ?? '' );
	$tx   = fx_tg_texts( $lang );
	if ( 0 === strpos( $text, '/start' ) ) {
		fx_tg( 'sendMessage', array( 'chat_id' => $chat, 'text' => $tx['hi'] ) );
		return array( 'ok' => true );
	}
	if ( ! fx_rate( 'tg' . $chat, 30, HOUR_IN_SECONDS ) ) {
		return array( 'ok' => true );
	}
	$name = trim( ( $from['first_name'] ?? '' ) . ' ' . ( $from['last_name'] ?? '' ) );
	$user = ! empty( $from['username'] ) ? '@' . $from['username'] : '';
	$id   = fx_lead_by( 'fx_tg_user', $chat );
	$new  = ! $id;
	if ( $new ) {
		$id = wp_insert_post( array( 'post_type' => 'fx_lead', 'post_status' => 'private', 'post_title' => 'Telegram: ' . trim( "$name $user" ) . ' – ' . wp_date( 'd.m.Y H:i' ), 'post_content' => 'Telegram ' . trim( "$name $user" ) ) );
		foreach ( array( 'fx_src' => 'tg', 'fx_tg_user' => $chat, 'fx_name' => $name, 'fx_contact' => $user ?: 'Telegram', 'fx_lang' => $lang ) as $k => $v ) {
			update_post_meta( $id, $k, $v );
		}
	}
	$body = $text ?: '';
	if ( $media ) {
		$body = '[Foto/Datei]' . ( $text ? ' ' . $text : '' );
	}
	fx_thread_add( $id, 'v', $body );
	fx_notify( $id, 'Telegram: ' . ( $name ?: $user ), "💬 Telegram #$id · " . trim( "$name $user" ) . "\n\n" . $body );
	if ( $media && $admin ) {
		$c = fx_tg( 'copyMessage', array( 'chat_id' => $admin, 'from_chat_id' => $chat, 'message_id' => $m['message_id'] ) );
		if ( $c ) {
			add_post_meta( $id, 'fx_tg_mid', (string) $c['message_id'] );
		}
	}
	$th = get_post_meta( $id, 'fx_thread', true );
	if ( $new || ( is_array( $th ) && 1 === count( array_filter( $th, function ( $x ) { return 'v' === $x['w']; } ) ) ) ) {
		fx_tg( 'sendMessage', array( 'chat_id' => $chat, 'text' => $tx['ack'] ) );
	}
	return array( 'ok' => true );
}
function fx_tg_setup( WP_REST_Request $r ) {
	$p = (array) $r->get_json_params();
	if ( ! empty( $p['token'] ) ) {
		update_option( 'fx_tg_token', sanitize_text_field( $p['token'] ), false );
	}
	if ( ! empty( $p['reset_chat'] ) ) {
		delete_option( 'fx_tg_chat' );
	}
	$me = fx_tg( 'getMe', array() );
	if ( ! $me ) {
		return new WP_Error( 'fx_tg', 'token invalid', array( 'status' => 400 ) );
	}
	update_option( 'fx_tg_bot', $me['username'], false );
	$who = null;
	if ( ! get_option( 'fx_tg_chat' ) ) {   // Slavik must have sent /start to the bot before
		fx_tg( 'deleteWebhook', array() );
		$ups = (array) fx_tg( 'getUpdates', array( 'allowed_updates' => array( 'message' ) ) );
		foreach ( array_reverse( $ups ) as $up ) {
			$mm = $up['message'] ?? null;
			if ( $mm && 'private' === ( $mm['chat']['type'] ?? '' ) ) {
				update_option( 'fx_tg_chat', (string) $mm['chat']['id'], false );
				$who = trim( ( $mm['from']['first_name'] ?? '' ) . ' @' . ( $mm['from']['username'] ?? '' ) );
				break;
			}
		}
	}
	$secret = (string) get_option( 'fx_tg_secret' );
	if ( ! $secret ) {
		$secret = wp_generate_password( 40, false, false );
		update_option( 'fx_tg_secret', $secret, false );
	}
	$hook = fx_tg( 'setWebhook', array( 'url' => rest_url( 'fx/v1/tg/' . $secret ), 'secret_token' => $secret, 'allowed_updates' => array( 'message' ), 'drop_pending_updates' => true ) );
	$chat = (string) get_option( 'fx_tg_chat' );
	if ( $chat && $who ) {
		fx_tg( 'sendMessage', array( 'chat_id' => $chat, 'text' => "✅ Бот подключён к farbaholix.de.\nСюда будут приходить все заявки с сайта и сообщения клиентов из Telegram. Чтобы ответить – сделай реплай на сообщение." ) );
	}
	return array( 'ok' => true, 'bot' => $me['username'], 'chat' => (bool) $chat, 'who' => $who, 'webhook' => (bool) $hook );
}
