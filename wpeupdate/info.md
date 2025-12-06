# WordPress Elementor İçerik Güncelleme Sistemi

## 📋 Genel Bakış

Bu sistem, WordPress Elementor sayfalarındaki içerikleri (H tagları, paragraflar, linkler) programatik olarak güncellemek için geliştirilmiştir. Sistem, Elementor JSON yapısını parse eder, kullanıcının yaptığı değişiklikleri algılar ve WordPress'e push eder.

## 🎯 Sistemin Amacı

- WordPress Elementor sayfalarındaki içerikleri JSON formatında çekmek
- İçerikleri (H tagları, paragraflar, linkler) extract etmek ve düzenlenebilir formata dönüştürmek
- Kullanıcının yaptığı değişiklikleri algılamak
- Değişiklikleri WordPress Elementor'a geri push etmek

## 📁 Dosya Yapısı

### 1. `sync_from_wordpress.py`
**Amaç:** WordPress'ten güncel Elementor JSON'unu çeker ve extract eder.

**Ne Yapar:**
- WordPress REST API'den Elementor JSON'unu indirir
- `{domain}_elementor.json` dosyasına kaydeder
- İçerikleri extract eder (H tagları, paragraflar, linkler)
- `elementor_content_extracted.json` dosyasını günceller

**Kullanım:**
```bash
python sync_from_wordpress.py
```

**Bağımlılıklar:**
- `core.database` - Site bilgilerini almak için
- `extract_content_from_elementor` - İçerik extract etmek için
- `httpx` - HTTP istekleri için
- `asyncio` - Asenkron işlemler için

### 2. `extract_content_from_elementor.py`
**Amaç:** Elementor JSON yapısından içerikleri (H tagları, paragraflar, linkler) çıkarır.

**Ne Yapar:**
- Elementor JSON'unu recursive olarak tarar
- Heading widget'larından H taglarını çıkarır
- Text Editor widget'larından paragrafları çıkarır
- Button ve Icon List widget'larından linkleri çıkarır
- Her öğe için `element_id`, `original`, `original_url` gibi metadata saklar

**Önemli Özellikler:**
- Icon list item'ları için `_id` alanını da extract eder (eşleştirme için kritik)
- `original` ve `original_url` alanlarını saklar (değişiklik algılama için)

**Çıktı Formatı:**
```json
{
  "headings": [...],
  "paragraphs": [...],
  "links": [...],
  "all": [...],
  "stats": {...}
}
```

### 3. `push_content_to_wordpress.py`
**Amaç:** `elementor_content_extracted.json` dosyasındaki değişiklikleri algılar ve WordPress'e push eder.

**Ne Yapar:**
- `elementor_content_extracted.json` dosyasını okur
- `original` ve `content` değerlerini karşılaştırarak değişiklikleri algılar
- `original_url` ve `url` değerlerini karşılaştırarak URL değişikliklerini algılar
- Sadece değişen öğeleri orijinal Elementor JSON'a uygular
- WordPress'e custom endpoint ile push eder

**Değişiklik Algılama Mantığı:**
- **Heading/Paragraph:** `original` != `content` ise değişiklik var
- **Link:** `original_url` != `url` veya `original` != `content` ise değişiklik var
- **Icon List Item:** `_id`, `text` veya `url` ile eşleştirme yapılır

**Kullanım:**
```bash
python push_content_to_wordpress.py
```

**Bağımlılıklar:**
- `core.database` - Site bilgilerini almak için
- `agents.link_fixer.wordpress_fixer` - WordPress API işlemleri için
- `BeautifulSoup` - HTML parsing için
- `httpx` - HTTP istekleri için

### 4. `wordpress_functions_fix.php`
**Amaç:** WordPress'e eklenecek custom REST API endpoint'leri içerir.

**Ne İçerir:**
1. **Test Endpoint:** `/wp-json/custom/v1/test` - Endpoint'lerin çalışıp çalışmadığını kontrol eder
2. **Elementor Data Read:** `_elementor_data` field'ını REST API'ye ekler
3. **Elementor Native Replace:** `/wp-json/custom/v1/elementor-native-replace` - URL değiştirme için
4. **Elementor Page Update:** `/wp-json/custom/v1/update-elementor-page` - Tüm Elementor JSON'u güncelleme için

**WordPress'e Ekleme:**
Bu dosyanın içeriğini WordPress tema'nızın `functions.php` dosyasına ekleyin veya bir plugin olarak yükleyin (örn: Code Snippets plugin).

## 🔧 WordPress Kurulumu

### 1. Application Password Oluşturma
1. WordPress Admin Panel > Users > Your Profile
2. "Application Passwords" bölümüne gidin
3. Yeni bir Application Password oluşturun
4. Bu şifreyi veritabanına kaydedin (`sites` tablosunda `wp_api_password` alanına)

### 2. PHP Kodunu Ekleme
`wordpress_functions_fix.php` dosyasının içeriğini WordPress tema'nızın `functions.php` dosyasına ekleyin.

**Önemli Notlar:**
- `update_elementor_page` fonksiyonu `add_action` dışında, dosyanın sonunda olmalı
- PHP syntax hatalarına dikkat edin
- WordPress ve Elementor güncel olmalı

### 3. Endpoint'leri Test Etme
```bash
curl -X GET "https://your-site.com/wp-json/custom/v1/test" \
  -u "username:application_password"
```

## 🔌 REST API Endpoint'leri

### 1. Test Endpoint
```
GET /wp-json/custom/v1/test
```
**Amaç:** Endpoint'lerin çalışıp çalışmadığını kontrol eder.

**Authentication:** Gerekmez

**Response:**
```json
{
  "success": true,
  "message": "Custom endpoint çalışıyor!",
  "timestamp": "2025-12-06 12:00:00"
}
```

### 2. Elementor Data Read
```
GET /wp-json/wp/v2/pages/{id}
GET /wp-json/wp/v2/posts/{id}
```
**Amaç:** Elementor JSON'unu okumak için `_elementor_data` field'ını ekler.

**Authentication:** Application Password (Basic Auth)

**Response:** Post/Page objesi + `_elementor_data` field'ı

### 3. Elementor Native Replace
```
POST /wp-json/custom/v1/elementor-native-replace
```
**Amaç:** Elementor JSON içindeki URL'leri değiştirmek için.

**Authentication:** Application Password (Basic Auth)

**Request Body:**
```json
{
  "id": 82,
  "old_url": "https://example.com/old-url/",
  "new_url": "https://example.com/new-url/"
}
```

**Response:**
```json
{
  "success": true,
  "changes_count": 5,
  "message": "5 link başarıyla güncellendi...",
  "cache_cleared": true,
  "page_updated": true
}
```

**Özellikler:**
- Escaped URL formatlarını destekler (`https:\/\/`)
- Escaped quotes formatlarını destekler (`href=\"...\"`)
- Trailing slash normalizasyonu yapar
- Elementor cache'ini otomatik temizler

### 4. Elementor Page Update
```
POST /wp-json/custom/v1/update-elementor-page
```
**Amaç:** Tüm Elementor JSON'unu güncellemek için.

**Authentication:** Application Password (Basic Auth)

**Request Body:**
```json
{
  "post_id": 82,
  "elementor_data": "{...tüm Elementor JSON...}"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Sayfa Elementor verisi güncellendi.",
  "post_id": 82,
  "cache_cleared": true
}
```

**Özellikler:**
- `update_post_meta` kullanır (WordPress standard)
- `wp_slash` ile JSON escape yapar
- Elementor cache'ini temizler
- WordPress genel cache'ini temizler (W3TC, WP Rocket, LiteSpeed vb.)

## 📝 Kullanım Akışı

### 1. İlk Kurulum
```bash
# 1. WordPress'e PHP kodunu ekleyin (functions.php)
# 2. Application Password oluşturun
# 3. Veritabanına site bilgilerini ekleyin
```

### 2. Güncel Veriyi Çekme
```bash
python sync_from_wordpress.py
```

Bu komut:
- WordPress'ten Elementor JSON'unu indirir
- `{domain}_elementor.json` dosyasına kaydeder
- İçerikleri extract eder
- `elementor_content_extracted.json` dosyasını günceller

### 3. İçerik Düzenleme
`elementor_content_extracted.json` dosyasını açın ve istediğiniz `content` veya `url` değerlerini değiştirin.

**Örnek:**
```json
{
  "type": "heading",
  "content": "Yeni Başlık",  // Değiştir
  "original": "Eski Başlık",  // Bu değişmez
  ...
}
```

### 4. Değişiklikleri Push Etme
```bash
python push_content_to_wordpress.py
```

Bu komut:
- Değişiklikleri algılar (`original` != `content`)
- Sadece değişen öğeleri günceller
- WordPress'e push eder
- Cache'i temizler

## 🔍 Öğrenilenler ve Çözümler

### 1. Elementor JSON Yapısı
- Elementor içerikleri `_elementor_data` post meta'sında JSON string olarak saklanır
- JSON içinde URL'ler escaped formatlarda olabilir (`https:\/\/`)
- HTML attribute'ları escaped quotes ile gelebilir (`href=\"...\"`)

### 2. URL Formatları
Elementor JSON'da URL'ler farklı formatlarda olabilir:
- Normal: `https://example.com/page/`
- Escaped slashes: `https:\/\/example.com\/page\/`
- Escaped quotes: `href=\"https://example.com/page/\"`
- Mixed: `href=\"https:\/\/example.com\/page\/\"`

**Çözüm:** Tüm formatları destekleyen pattern matching sistemi geliştirildi.

### 3. Icon List Item Eşleştirme
Icon list item'ları için eşleştirme sorunları yaşandı.

**Sorun:** Icon list içindeki item'ları doğru şekilde eşleştirmek zordu.

**Çözüm:**
- `_id` alanını extract etme eklendi
- `_id`, `text` ve `url` ile çoklu eşleştirme yapılıyor
- Trailing slash normalizasyonu yapılıyor

### 4. Değişiklik Algılama
**Sorun:** Hangi öğelerin değiştiğini algılamak gerekiyordu.

**Çözüm:**
- `original` ve `original_url` alanları extract edilirken saklanıyor
- Push sırasında `original` != `content` karşılaştırması yapılıyor
- Sadece değişen öğeler güncelleniyor

### 5. WordPress Cache Sorunları
**Sorun:** Güncellemeler hemen görünmüyordu.

**Çözüm:**
- Elementor cache temizleme eklendi
- WordPress genel cache temizleme eklendi (W3TC, WP Rocket, LiteSpeed)
- Post update tetikleniyor

### 6. Authentication Sorunları
**Sorun:** Application Password authentication bazen çalışmıyordu.

**Çözüm:**
- Basic Auth kullanılıyor
- `wp_set_current_user` ile user context ayarlanıyor
- `current_user_can` ile permission kontrolü yapılıyor

## ⚠️ Önemli Notlar

### 1. Dosya Yolları
Scriptler ana dizinde çalışır. `extract_content_from_elementor.py` import edilirken path'e dikkat edin.

### 2. Veritabanı Bağımlılığı
Scriptler `core.database` modülünü kullanır. Site bilgileri `sites` tablosunda olmalı:
- `wp_api_url`
- `wp_api_username`
- `wp_api_password`

### 3. Elementor Versiyonu
Sistem Elementor Pro ile test edilmiştir. Farklı versiyonlarda JSON yapısı değişebilir.

### 4. Icon List Item'ları
Icon list item'ları için `_id` alanı kritiktir. `sync_from_wordpress.py` çalıştırıldığında `_id` alanları extract edilir.

### 5. Cache Temizleme
WordPress cache plugin'leri (W3TC, WP Rocket, LiteSpeed) kullanılıyorsa, PHP kodunda ilgili cache temizleme fonksiyonları çağrılır.

## 🐛 Bilinen Sorunlar ve Çözümler

### 1. Icon List Item Eşleşmiyor
**Sorun:** Icon list item'ları eşleşmiyor.

**Çözüm:**
- `sync_from_wordpress.py` çalıştırın (`_id` alanlarını ekler)
- `elementor_content_extracted.json` dosyasında `_id` alanının olduğundan emin olun
- `text` veya `url` ile de eşleştirme yapılır

### 2. Değişiklik Algılanmıyor
**Sorun:** Değişiklik yaptınız ama algılanmıyor.

**Çözüm:**
- Dosyayı kaydettiğinizden emin olun (Ctrl+S / Cmd+S)
- `original` ve `content` değerlerinin farklı olduğundan emin olun
- `sync_from_wordpress.py` çalıştırıp tekrar deneyin

### 3. WordPress'te Görünmüyor
**Sorun:** Push başarılı ama WordPress'te görünmüyor.

**Çözüm:**
- Hard refresh yapın (Ctrl+F5 / Cmd+Shift+R)
- WordPress Admin > Elementor > Tools > Regenerate CSS & Data
- WordPress cache plugin'lerini kontrol edin

### 4. 404/500 Hataları
**Sorun:** Endpoint'ler 404 veya 500 hatası veriyor.

**Çözüm:**
- `functions.php` dosyasına kodu eklediğinizden emin olun
- PHP syntax hatalarını kontrol edin
- WordPress ve Elementor güncel mi kontrol edin
- Test endpoint'i deneyin: `/wp-json/custom/v1/test`

## 📚 Gelecekte Kullanım İçin

### Yeni Bir Site İçin Kurulum
1. `sites` tablosuna site bilgilerini ekleyin
2. WordPress'e `wordpress_functions_fix.php` kodunu ekleyin
3. Application Password oluşturun
4. `sync_from_wordpress.py` çalıştırın
5. `elementor_content_extracted.json` dosyasını düzenleyin
6. `push_content_to_wordpress.py` çalıştırın

### Yeni İçerik Tipleri Eklemek
1. `extract_content_from_elementor.py` dosyasına yeni widget type'ı ekleyin
2. `push_content_to_wordpress.py` dosyasına güncelleme mantığını ekleyin
3. Test edin

### Farklı WordPress Sürümleri
WordPress ve Elementor sürümleri değiştiğinde JSON yapısı değişebilir. `extract_content_from_elementor.py` dosyasını güncellemeniz gerekebilir.

## 🔗 İlgili Dosyalar

- `mommymakeoverturkey_net_elementor.json` - Orijinal Elementor JSON (WordPress'ten çekilen)
- `elementor_content_extracted.json` - Extract edilmiş içerikler (düzenlenebilir format)
- `wordpress_current_elementor.json` - Test için kullanılan mevcut WordPress verisi

## 📞 Destek

Sorun yaşarsanız:
1. `info.md` dosyasını okuyun
2. Test endpoint'ini deneyin
3. WordPress debug log'larını kontrol edin
4. Python script log'larını kontrol edin

## 🎓 Öğrenilen Teknik Detaylar

### 1. WordPress REST API
- Custom endpoint'ler `register_rest_route` ile eklenir
- `permission_callback` ile authentication kontrol edilir
- `wp_set_current_user` ile user context ayarlanır

### 2. Elementor Yapısı
- Elementor JSON recursive bir yapıdır
- Her element `elType` ve `widgetType` alanlarına sahiptir
- Settings içinde widget'a özel ayarlar vardır

### 3. URL Normalizasyonu
- Trailing slash'ler normalize edilir
- Escaped formatlar desteklenir
- URL encoding desteklenir

### 4. Cache Yönetimi
- Elementor kendi cache sistemine sahiptir
- WordPress cache plugin'leri farklı API'ler kullanır
- Her cache sistemi için ayrı temizleme yapılır

---

**Son Güncelleme:** 2025-12-06
**Versiyon:** 1.0
**Geliştirici:** Rakip İçerik İstihbarat Sistemi V2

