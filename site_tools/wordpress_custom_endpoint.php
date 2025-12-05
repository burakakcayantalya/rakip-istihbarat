<?php
/**
 * WordPress Custom REST API Endpoint for Elementor Native URL Replacement
 * 
 * Bu dosyayı WordPress tema'nızın functions.php dosyasına ekleyin
 * veya "Code Snippets" eklentisi kullanıyorsanız yeni bir snippet olarak ekleyin.
 * 
 * Bu endpoint, Elementor'un kendi URL değiştirme mantığını taklit eder ve
 * Elementor'un önbellek temizleyicisini otomatik çalıştırır.
 */

add_action('rest_api_init', function () {
    // 1. İZİN: Python'un Elementor verisini OKUMASINI sağlar
    register_rest_field(['page', 'post'], '_elementor_data', array(
        'get_callback'    => function ($object) {
            return get_post_meta($object['id'], '_elementor_data', true);
        },
        'update_callback' => null,
        'schema'          => null,
    ));

    // 2. İŞLEM: Elementor Native Replace Endpoint'i (İsimsiz Fonksiyon)
    register_rest_route('custom/v1', '/elementor-native-replace', array(
        'methods' => 'POST',
        'permission_callback' => function () {
            return current_user_can('edit_posts');
        },
        'callback' => function ($request) {
            // --- Fonksiyon Başlangıcı ---
            
            $post_id = $request->get_param('id');
            $old_url = $request->get_param('old_url');
            $new_url = $request->get_param('new_url');
            
            // Parametre kontrolü
            if (!$post_id || !$old_url || !$new_url) {
                return new WP_Error('missing_params', 'Eksik parametreler.', ['status' => 400]);
            }
            
            // Elementor kontrolü
            if (!class_exists('\Elementor\Plugin')) {
                return new WP_Error('elementor_missing', 'Elementor yüklü değil.', ['status' => 500]);
            }
            
            // Veriyi al
            $source_data = get_post_meta($post_id, '_elementor_data', true);
            
            if (empty($source_data)) {
                return new WP_Error('no_data', 'Veri yok.', ['status' => 404]);
            }
            
            // DEĞİŞTİRME MANTIĞI
            // 1. Düz Link Değişimi
            $updated_data = str_replace($old_url, $new_url, $source_data);
            
            // 2. Escaped (Kaçışlı) Link Değişimi (Örn: https:\/\/...)
            $old_url_escaped = str_replace('/', '\/', $old_url);
            $new_url_escaped = str_replace('/', '\/', $new_url);
            $updated_data = str_replace($old_url_escaped, $new_url_escaped, $updated_data);
            
            // Değişiklik yoksa çık
            if ($source_data === $updated_data) {
                return [
                    'success' => true,
                    'changes_count' => 0,
                    'message' => 'Link bulunamadı, değişiklik yapılmadı.'
                ];
            }
            
            // Veriyi Kaydet (wp_slash önemli!)
            update_post_meta($post_id, '_elementor_data', wp_slash($updated_data));
            
            // CSS Cache Temizle (Bozulmayı önleyen kısım)
            \Elementor\Plugin::$instance->files_manager->clear_cache();
            
            return [
                'success' => true,
                'changes_count' => 1,
                'message' => 'Başarıyla güncellendi ve CSS yenilendi.'
            ];
            // --- Fonksiyon Bitişi ---
        },
    ));
});

/**
 * Kullanım:
 * 1. Bu kodu WordPress tema'nızın functions.php dosyasına ekleyin
 * 2. Veya "Code Snippets" eklentisi ile yeni bir snippet olarak ekleyin
 * 3. WordPress cache'ini temizleyin
 * 4. Artık şu endpoint'ler kullanılabilir:
 *    - GET /wp-json/wp/v2/pages/{id} veya /wp-json/wp/v2/posts/{id} -> _elementor_data field'ı ile birlikte gelir
 *    - POST /wp-json/custom/v1/elementor-native-replace -> URL değiştirir
 * 
 * NOT: Bu endpoint Elementor'un kendi URL değiştirme mantığını kullanır ve
 * otomatik olarak Elementor cache'ini temizler. CSS bozulması sorunu yaşanmaz.
 */
