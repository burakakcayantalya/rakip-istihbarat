<?php
/**
 * Elementor Native Replace Endpoint - DÜZELTİLMİŞ VERSİYON
 * 
 * Bu kod WordPress functions.php dosyasına eklenecek.
 * REST API authentication ile çalışır.
 */

add_action('rest_api_init', function () {
    
    // 0. TEST ENDPOINT - Endpoint'in çalışıp çalışmadığını kontrol et
    register_rest_route('custom/v1', '/test', array(
        'methods' => 'GET',
        'permission_callback' => '__return_true',
        'callback' => function ($request) {
            return array(
                'success' => true,
                'message' => 'Custom endpoint çalışıyor!',
                'timestamp' => current_time('mysql')
            );
        },
    ));

    // 1. İZİN: Python'un Elementor verisini OKUMASINI sağlar
    register_rest_field(['page', 'post'], '_elementor_data', array(
        'get_callback'    => function ($object) {
            return get_post_meta($object['id'], '_elementor_data', true);
        },
        'update_callback' => null,
        'schema'          => null,
    ));

    // 2. İŞLEM: Elementor Native Replace Endpoint'i (DÜZELTİLMİŞ)
    register_rest_route('custom/v1', '/elementor-native-replace', array(
        'methods' => 'POST',
        'permission_callback' => function ($request) {
            // REST API authentication kontrolü
            $user = null;
            
            // Önce Basic Auth header'dan username:password çıkar
            $auth_header = $request->get_header('Authorization');
            if ($auth_header && strpos($auth_header, 'Basic ') === 0) {
                $credentials = base64_decode(substr($auth_header, 6));
                list($username, $password) = explode(':', $credentials, 2);
                if ($username && $password) {
                    $user = wp_authenticate($username, $password);
                }
            }
            
            // Application Password desteği kaldırıldı - sadece Basic Auth kullanılıyor
            // (WordPress sürüm uyumsuzlukları nedeniyle)
            
            // Eğer hala user yoksa, REST API nonce kontrolü yap
            if (!$user || is_wp_error($user)) {
                $user_id = wp_validate_auth_cookie();
                if ($user_id) {
                    $user = get_user_by('ID', $user_id);
                }
            }
            
            // Normal kullanım: User varsa ve edit_posts yetkisi varsa izin ver
            if ($user && !is_wp_error($user)) {
                return user_can($user, 'edit_posts');
            }
            
            // REST API authentication başarısız
            return false;
        },
        'callback' => function ($request) {
            // --- Fonksiyon Başlangıcı ---
            
            $post_id = $request->get_param('id');
            $old_url = $request->get_param('old_url');
            $new_url = $request->get_param('new_url');
            
            // Parametre kontrolü
            if (!$post_id || !$old_url || !$new_url) {
                return new WP_Error(
                    'missing_params', 
                    'Eksik parametreler: id, old_url ve new_url gerekli.', 
                    ['status' => 400]
                );
            }
            
            // Elementor kontrolü
            if (!class_exists('\Elementor\Plugin')) {
                return new WP_Error(
                    'elementor_missing', 
                    'Elementor yüklü değil.', 
                    ['status' => 500]
                );
            }
            
            // Veriyi al
            $source_data = get_post_meta($post_id, '_elementor_data', true);
            if (empty($source_data)) {
                return new WP_Error(
                    'no_data', 
                    'Elementor data bulunamadı.', 
                    ['status' => 404]
                );
            }
            
            // ========================================
            // GÜVENLİ REPLACE MANTIĞI (V2)
            // Escaped quotes + mixed format support
            // ========================================
            
            $updated_data = $source_data;
            $changes_count = 0;
            
            // URL'leri normalize et
            $old_url_normalized = rtrim($old_url, '/');
            $new_url_normalized = rtrim($new_url, '/');
            
            // Escaped slash versiyonları
            $old_url_escaped = str_replace('/', '\/', $old_url_normalized);
            $new_url_escaped = str_replace('/', '\/', $new_url_normalized);
            
            // ========================================
            // PATTERN LİSTESİ - TÜM VARYASYONLAR
            // ========================================
            
            $patterns = [];
            
            // 1. Normal quotes (unescaped): href="..."
            $patterns['href="' . $old_url_normalized . '"'] = 'href="' . $new_url_normalized . '/"';
            $patterns['href="' . $old_url_normalized . '/"'] = 'href="' . $new_url_normalized . '/"';
            $patterns["href='" . $old_url_normalized . "'"] = "href='" . $new_url_normalized . "/'";
            $patterns["href='" . $old_url_normalized . "/'"] = "href='" . $new_url_normalized . "/'";
            
            // 2. Escaped slashes: href="\/old\/url\/"
            $patterns['href="' . $old_url_escaped . '"'] = 'href="' . $new_url_escaped . '\/"';
            $patterns['href="' . $old_url_escaped . '\/"'] = 'href="' . $new_url_escaped . '\/"';
            
            // 3. Escaped quotes (JSON encoded): href=\"...\"
            $patterns['href=\"' . $old_url_normalized . '\"'] = 'href=\"' . $new_url_normalized . '/\"';
            $patterns['href=\"' . $old_url_normalized . '/\"'] = 'href=\"' . $new_url_normalized . '/\"';
            
            // 4. Escaped quotes + escaped slashes: href=\"\/old\/url\/\"
            $patterns['href=\"' . $old_url_escaped . '\"'] = 'href=\"' . $new_url_escaped . '\/\"';
            $patterns['href=\"' . $old_url_escaped . '\/\"'] = 'href=\"' . $new_url_escaped . '\/\"';
            
            // 5. URL field formats
            $patterns['"url":"' . $old_url_normalized . '"'] = '"url":"' . $new_url_normalized . '\/"';
            $patterns['"url":"' . $old_url_normalized . '\/"'] = '"url":"' . $new_url_normalized . '\/"';
            $patterns['"url":"' . $old_url_escaped . '"'] = '"url":"' . $new_url_escaped . '\/"';
            $patterns['"url":"' . $old_url_escaped . '\/"'] = '"url":"' . $new_url_escaped . '\/"';
            
            // 6. Direkt URL değişimi (href olmadan, sadece URL)
            $patterns[$old_url_normalized] = $new_url_normalized;
            $patterns[$old_url_normalized . '/'] = $new_url_normalized . '/';
            $patterns[$old_url_escaped] = $new_url_escaped;
            $patterns[$old_url_escaped . '\/'] = $new_url_escaped . '\/';
            
            // 7. URL encode edilmiş versiyonlar (örn: %2F)
            $old_url_encoded = urlencode($old_url_normalized);
            $new_url_encoded = urlencode($new_url_normalized);
            if ($old_url_encoded != $old_url_normalized) {
                $patterns[$old_url_encoded] = $new_url_encoded;
            }
            
            // ========================================
            // REPLACEMENT
            // ========================================
            
            foreach ($patterns as $search => $replace) {
                if (strpos($updated_data, $search) !== false) {
                    $count = substr_count($updated_data, $search);
                    $updated_data = str_replace($search, $replace, $updated_data);
                    $changes_count += $count;
                }
            }
            
            // Değişiklik yoksa çık
            if ($source_data === $updated_data) {
                return array(
                    'success' => true,
                    'changes_count' => 0,
                    'message' => 'Link bulunamadı, değişiklik yapılmadı.'
                );
            }
            
            // Veriyi Kaydet (wp_slash önemli!)
            $update_result = update_post_meta($post_id, '_elementor_data', wp_slash($updated_data));
            
            if (!$update_result) {
                return new WP_Error(
                    'update_failed', 
                    'Elementor data güncellenemedi.', 
                    ['status' => 500]
                );
            }
            
            // CSS Cache Temizle (Bozulmayı önleyen kısım)
            if (class_exists('\Elementor\Plugin') && isset(\Elementor\Plugin::$instance)) {
                try {
                    \Elementor\Plugin::$instance->files_manager->clear_cache();
                } catch (Exception $e) {
                    // Cache temizleme hatası kritik değil, logla
                    error_log('Elementor cache temizleme hatası: ' . $e->getMessage());
                }
            }
            
            // WordPress Genel Cache Temizle
            try {
                // 1. Object Cache (Redis, Memcached vb.)
                if (function_exists('wp_cache_flush')) {
                    wp_cache_flush();
                }
                
                // 2. Transients temizle (opsiyonel - sadece bu post için)
                // delete_transient('elementor_css_' . $post_id);
                
                // 3. Page Cache temizle (popüler cache plugin'leri için)
                // WP Super Cache
                if (function_exists('wp_cache_post_change')) {
                    wp_cache_post_change($post_id);
                }
                
                // W3 Total Cache
                if (function_exists('w3tc_flush_post')) {
                    w3tc_flush_post($post_id);
                }
                
                // WP Rocket
                if (function_exists('rocket_clean_post')) {
                    rocket_clean_post($post_id);
                }
                
                // LiteSpeed Cache
                if (class_exists('\LiteSpeed\Purge')) {
                    \LiteSpeed\Purge::purge_post($post_id);
                }
                
                // 4. Elementor CSS/JS cache temizle (ekstra)
                if (class_exists('\Elementor\Plugin')) {
                    \Elementor\Plugin::$instance->files_manager->regenerate_css_files();
                }
                
            } catch (Exception $e) {
                // Cache temizleme hatası kritik değil, logla
                error_log('WordPress cache temizleme hatası: ' . $e->getMessage());
            }
            
            // Sayfa güncellemesi için post meta ekle (opsiyonel - frontend'de kontrol edilebilir)
            update_post_meta($post_id, '_elementor_last_updated', time());
            
            return array(
                'success' => true,
                'changes_count' => $changes_count,
                'message' => sprintf('%d link başarıyla güncellendi, cache temizlendi ve sayfa güncellendi.', $changes_count),
                'cache_cleared' => true,
                'page_updated' => true
            );
            
            // --- Fonksiyon Bitişi ---
        },
    ));
    
    // 3. Elementor Content Update Endpoint'i (BASİT VERSİYON)
    register_rest_route('custom/v1', '/update-elementor-page', array(
        'methods' => 'POST',
        'callback' => 'update_elementor_page',
        'permission_callback' => function ($request) {
            // REST API authentication kontrolü
            $user = null;
            
            // Önce Basic Auth header'dan username:password çıkar
            $auth_header = $request->get_header('Authorization');
            if ($auth_header && strpos($auth_header, 'Basic ') === 0) {
                $credentials = base64_decode(substr($auth_header, 6));
                list($username, $password) = explode(':', $credentials, 2);
                if ($username && $password) {
                    $user = wp_authenticate($username, $password);
                    if ($user && !is_wp_error($user)) {
                        wp_set_current_user($user->ID);
                    }
                }
            }
            
            // Cookie-based authentication
            if (!$user || is_wp_error($user)) {
                $user_id = wp_validate_auth_cookie();
                if ($user_id) {
                    wp_set_current_user($user_id);
                }
            }
            
            // Permission kontrolü
            return current_user_can('edit_pages');
        },
        'args' => array(
            'post_id' => array(
                'required' => true,
                'type' => 'integer',
            ),
            'elementor_data' => array(
                'required' => true,
                'type' => 'string',
            ),
        ),
    ));
});

// Elementor Page Update Fonksiyonu
function update_elementor_page(WP_REST_Request $request) {
    $post_id = $request->get_param('post_id');
    $elementor_data = $request->get_param('elementor_data');
    
    if (empty($post_id) || empty($elementor_data)) {
        return new WP_Error('missing_params', 'Post ID veya Elementor data eksik.', array('status' => 400));
    }
    
    // Elementor kontrolü
    if (!class_exists('\Elementor\Plugin')) {
        return new WP_Error('elementor_missing', 'Elementor yüklü değil.', array('status' => 500));
    }
    
    // Meta'yı güncelle (JSON string olarak saklanır)
    // wp_slash önemli - JSON escape için
    $updated = update_post_meta($post_id, '_elementor_data', wp_slash($elementor_data));
    
    // update_post_meta false dönebilir (değer aynıysa), bu hata değil
    // Ama gerçek bir hata olup olmadığını kontrol et
    if ($updated === false) {
        $existing = get_post_meta($post_id, '_elementor_data', true);
        if ($existing === false) {
            // Meta hiç yoksa, ekle
            $added = add_post_meta($post_id, '_elementor_data', wp_slash($elementor_data), true);
            if (!$added) {
                return new WP_Error('update_failed', 'Elementor data eklenemedi.', array('status' => 500));
            }
        } elseif ($existing !== $elementor_data) {
            // Meta var ama farklı, güncelleme başarısız
            return new WP_Error('update_failed', 'Elementor data güncellenemedi.', array('status' => 500));
        }
    }
    
    // Post'u güncelle (cache temizleme için)
    wp_update_post(array(
        'ID' => $post_id,
        'post_modified' => current_time('mysql'),
        'post_modified_gmt' => current_time('mysql', 1)
    ));
    
    // Elementor CSS'ini yenile
    if (class_exists('\Elementor\Plugin') && isset(\Elementor\Plugin::$instance)) {
        try {
            \Elementor\Plugin::$instance->files_manager->clear_cache();
        } catch (Exception $e) {
            error_log('Elementor cache temizleme hatası: ' . $e->getMessage());
        }
    }
    
    // WordPress Genel Cache Temizle
    try {
        if (function_exists('wp_cache_flush')) {
            wp_cache_flush();
        }
        
        if (function_exists('wp_cache_post_change')) {
            wp_cache_post_change($post_id);
        }
        
        if (function_exists('w3tc_flush_post')) {
            w3tc_flush_post($post_id);
        }
        
        if (function_exists('rocket_clean_post')) {
            rocket_clean_post($post_id);
        }
        
        if (class_exists('\LiteSpeed\Purge')) {
            \LiteSpeed\Purge::purge_post($post_id);
        }
    } catch (Exception $e) {
        error_log('WordPress cache temizleme hatası: ' . $e->getMessage());
    }
    
    return array(
        'success' => true,
        'message' => 'Sayfa Elementor verisi güncellendi.',
        'post_id' => $post_id,
        'cache_cleared' => true
    );
}

