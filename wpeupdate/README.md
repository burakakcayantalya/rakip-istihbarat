# WordPress Elementor İçerik Güncelleme Sistemi

Bu klasör, WordPress Elementor sayfalarındaki içerikleri programatik olarak güncellemek için gerekli tüm dosyaları içerir.

## 📁 Dosyalar

- **`sync_from_wordpress.py`** - WordPress'ten güncel Elementor JSON'unu çeker
- **`extract_content_from_elementor.py`** - Elementor JSON'dan içerikleri extract eder
- **`push_content_to_wordpress.py`** - Değişiklikleri WordPress'e push eder
- **`wordpress_functions_fix.php`** - WordPress'e eklenecek PHP kodu
- **`info.md`** - Detaylı dokümantasyon ve kullanım kılavuzu

## 🚀 Hızlı Başlangıç

1. **WordPress Kurulumu:**
   - `wordpress_functions_fix.php` dosyasının içeriğini WordPress `functions.php` dosyasına ekleyin
   - Application Password oluşturun

2. **Güncel Veriyi Çek:**
   ```bash
   python sync_from_wordpress.py
   ```

3. **İçeriği Düzenle:**
   - `elementor_content_extracted.json` dosyasını açın
   - İstediğiniz `content` veya `url` değerlerini değiştirin

4. **Değişiklikleri Push Et:**
   ```bash
   python push_content_to_wordpress.py
   ```

## 📖 Detaylı Bilgi

Tüm detaylar, öğrenilenler, endpoint'ler ve sorun çözümleri için **`info.md`** dosyasını okuyun.

## ⚠️ Önemli

- WordPress'e PHP kodunu eklemeden sistem çalışmaz
- Application Password gereklidir
- `info.md` dosyasını mutlaka okuyun

