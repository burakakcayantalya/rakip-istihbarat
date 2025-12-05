# 🕵️ Rakip İçerik İstihbarat Sistemi V2

Rakip sitelerin içerik değişikliklerini, aktivitelerini ve entity analizlerini takip eden kapsamlı bir istihbarat ve analiz platformu.

## 📋 İçindekiler

- [Genel Bakış](#genel-bakış)
- [Özellikler](#özellikler)
- [Teknolojiler](#teknolojiler)
- [Kurulum](#kurulum)
- [Kullanım](#kullanım)
- [Proje Yapısı](#proje-yapısı)
- [API Endpoints](#api-endpoints)
- [Yapılandırma](#yapılandırma)
- [Veritabanı](#veritabanı)

## 🎯 Genel Bakış

Bu sistem, rakip sitelerin içerik aktivitelerini otomatik olarak takip eder ve analiz eder. Sitemap'lerden URL'leri çıkarır, içerik değişikliklerini tespit eder, entity analizleri yapar ve detaylı raporlar sunar.

### Ana Kullanım Senaryoları

- **Rakip Takibi**: Rakip sitelerin yeni içerik ekleme ve güncelleme aktivitelerini takip etme
- **İçerik Analizi**: H1, Schema.org, internal link analizleri
- **Freshness Kontrolü**: Eski içerikleri tespit etme (45 gün kuralı)
- **Entity Analizi**: Meta title, description ve URL'lerden entity çıkarma ve Wikipedia ile eşleştirme
- **Aktivite Puanlama**: Sitelerin aktivite skorlarını hesaplama ve karşılaştırma

## ✨ Özellikler

### 1. Rakip Takip Modülü
- Otomatik sitemap tarama
- İçerik değişiklik tespiti (MD5 hash ile)
- Günlük aktivite grafikleri
- Sitemap `lastmod` tarihine göre aktivite takibi
- Renkli ve filtreli aktivite logları

### 2. Site Araçları
- **Detaylar**: Her URL için detaylı analiz (H1, Schema, Internal Links)
- **Freshness**: 45 gün kuralına göre eski içerik tespiti
- **Linkler**: Internal link analizi ve pagination
  - **Redirect Link Düzeltme**: WordPress REST API ile Elementor içeriklerindeki redirect linklerini otomatik düzeltme
  - **Elementor Native Replace**: Elementor'un kendi URL değiştirme mantığını kullanarak güvenli link güncelleme
  - **CSS Cache Temizleme**: Otomatik Elementor cache temizleme (CSS bozulmasını önler)
  - **Detaylı Log Ekranı**: Adım adım işlem logları ve gerçek zamanlı takip
  - **Expandable Redirect Detayları**: Redirect linkler için detaylı görünüm (kaynak sayfa, redirect URL, final URL, status kodları)
- Per-URL güncelleme butonu (cache-free analiz)
- Dinamik site menüleri
- **WordPress REST API Entegrasyonu**: Application Password ile güvenli bağlantı

### 3. Entity Analyzer
- **Çoklu AI Desteği**: Gemini AI veya Deepseek AI ile entity çıkarma
  - Gemini AI (rate limit: 250 req/day free tier)
  - Deepseek AI (RapidAPI üzerinden)
- Wikipedia API ile entity doğrulama
- Tam/Yarım/Düşük eşleşme kategorileri
- AI eşleşme kategorisi
- Google Search sonuçlarını dahil etme
- Duplicate temizleme (otomatik is_cleaned flag reset)
- Wikipedia manuel doğrulama (direkt API entegrasyonu)
- **Wikipedia Test**: Her entity için detaylı log ekranı ile Wikipedia API testi
- Entity listesi kopyalama (virgülle ayrılmış format)
- Rakip site entity dağılım analizi
- Arama sırasında AI provider seçimi (dropdown)
- **Not**: Büyük entity aramalarında AI quota limitine dikkat edin (429 hatası durumunda işlem durur)

### 4. Puanlama Sistemi
- Site aktivite skorları
- Günlük aktivite grafikleri
- Site bazlı renkli gösterim
- Filtreleme özellikleri
- "Bizim Sitemiz" ve rakip ayrımı

### 5. Entity Finder
- **Wikipedia Entity Bulma**: Anahtar kelime veya URL ile Wikipedia'dan entity bulma
- **Kategorilendirme**: Bulunan entity'ler otomatik olarak kategorilere ayrılır
  - cosmetic_dentistry
  - restorative_dentistry
  - preventive_dentistry
  - orthodontics
  - periodontics
  - endodontics
  - oral_surgery
  - prosthodontics
  - pediatric_dentistry
  - general_dentistry
- **Relevance Scoring**: Her entity için 0-100 arası ilgili olma skoru
- **Entity Listesi**: Tüm kategoriler ve entity'leri görüntüleme
- **Kategori Bazında Kopyalama**: Her kategori için entity'leri virgülle ayrılmış formatta kopyalama
- **Standart Mod**: Tüm internal linkleri toplar ve relevance score'a göre filtreler

### 6. AI Helper - Autonomous Internal Linking Agent
- **Otomatik Internal Link Önerileri**: AI destekli internal linking sistemi
- **Sayfa Bazlı Analiz**: Her sayfa HTML'i paragraflara bölünür ve analiz edilir
- **Paragraf Bazlı İşlem**: Sadece `<p>` tag'lerindeki paragraflar işlenir (başlıklar hariç)
- **Internal Link Kontrolü**: 
  - Sayfada 12'den fazla internal link varsa atlanır
  - Sadece internal link olmayan paragraflar AI'a gönderilir
  - Menu/footer linkleri sayılmaz
- **Elementor Temizleme**: Elementor widget kodları temizlenir, saf HTML AI'a gönderilir
- **Manuel Kümeleme**: URL'ler önceden tanımlı anahtar kelimelere göre kümelenir:
  - Crowns
  - Implant
  - Orthodontic (Root Canal dahil)
  - Veneer
  - Whitening
  - Dental Holiday
- **Gelişmiş Internal Linking Denetimi (Advanced Auditor)**:
  - **Hedef Cluster Yönetimi**: Her cluster için 4 tip hedef belirlenir:
    - Otorite Hedef
    - Tematik Hedef
    - Dolaylı Hedef
    - Zorunlu Hedef
  - **Kurallar**: 
    - Her URL'de 4 hedef cluster'a ait linkler olmalı
    - Cluster kendi kümesine ait minimum 4 internal link olmalı
    - Tüm kuralları karşılayan URL'ler "OK" olarak işaretlenir
- **URL Denetim Detayları Sayfası**:
  - Her URL için detaylı denetim sayfası
  - **Live Check**: Canlı HTML çekme ve link analizi
  - **Hedef Cluster Link Durumları**: Hangi cluster'lara link var/yok gösterimi
  - **Kendi Cluster Link Durumu**: Kendi cluster'ına ait link sayısı (X/4)
  - **AI'a Gönderilen HTML**: Dropdown ile AI'a gönderilen HTML versiyonunu görüntüleme ve kopyalama
  - **AI Önerileri**: Cluster'a göre gruplanmış öneriler ve before/after karşılaştırması
- **Cluster Yönetimi**:
  - Yeni cluster oluşturma
  - Cluster adı düzenleme
  - URL'leri cluster'lar arasında taşıma (tekli ve toplu)
  - Cluster silme
  - Hedef cluster'ları güncelleme
  - Dental Holiday
- **Gelişmiş Internal Linking Denetimi (Advanced Auditor)**:
  - **Hedef Cluster Yönetimi**: Her cluster için 4 tip hedef belirlenir:
    - Otorite Hedef
    - Tematik Hedef
    - Dolaylı Hedef
    - Zorunlu Hedef
  - **Kurallar**: 
    - Her URL'de 4 hedef cluster'a ait linkler olmalı
    - Cluster kendi kümesine ait minimum 4 internal link olmalı
    - Tüm kuralları karşılayan URL'ler "OK" olarak işaretlenir
- **URL Denetim Detayları Sayfası**:
  - Her URL için detaylı denetim sayfası
  - **Live Check**: Canlı HTML çekme ve link analizi
  - **Hedef Cluster Link Durumları**: Hangi cluster'lara link var/yok gösterimi
  - **Kendi Cluster Link Durumu**: Kendi cluster'ına ait link sayısı (X/4)
  - **AI'a Gönderilen HTML**: Dropdown ile AI'a gönderilen HTML versiyonunu görüntüleme ve kopyalama
  - **AI Önerileri**: Cluster'a göre gruplanmış öneriler ve before/after karşılaştırması
- **Cluster Yönetimi**:
  - Yeni cluster oluşturma
  - Cluster adı düzenleme
  - URL'leri cluster'lar arasında taşıma (tekli ve toplu)
  - Cluster silme
  - Hedef cluster'ları güncelleme
- **Küme Bazlı Denetim**: Her küme için ayrı "Denetle" butonu ile internal link kontrolü
- **AI Provider Seçimi**: Gemini AI veya Deepseek AI seçilebilir (küme denetimi için)
- **Retry Mekanizması**: 503, 429, 500 gibi geçici hatalar için otomatik retry (exponential backoff)
- **Periyodik Analiz**: Her 10 dakikada bir otomatik analiz (agresif değil)
- **Random Bekleme**: Paragraflar arasında 4-6 dakika random bekleme
- **Opportunity Yönetimi**:
  - Havuzdaki tüm opportunity'leri temizle
  - Checkbox ile toplu seçim ve silme
  - Orijinal paragraf ve AI önerisi (HTML) görüntüleme
- **Log İzleme**: Detaylı, renkli, filtreli log ekranı (real-time)
- **AI Prompt ve Response Loglama**: AI'a gönderilen prompt'lar ve alınan cevaplar log'da görünür

### 7. Dashboard
- Genel istatistikler
- Son aktiviteler
- Site sıralamaları
- Sistem durumu takibi

## 🛠 Teknolojiler

- **Backend**: FastAPI
- **Veritabanı**: SQLite (SQLAlchemy ORM)
- **Frontend**: Jinja2 Templates, Tailwind CSS, Alpine.js
- **Background Tasks**: APScheduler
- **HTTP Client**: httpx (async)
- **HTML Parsing**: BeautifulSoup4, lxml
- **AI Services**:
  - Google Gemini API
  - Deepseek AI (RapidAPI)
- **External APIs**: Wikipedia REST API, Google Search API (RapidAPI)

## 📦 Kurulum

### Gereksinimler

- Python 3.8+
- pip

### Adımlar

1. **Repository'yi klonlayın**
```bash
git clone <repository-url>
cd rakip-istihbarat
```

2. **Virtual environment oluşturun**
```bash
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# veya
venv\Scripts\activate  # Windows
```

3. **Bağımlılıkları yükleyin**
```bash
pip install -r requirements.txt
```

4. **Environment değişkenlerini ayarlayın**
`.env` dosyası oluşturun:
```env
# API Keys
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-flash-latest
DEEPSEEK_API_KEY=your_rapidapi_key_for_deepseek
DEEPSEEK_HOST=deepseek-all-in-one.p.rapidapi.com
RAPIDAPI_KEY=your_rapidapi_key
RAPIDAPI_HOST=google-search116.p.rapidapi.com

# Server
HOST=0.0.0.0
PORT=8000
DEBUG=true
```

5. **Uygulamayı başlatın**
```bash
python main.py
```

6. **Tarayıcıda açın**
```
http://localhost:8000
```

## 🚀 Kullanım

### İlk Kurulum

1. **Site Ekleme**: "Rakip Takip" > "Siteler" menüsünden rakip siteleri ekleyin
2. **Sitemap URL**: Her site için sitemap URL'sini girin
3. **İlk Tarama**: Sistem otomatik olarak sitemap'leri tarayacak

### Rakip Takip

- **Siteler**: Eklenen siteleri görüntüleme ve yönetme
- **Değişiklik Logları**: İçerik değişikliklerini görüntüleme
- **Puanlama**: Site aktivite skorlarını ve grafiklerini görüntüleme

### Site Araçları

- Her "Bizim Sitemiz" için:
  - **Detaylar**: URL bazlı detaylı analiz
  - **Freshness**: Eski içerik tespiti
  - **Linkler**: Internal link analizi
    - **Redirect Link Düzeltme**: 
      1. WordPress REST API ayarlarını yapın (URL, Kullanıcı Adı, Application Password)
      2. Redirect linklerini görüntüleyin (detaylı expandable görünüm)
      3. "Otomatik Düzelt" butonu ile linkleri düzeltin
      4. Log ekranından işlemi takip edin
    - **WordPress PHP Endpoint**: `wordpress_custom_endpoint.php` dosyasını WordPress `functions.php` dosyasına ekleyin

### Entity Analyzer

1. **Yeni Arama**: "Araçlar" > "Entity Arama" menüsünden yeni entity araması başlatın
2. **AI Provider Seçimi**: Dropdown'dan Gemini AI veya Deepseek AI seçin
3. **Arama Terimi**: Örn: "hollywood", "istanbul", "dental"
4. **Sonuçları İncele**: Tam/Yarım/Düşük/AI eşleşmeleri görüntüleyin
5. **Temizleme**: "Aynı Entity'leri Temizle" butonu ile duplicate'leri temizleyin
6. **Wikipedia Check**: Temizlik sonrası Wikipedia doğrulaması yapın (direkt API entegrasyonu ile)
7. **Entity Kopyalama**: "Entity'leri Kopyala" butonu ile tüm unique entity'leri virgülle ayrılmış formatta panoya kopyalayın
8. **Güncelleme**: Arama güncellendikten sonra temizlik butonu otomatik olarak aktif hale gelir

### Entity Finder

1. **Yeni Arama**: "Araçlar" > "Entity Bul" menüsünden yeni entity bulma araması başlatın
2. **Arama Yöntemi**: Anahtar kelime veya Wikipedia URL ile arama yapın
   - **Anahtar Kelime**: Örn: "dentistry", "dental implant"
   - **Wikipedia URL**: Örn: `https://en.wikipedia.org/wiki/Dentistry`
3. **Maksimum Link Sayısı**: Kontrol edilecek internal link sayısını belirleyin (10-500 arası)
4. **Sonuçları İncele**: Detay sayfasında kategorilere göre gruplanmış entity'leri görüntüleyin
5. **Entity Listesi**: "Araçlar" > "Entity Listesi" menüsünden tüm kategorileri ve entity'leri görüntüleyin
6. **Kategori Kopyalama**: Her kategori için "Kopyala" butonu ile entity'leri virgülle ayrılmış formatta panoya kopyalayın

## 📁 Proje Yapısı

```
rakip-istihbarat/
├── main.py                 # Ana uygulama giriş noktası
├── config.py               # Yapılandırma ayarları
├── requirements.txt        # Python bağımlılıkları
├── .env                    # Environment değişkenleri (oluşturulmalı)
│
├── core/                   # Çekirdek modüller
│   ├── database.py         # Veritabanı modelleri ve bağlantı
│   ├── scheduler.py        # Arka plan görevleri ve tarama
│   ├── scraper.py          # Web scraping ve sitemap parsing
│   └── scoring.py          # Puanlama algoritması
│
├── routers/                # API route'ları
│   ├── dashboard.py        # Dashboard endpoint'leri
│   ├── sites.py            # Site yönetimi
│   ├── logs.py             # Log görüntüleme
│   ├── puanlama.py         # Puanlama sayfası
│   ├── settings.py         # Ayarlar sayfası
│   └── system.py           # Sistem yönetimi (restart)
│
├── site_tools/             # Site araçları modülü
│   ├── router.py           # Site tools endpoint'leri
│   ├── models.py           # Site tools veritabanı modelleri
│   ├── analyzer.py         # Link analizi ve HTTP status kontrolü
│   ├── wordpress_api_fix.py # WordPress REST API ile link düzeltme
│   ├── wordpress_custom_endpoint.php # WordPress PHP endpoint kodu
│   └── templates/          # Site tools HTML şablonları
│
├── entity_analyzer/        # Entity analiz modülü
│   ├── router.py           # Entity analyzer endpoint'leri
│   ├── models.py           # Entity analyzer veritabanı modelleri
│   ├── analyzer.py         # Wikipedia API ve entity matching
│   └── templates/          # Entity analyzer HTML şablonları
│
├── entity_finder/          # Entity bulma modülü
│   ├── router.py           # Entity finder endpoint'leri
│   ├── models.py           # Entity finder veritabanı modelleri
│   ├── finder.py           # Wikipedia scraping ve entity bulma
│   └── templates/          # Entity finder HTML şablonları
│
├── ai_helper/             # AI Helper - Internal Linking Agent
│   ├── router.py           # AI Helper endpoint'leri
│   ├── models.py           # AI Helper veritabanı modelleri
│   ├── strategist.py       # Sitemap analizi ve kümeleme
│   ├── page_analyzer.py    # Sayfa bazlı, paragraf bazlı analiz
│   ├── advanced_auditor.py # Gelişmiş internal linking denetimi
│   ├── editor.py           # AI contextual link injection
│   ├── scheduler.py         # Haftalık batch oluşturma
│   ├── periodic_analyzer.py # Periyodik analiz (her 10 dakika)
│   └── templates/          # AI Helper HTML şablonları
│       ├── url_audit_details.html # URL denetim detayları sayfası
│
├── services/               # Harici servisler
│   ├── gemini_ai.py        # Google Gemini AI entegrasyonu
│   ├── deepseek_ai.py      # Deepseek AI entegrasyonu (RapidAPI)
│   └── google_search.py    # Google Search API entegrasyonu
│
└── templates/              # HTML şablonları
    ├── base.html           # Ana layout şablonu
    ├── dashboard.html      # Dashboard sayfası
    └── ...                 # Diğer sayfa şablonları
```

## 🔌 API Endpoints

### Dashboard
- `GET /` - Ana dashboard sayfası
- `GET /api/stats` - İstatistikler (JSON)
- `GET /api/recent-activity` - Son aktiviteler
- `GET /api/rankings` - Site sıralamaları

### Sites
- `GET /sites` - Site listesi
- `POST /sites/add` - Yeni site ekle
- `GET /sites/{site_id}` - Site detayları

### Entity Analyzer
- `GET /entity-analyzer` - Entity analyzer ana sayfası
- `POST /entity-analyzer/search` - Yeni entity araması başlat
- `GET /entity-analyzer/search/{search_id}` - Arama detayları
- `POST /entity-analyzer/search/{search_id}/clean-duplicates` - Duplicate temizleme (is_cleaned flag otomatik güncelleme)
- `POST /entity-analyzer/search/{search_id}/wikipedia-check` - Wikipedia doğrulama (direkt API entegrasyonu)
- `POST /entity-analyzer/entity/{entity_id}/test-wikipedia` - Tek entity için detaylı Wikipedia testi ve loglama
- `GET /entity-analyzer/search/{search_id}/entities-list` - Tüm unique entity'leri virgülle ayrılmış liste olarak al
- `GET /entity-analyzer/api/search/{search_id}/logs` - Arama logları

### Entity Finder
- `GET /entity-finder` - Entity finder ana sayfası
- `POST /entity-finder/search` - Yeni entity bulma araması başlat (keyword veya Wikipedia URL)
- `GET /entity-finder/search/{finder_id}` - Arama detayları
- `GET /entity-finder/list` - Tüm kategoriler ve entity'leri listele
- `GET /entity-finder/api/category/{category_name}/entities` - Kategori entity'lerini virgülle ayrılmış liste olarak al
- `DELETE /entity-finder/search/{finder_id}` - Arama kaydını sil

### AI Helper
- `GET /ai-helper` - AI Helper ana sayfası (proje listesi)
- `GET /ai-helper/project/{project_id}/url/audit-details?url={url}` - URL denetim detayları sayfası (live check ile)
- `PUT /ai-helper/project/{project_id}/cluster/{cluster_id}/update-targets` - Cluster hedef güncelleme (Otorite, Tematik, Dolaylı, Zorunlu)
- `POST /ai-helper/project/create` - Yeni proje oluştur
- `GET /ai-helper/project/{project_id}` - Proje dashboard'u
- `GET /ai-helper/project/{project_id}/clusters` - Küme listesi
- `GET /ai-helper/project/{project_id}/opportunities` - Opportunity listesi (filtreli)
- `POST /ai-helper/project/{project_id}/start-analysis` - Analizi başlat
- `POST /ai-helper/project/{project_id}/recluster` - Tekrar kümelendir
- `POST /ai-helper/project/{project_id}/cluster/{cluster_id}/audit` - Küme denetimi (AI provider seçimi ile)
- `GET /ai-helper/project/{project_id}/logs` - Proje logları (JSON)
- `GET /ai-helper/project/{project_id}/approval/{opportunity_id}` - Opportunity onay sayfası
- `POST /ai-helper/opportunity/{opportunity_id}/approve` - Opportunity onayla
- `POST /ai-helper/opportunity/{opportunity_id}/reject` - Opportunity reddet
- `DELETE /ai-helper/opportunity/{opportunity_id}` - Opportunity sil
- `DELETE /ai-helper/project/{project_id}/opportunities/clear-pool` - Havuzdaki tüm opportunity'leri sil
- `DELETE /ai-helper/project/{project_id}/opportunities/bulk-delete` - Seçili opportunity'leri toplu sil
- `DELETE /ai-helper/project/{project_id}` - Proje sil

### Site Tools
- `GET /site-tools/site/{site_id}` - Site detayları
- `GET /site-tools/freshness/{site_id}` - Freshness raporu
- `GET /site-tools/links/{site_id}` - Link analizi
- `POST /site-tools/update/{page_id}` - Tek URL güncelleme
- `POST /site-tools/site/{site_id}/wordpress-api-settings` - WordPress REST API ayarlarını kaydet
- `POST /site-tools/site/{site_id}/test-wordpress-api` - WordPress REST API bağlantısını test et
- `POST /site-tools/fix-redirect` - Redirect linkini otomatik düzelt

### System
- `POST /api/system/restart` - Sistem yeniden başlatma (cache temizleme)

## ⚙️ Yapılandırma

### Environment Variables (.env)

```env
# Uygulama
APP_NAME=Rakip İstihbarat Sistemi
DEBUG=true
SECRET_KEY=your-secret-key-here

# Sunucu
HOST=0.0.0.0
PORT=8000

# Veritabanı
DATABASE_URL=sqlite:///./database.db

# API Keys
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-flash-latest  # Önerilen: gemini-flash-latest (free tier: 250 req/day)
DEEPSEEK_API_KEY=your_rapidapi_key_for_deepseek
DEEPSEEK_HOST=deepseek-all-in-one.p.rapidapi.com
RAPIDAPI_KEY=your_rapidapi_key
RAPIDAPI_HOST=google-search116.p.rapidapi.com

# Tarama Ayarları
SCAN_INTERVAL_HOURS=6
CHANGE_THRESHOLD_PERCENT=5
MAX_CONCURRENT_SCANS=3
REQUEST_DELAY_SECONDS=2
```

### Ayarlar Sayfası

Uygulama içinden "Ayarlar" menüsünden şu değerler güncellenebilir:
- Gemini API Key
- Gemini Model (varsayılan: `gemini-flash-latest`)
- Deepseek API Key (RapidAPI)
- Deepseek Host
- RapidAPI Key
- RapidAPI Host

**AI API Limitleri:**

**Gemini AI:**
- **Free Tier**: 250 istek/gün (model başına)
- **Rate Limit**: Saniyede ~15 istek
- **Önerilen Model**: `gemini-flash-latest` (hızlı ve ücretsiz)
- **Quota Aşımı**: 429 hatası alırsanız, belirtilen süre kadar bekleyin veya plan yükseltin

**Deepseek AI (RapidAPI):**
- **RapidAPI Üzerinden**: Plan bazlı limitler
- **Hızlı ve Güvenilir**: RapidAPI altyapısı
- **Alternatif AI**: Gemini quota dolduğunda kullanılabilir

## 🗄️ Veritabanı

### Ana Tablolar

- **sites**: Takip edilen siteler
- **pages**: Site sayfaları ve içerikleri
- **logs**: İçerik değişiklik logları
- **scan_jobs**: Tarama işleri
- **settings**: Sistem ayarları

### Entity Analyzer Tabloları

- **entity_searches**: Entity arama kayıtları
- **entity_results**: Entity eşleşme sonuçları
- **entity_search_logs**: Entity arama logları

### Entity Finder Tabloları

- **entity_finders**: Entity bulma aramaları
- **found_entities**: Bulunan entity'ler (kategori, relevance_score, source_section)
- **entity_categories**: Entity kategorileri ve sayıları

### AI Helper Tabloları

- **ai_helper_projects**: AI Helper projeleri (site bazlı)
- **ai_helper_clusters**: Semantic kümeler (implant, veneer, vb.)
  - `authority_target_cluster_id`: Otorite hedef cluster ID
  - `thematic_target_cluster_id`: Tematik hedef cluster ID
  - `indirect_target_cluster_id`: Dolaylı hedef cluster ID
  - `mandatory_target_cluster_id`: Zorunlu hedef cluster ID
- **ai_helper_opportunities**: Internal linking fırsatları (gap'ler)
  - `html_snippet`: AI'ın önerdiği HTML kodu (Elementor widget'e direkt koyulacak)
  - `paragraph_index`: Paragraf sırası
  - `original_paragraph`: Orijinal paragraf metni
  - `internal_link_status`: Internal link durumu (OK, PENDING, MISSING)
- **ai_helper_batches**: Haftalık batch'ler
- **ai_helper_proposals**: AI önerileri (before/after HTML)
- **ai_helper_logs**: Proje logları (detaylı, renkli, filtreli)

### Site Tools Tabloları

- **site_analysis**: Site analiz sonuçları
- **page_analysis**: Sayfa analiz sonuçları
- **internal_links**: Internal link analiz sonuçları (OK, Redirect, Broken)
  - `final_status_code`: Redirect sonrası final URL'nin HTTP status kodu

### Migration

Sistem otomatik migration yapar. Yeni kolonlar ve tablolar uygulama başlatıldığında otomatik olarak oluşturulur.

## 🔄 Çalışma Mantığı

### 1. Sitemap Tarama
- Her site için sitemap URL'si parse edilir
- URL'ler ve `lastmod` tarihleri veritabanına kaydedilir
- Yeni URL'ler için içerik çekilir

### 2. İçerik Değişiklik Tespiti
- Her sayfa için MD5 hash hesaplanır
- Önceki hash ile karşılaştırılır
- Değişiklik varsa log kaydı oluşturulur

### 3. Freshness Hesaplama
- Sitemap'teki `lastmod` tarihi kullanılır
- Bugünün tarihi ile karşılaştırılır
- 45 günden eski içerikler "stale" olarak işaretlenir

### 4. Entity Analizi (Entity Analyzer)
- Kullanıcı seçimine göre Gemini AI veya Deepseek AI ile entity'ler çıkarılır
- Her entity Wikipedia REST API ile direkt doğrulanır
- Eşleşme skoruna göre kategorize edilir (Tam/Yarım/Düşük)
- AI tarafından bulunan entity'ler ayrı işaretlenir
- Duplicate entity'ler otomatik temizlenir
- Temizlenmiş entity listesi tek tıkla panoya kopyalanabilir
- AI provider seçimi arama formunda yapılır

### 5. Entity Bulma (Entity Finder)
- Wikipedia sayfasından internal linkler çıkarılır
- Her link için Wikipedia API'den entity bilgileri alınır
- Relevance score hesaplanır (0-100 arası)
- Entity'ler otomatik olarak dental kategorilerine ayrılır
- Kategori bazında entity listesi oluşturulur
- Her kategori için entity'ler virgülle ayrılmış formatta kopyalanabilir

### 5. Aktivite Puanlama
- Sitemap `lastmod` tarihine göre aktivite hesaplanır
- Yeni içerik ve güncellemeler ayrı ayrı sayılır
- Site bazlı skorlar hesaplanır

### 6. AI Helper - Internal Linking
- **Sitemap Analizi**: Sitemap'ten tüm URL'ler çıkarılır
- **Manuel Kümeleme**: URL'ler önceden tanımlı anahtar kelimelere göre kümelenir
- **Sayfa Bazlı Analiz**: Her sayfa HTML'i alınır ve paragraflara bölünür
- **Paragraf Filtreleme**: 
  - Sadece `<p>` tag'leri işlenir (başlıklar hariç)
  - Internal link olmayan paragraflar seçilir
  - 12'den fazla internal link varsa sayfa atlanır
- **Elementor Temizleme**: Elementor widget kodları temizlenir, saf HTML AI'a gönderilir
- **AI Analizi**: Her paragraf için AI'a gönderilir ve internal link önerileri alınır
- **Random Bekleme**: Paragraflar arasında 4-6 dakika random bekleme
- **Retry Mekanizması**: 503, 429, 500 hataları için otomatik retry (exponential backoff)
- **Opportunity Oluşturma**: AI önerileri opportunity olarak havuza atılır
- **Periyodik Analiz**: Her 10 dakikada bir otomatik analiz (agresif değil)

## 📊 Önemli Notlar

### Sitemap Lastmod Kullanımı
Sistem, içerik aktivitesini hesaplarken **sitemap'teki `lastmod` tarihini** kullanır. Bu, içeriğin gerçek güncellenme tarihini yansıtır.

### Cache-Free Analiz
Site Tools'da her URL için "Güncelle" butonu ile cache olmadan anlık analiz yapılabilir.

### Background Tasks
Uzun süren işlemler (entity analizi, sitemap tarama) arka planda çalışır. İlerleme log ekranından takip edilebilir.

### Duplicate Temizleme ve Entity Kopyalama
- Entity Analyzer'da aynı entity'yi farklı sitelerden bulmuşsa, "Aynı Entity'leri Temizle" butonu ile tekrar edenler temizlenebilir
- Temizlik yapıldıktan sonra "Wikipedia Check" butonu ile entity'ler Wikipedia'da doğrulanabilir
- "Entity'leri Kopyala" butonu ile tüm unique entity'ler virgülle ayrılmış formatta panoya kopyalanır
- Arama güncellendikten sonra `is_cleaned` flag'i otomatik resetlenir ve temizlik tekrar yapılabilir

## 🐛 Sorun Giderme

### WordPress REST API Bağlantı Sorunları
- **401 Unauthorized Hatası**: 
  - Application Password'ün doğru girildiğinden emin olun (boşluklar dahil)
  - WordPress 5.6+ sürümü gerekir (Application Password desteği için)
  - Kullanıcının `edit_posts` yetkisi olmalı (Editor veya Administrator)
- **Endpoint Bulunamadı (404)**:
  - `wordpress_custom_endpoint.php` dosyasını WordPress `functions.php` dosyasına eklediğinizden emin olun
  - WordPress cache'ini temizleyin
  - Permalink'leri yeniden kaydedin (Ayarlar → Kalıcı Bağlantılar)
- **Elementor Data Bulunamadı**:
  - `register_rest_field` kodu WordPress'e eklenmiş olmalı
  - Post ID'nin doğru olduğundan emin olun
  - Elementor'un aktif olduğundan emin olun

### Dashboard Boş Görünüyor
- Veritabanında `sitemap_lastmod` kolonu eksik olabilir
- Uygulamayı yeniden başlatın (migration otomatik çalışacak)
- Konsol loglarını kontrol edin

### Entity Analyzer Sayfası Boş
- `is_cleaned` kolonu eksik olabilir
- Uygulamayı yeniden başlatın
- Migration otomatik çalışacak

### Wikipedia Eşleşmesi Bulunamıyor
- Entity kelimelerinde tek tırnak (`'`) veya özel karakterler olabilir
- Sistem otomatik temizler, ancak manuel kontrol edebilirsiniz
- Wikipedia Check özelliği direkt Wikipedia REST API kullanır, metin eşleştirme sorunu yoktur

### Entity Kopyalama Çalışmıyor
- Tarayıcınızın Clipboard API'yi desteklediğinden emin olun
- HTTPS bağlantısı veya localhost üzerinden çalışıyor olmalısınız
- Sistem otomatik olarak fallback yöntemi dener (textarea+execCommand)

### Temizlik Butonu Görünmüyor
- Entity arama güncellendikten sonra `is_cleaned` flag'i otomatik resetlenir
- Uygulamayı yeniden başlatmayı deneyin
- Veritabanında `is_cleaned` kolonu olduğundan emin olun

### Entity Analyzer Butonları Çalışmıyor
- **Hata**: `Uncaught SyntaxError: Illegal return statement` veya `Uncaught ReferenceError: function is not defined`
- **Neden**: JavaScript syntax hataları veya scope sorunları
- **Çözüm**: 
  - Sayfayı hard refresh yapın (Ctrl+Shift+R veya Cmd+Shift+R)
  - Tarayıcı console'unu kontrol edin (F12 → Console)
  - Tüm JavaScript kodları ES5 syntax ile yazılmıştır ve `window` objesine bağlıdır
  - Butonlar `window.functionName(...)` formatında çağrılır
- **Not**: Sistem tüm butonları (Aynı Entity'leri Temizle, Test Wikipedia, Wikipedia Check, Güncelle, İptal Et, Filtre butonları) global scope'ta tanımlar

### AI Helper - 503 Service Unavailable Hatası
- **Hata**: `503 Service Unavailable` veya `429 Rate Limit`
- **Neden**: AI API (Gemini/Deepseek) geçici olarak kullanılamıyor veya rate limit'e takıldı
- **Çözüm**: 
  - Sistem otomatik retry yapar (maksimum 3 deneme)
  - Exponential backoff: 1s, 2s, 4s bekleme
  - Log ekranından retry durumunu takip edebilirsiniz
  - Tüm denemeler başarısız olursa hata loglanır ve işlem durur
- **Not**: Geçici hatalar (503, 429, 500) otomatik olarak yeniden denenecek

### AI Helper - Internal Link Kontrolü
- **Kural**: Sayfada 12'den fazla internal link varsa sayfa atlanır
- **Kural**: Sadece `<p>` tag'lerindeki paragraflar işlenir (başlıklar hariç)
- **Kural**: Başlıklar (H1-H6) işlemden muaf, AI'a gönderilmez
- **Not**: Menu/footer linkleri sayılmaz, sadece içerik alanındaki linkler sayılır

### Gemini API Quota Hatası (429)
- **Hata**: `429 RESOURCE_EXHAUSTED` - Quota exceeded
- **Neden**: Gemini API'nin günlük istek limitine ulaşıldı
- **Free Tier Limit**: 250 istek/gün (model başına)
- **Çözümler**:
  1. **Bekleme**: Hata mesajında belirtilen süre kadar bekleyin (genellikle 30-60 saniye)
  2. **Rate Limiting**: Entity Analyzer'da çok sayıda kaynak analiz ederken batch'ler halinde işlem yapın
  3. **API Plan Yükseltme**: Google Cloud Console'dan daha yüksek quota planına geçin
  4. **Alternatif Model**: Farklı bir Gemini modeli kullanın (ayarlardan değiştirilebilir)
  5. **Manuel Kontrol**: Büyük entity aramaları için kaynak sayısını sınırlayın
- **Not**: Sistem 429 hatası aldığında işlemi durdurur ve log'a kaydeder. Hata sonrası fallback mekanizması devreye girer (Wikipedia doğrulama olmadan devam eder)

## 🤖 Agent Sistemi - Otomatik SEO Sorun Çözümü

Sistem, SEO sorunlarını tespit eden, önceliklendiren, düzelten ve doğrulayan **otonom agentlar** içeren bir **mikroservis mimarisi** kullanır. Her agent kendi sorumluluğuna odaklanır ve diğer agentlarla **asenkron haberleşme** yapar.

### Agent Mimarisi

```
┌─────────────────────────────────────────────────────────────┐
│                    REPORTER AGENT                            │
│  (Tüm görevlerin hikayesini gösterir, log yönetimi)          │
└─────────────────────────────────────────────────────────────┘
                            ▲
                            │ (Görüntüleme)
                            │
┌─────────────────────────────────────────────────────────────┐
│                    CONTROLLER AGENT                          │
│  (Görev tamamlandı mı? Doğrula! 5 dakika gecikme ile)        │
└─────────────────────────────────────────────────────────────┘
         ▲                              │
         │ (Tamamlandı bildirimi)       │ (Doğrulama isteği)
         │                              ▼
┌────────────────────┐      ┌──────────────────────────────┐
│  LINK FIXER        │      │      OBSERVER AGENT          │
│  (Link düzeltir)   │      │  (SEO sorunlarını tespit eder)│
└────────────────────┘      └──────────────────────────────┘
         ▲                              │
         │ (Görev atama)                 │ (Raporlar)
         │                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    DISPATCHER AGENT                          │
│  (Görevleri uygun agent'a yönlendirir)                      │
└─────────────────────────────────────────────────────────────┘
         ▲                              │
         │ (Görev oluştur)              │ (Önceliklendirilmiş görevler)
         │                              │
┌─────────────────────────────────────────────────────────────┐
│                    REVIEWER AGENT                            │
│  (Raporları önceliklendirir ve aksiyon planı oluşturur)     │
└─────────────────────────────────────────────────────────────┘
         ▲
         │ (Raporlar)
         │
┌─────────────────────────────────────────────────────────────┐
│                    OBSERVER AGENT                            │
│  (SEO sorunlarını tespit eder ve raporlar)                  │
└─────────────────────────────────────────────────────────────┘
```

### Agent Detayları ve Görevleri

#### 1. OBSERVER AGENT
**Görevi:** SEO sorunlarını tespit etmek ve raporlamak

**Yapabilecekleri:**
- ✅ Full Audit (H1, Schema, Link kontrolü)
- ✅ Link Audit (Kırık linkler, redirect'ler)
- ✅ Freshness Check (Eski içerik tespiti)
- ✅ Duplicate Link Check
- ✅ Schema Check
- ✅ H1 Check
- ✅ Controller Doğrulama (sadece belirtilen sayfayı kontrol eder, cache temizler)

**Çıktıları:**
- `ObserverTask`: Görev kaydı
- `ObserverReport`: Tespit edilen sorunlar

**Haberleşme:**
- **Girdi:** Manuel görev oluşturma veya Controller'dan doğrulama görevi
- **Çıktı:** ObserverReport → Reviewer'a otomatik gönderilir (Controller doğrulaması değilse)

**Önemli Özellikler:**
- Controller doğrulaması için sadece belirtilen sayfayı kontrol eder
- Normal görevlerde tüm site'ı tarar
- Controller doğrulaması sırasında cache'i temizler (fresh scan için)
- `already_fixed` flag'i ile manuel düzeltilmiş linkleri algılar

---

#### 2. REVIEWER AGENT
**Görevi:** Observer raporlarını önceliklendirmek ve aksiyon planı oluşturmak

**Yapabilecekleri:**
- ✅ ObserverReport'ları öncelik skoruna göre sıralar
- ✅ Action plan belirler (FIX_LINK, ANALYZE_DUPLICATE_LINKS, vb.)
- ✅ ReviewerQueue'ya ekler

**Çıktıları:**
- `ReviewerQueue`: Önceliklendirilmiş görevler

**Haberleşme:**
- **Girdi:** ObserverReport (Observer'dan otomatik)
- **Çıktı:** ReviewerQueue → Dispatcher'a gönderilir

**Öncelik Skorları:**
- ERROR seviyesi: 100 puan
- WARNING seviyesi: 50 puan
- Kural bazlı ek puanlar

---

#### 3. DISPATCHER AGENT
**Görevi:** Görevleri uygun agent'a yönlendirmek

**Yapabilecekleri:**
- ✅ ReviewerQueue'dan görevleri alır
- ✅ Görev tipine göre agent belirler (routing rules)
- ✅ DispatcherTask oluşturur
- ✅ Agent'a görev atar
- ✅ Retry görevleri oluşturur (Controller'dan gelen başarısız doğrulamalar için)

**Routing Rules:**
- `FIX_LINK`, `FIX_301_LINK`, `FIX_404_LINK`, vb. → **FIXER**
- `ANALYZE_DUPLICATE_LINKS` → **AI_HELPER**

**Çıktıları:**
- `DispatcherTask`: Görev kaydı
- Agent'a özel task (LinkFixTask veya AIHelperOpportunity)

**Haberleşme:**
- **Girdi:** ReviewerQueue veya Controller retry görevi
- **Çıktı:** Link Fixer veya AI Helper'a görev atama

**Önemli Özellikler:**
- `old_url` ve `new_url` bilgilerini ControllerTask'tan veya ObserverReport'tan çıkarır
- Retry görevlerinde `old_url` kaybını önler
- `global_task_id`'yi korur (görev hiyerarşisi için)

---

#### 4. LINK FIXER AGENT
**Görevi:** Kırık linkleri ve redirect'leri düzeltmek

**Yapabilecekleri:**
- ✅ WordPress REST API ile Elementor içeriğini günceller
- ✅ Custom PHP endpoint kullanır (`/wp-json/custom/v1/elementor-native-replace`)
- ✅ Application Password authentication
- ✅ Escaped URL formatlarını algılar ve işler
- ✅ Manuel düzeltilmiş linkleri tespit eder (`already_fixed` flag)
- ✅ WordPress cache temizleme (Elementor, object cache, plugin cache'leri)

**Çıktıları:**
- `LinkFixTask`: Görev kaydı
- WordPress post güncelleme (cache temizleme için)

**Haberleşme:**
- **Girdi:** DispatcherTask (Dispatcher'dan)
- **Çıktı:** Controller'a tamamlandı bildirimi (`already_fixed` flag ile)

**WordPress Entegrasyonu:**
- Sadece custom PHP endpoint kullanır (güvenli ve hızlı)
- Application Password ile authentication
- Elementor JSON verisini doğrudan PHP tarafında günceller
- Tüm URL formatlarını destekler (escaped, encoded, href formatları)

**Elementor Link Sorunu Çözümü:**

Elementor içeriklerinde URL'ler farklı formatlarda saklanabilir:
- **Normal format**: `https://example.com/page/`
- **Escaped format**: `https:\/\/example.com\/page\/` (JSON'da yaygın)
- **Escaped quotes**: `href=\"https://example.com/page/\"` (JSON encoded)
- **Escaped quotes + slashes**: `href=\"https:\/\/example.com\/page\/\"` (en karmaşık format)
- **URL encoded**: `https%3A%2F%2Fexample.com%2Fpage%2F`
- **Trailing slash varyasyonları**: `/` ile veya `/` olmadan

**Çözüm Yaklaşımı:**

1. **PHP Endpoint (wordpress_functions_fix.php):**
   - Tüm URL formatlarını destekleyen pattern listesi
   - `href="..."`, `href=\"...\"`, `"url":"..."` formatlarını işler
   - Escaped slashes (`\/`) ve escaped quotes (`\"`) desteği
   - Trailing slash normalizasyonu
   - URL encode edilmiş versiyonlar

2. **Python Link Fixer (wordpress_fixer.py):**
   - PHP endpoint'ine sadece `old_url` ve `new_url` gönderir
   - Endpoint'ten `changes_count` alır
   - Eğer `changes_count = 0` ise, sayfayı kontrol eder:
     - Tüm URL variant'larını kontrol eder (escaped, encoded, href formatları)
     - `new_url` bulunursa ve `old_url` bulunamazsa → `already_fixed: True`
     - Bu durum Observer'a bildirilir

3. **URL Variant Kontrolü:**
   ```python
   # Örnek: old_url = "https://example.com/page/"
   old_url_variants = [
       "https://example.com/page/",           # Orijinal
       "https://example.com/page",             # Trailing slash yok
       "https:\\/\\/example.com\\/page\\/",   # Escaped slashes
       "href=\"https://example.com/page/\"",   # Escaped quotes
       "href=\"https:\\/\\/example.com\\/page\\/\"",  # Escaped quotes + slashes ✅
       "\"url\":\"https://example.com/page/\"", # JSON format
       # ... ve daha fazlası
   ]
   ```

**Bağımlılıklar:**
- `httpx`: Async HTTP client (WordPress REST API için)
- `json`: JSON parsing (Elementor data için)
- `urllib.parse`: URL encoding/decoding

---

#### 5. CONTROLLER AGENT
**Görevi:** Tamamlanan görevleri doğrulamak

**Yapabilecekleri:**
- ✅ Agent'lardan tamamlanma bildirimi alır
- ✅ 5 dakika gecikme ile Observer'a doğrulama görevi gönderir (WordPress cache için)
- ✅ Observer sonucunu bekler
- ✅ Başarılı ise → `VERIFIED_SUCCESS`
- ✅ Başarısız ise → `VERIFIED_FAILED` ve Dispatcher'a retry görevi gönderir
- ✅ `already_fixed` flag'ini Observer'a iletir

**Çıktıları:**
- `ControllerTask`: Doğrulama görev kaydı
- Observer'a doğrulama görevi
- Dispatcher'a retry görevi (başarısız durumda)

**Haberleşme:**
- **Girdi:** Link Fixer veya AI Helper'dan tamamlanma bildirimi
- **Çıktı:** Observer'a doğrulama görevi (5 dakika gecikme ile)
- **Çıktı:** Dispatcher'a retry görevi (başarısız doğrulama için)

**Önemli Özellikler:**
- 5 dakika gecikme: WordPress cache ve Elementor CSS/JS regeneration için
- `old_url` ve `new_url` bilgilerini Observer'a iletir
- `already_fixed` flag'ini Observer'a iletir (özel kontrol için)
- Retry görevlerinde `old_url` kaybını önler

---

#### 6. REPORTER AGENT
**Görevi:** Tüm agent aktivitelerini görüntülemek ve log yönetimi

**Yapabilecekleri:**
- ✅ Tüm agent loglarını görüntüler
- ✅ Logları `global_task_id`'ye göre gruplar
- ✅ Task ID, Type, Status, Log Count gösterimi
- ✅ Logları en eski en üstte, en yeni en altta gösterir
- ✅ Tüm logları silme özelliği (veritabanından kalıcı silme)

**Çıktıları:**
- Reporter Dashboard: Gruplanmış log görünümü
- Task bazlı log grupları

**Haberleşme:**
- **Girdi:** Tüm agentlardan log mesajları
- **Çıktı:** Dashboard görünümü

---

### Görev Akışı (Workflow)

#### Senaryo: Redirect Link Düzeltme

```
1. OBSERVER
   ├─ Redirect link tespit eder (301, 302, vb.)
   └─ ObserverReport oluşturur
      └─ rule_name: "BROKEN_LINK" veya "REDIRECT_LINK"

2. REVIEWER
   ├─ ObserverReport'u önceliklendirir
   ├─ Action plan: FIX_LINK
   └─ ReviewerQueue'ya ekler

3. DISPATCHER (Otomatik - 30 saniyede bir)
   ├─ ReviewerQueue'dan görevleri alır
   ├─ Görev tipine göre agent belirler (FIX_LINK → FIXER)
   ├─ DispatcherTask oluşturur
   └─ Link Fixer'a görev atar

4. LINK FIXER
   ├─ DispatcherTask'ı alır
   ├─ WordPress custom endpoint'i çağırır
   │  └─ Tüm URL formatlarını işler (escaped, encoded, href formatları)
   ├─ WordPress cache temizler
   ├─ LinkFixTask oluşturur
   └─ Controller'a tamamlandı bildirimi gönderir
      └─ already_fixed flag'i ile (eğer link zaten düzeltilmişse)

5. CONTROLLER (Otomatik - 45 saniyede bir)
   ├─ Tamamlandı bildirimini alır
   ├─ ControllerTask oluşturur
   ├─ 5 dakika bekler (WordPress cache için)
   └─ Observer'a doğrulama görevi gönderir
      └─ old_url, new_url, already_fixed bilgileri ile

6. OBSERVER (Doğrulama)
   ├─ Controller'dan doğrulama görevi alır
   ├─ Cache'i temizler (fresh scan için)
   ├─ Sadece o sayfayı kontrol eder
   ├─ Eğer already_fixed ise:
   │  ├─ new_url var mı, old_url yok mu kontrol eder
   │  └─ Başarılı ise → LINK_ALREADY_FIXED raporu oluşturur
   ├─ Normal kontrol:
   │  ├─ Link'in düzeltilip düzeltilmediğini kontrol eder
   │  └─ ObserverReport oluşturur
   └─ Controller'a sonucu bildirir

7. CONTROLLER
   ├─ Observer sonucunu alır
   ├─ Hata yoksa → VERIFIED_SUCCESS
   ├─ Hata varsa → VERIFIED_FAILED
   └─ Başarısızsa Dispatcher'a retry görevi gönderir
      └─ old_url ve new_url bilgileri korunur

8. REPORTER
   └─ Tüm bu süreci görüntüler ve loglar
      └─ Task ID'ye göre gruplanmış log görünümü
```

---

### Agent Bağımlılıkları

#### Python Bağımlılıkları (requirements.txt)

```txt
# Web Framework
fastapi==0.109.0
uvicorn[standard]==0.27.0

# Template Engine
jinja2==3.1.3

# Database
sqlalchemy==2.0.25
aiosqlite==0.19.0

# Background Tasks & Scheduling
apscheduler==3.10.4

# HTTP Requests & Scraping
httpx==0.26.0          # Link Fixer: WordPress REST API için
beautifulsoup4==4.12.3  # Observer: HTML parsing için
lxml==5.1.0            # Observer: HTML parsing için

# Sitemap Parsing
advertools==0.14.2

# Environment & Config
python-dotenv==1.0.0

# Security
cryptography==42.0.0
python-multipart==0.0.6

# Date & Time
python-dateutil==2.8.2
```

#### Agent-Specific Bağımlılıklar

**Link Fixer Agent:**
- `httpx`: WordPress REST API istekleri için
- `json`: Elementor JSON parsing için
- `urllib.parse`: URL encoding/decoding için

**Observer Agent:**
- `beautifulsoup4`: HTML parsing için
- `lxml`: HTML parsing için
- `httpx`: HTTP istekleri için

**Controller Agent:**
- `threading`: 5 dakika gecikme için Timer thread
- `asyncio`: Async işlemler için

**Dispatcher Agent:**
- `sqlalchemy`: Veritabanı işlemleri için

**Reporter Agent:**
- `sqlalchemy`: Veritabanı işlemleri için
- `jinja2`: Template rendering için

---

### WordPress PHP Endpoint

**Dosya:** `wordpress_functions_fix.php`

**Endpoint:** `/wp-json/custom/v1/elementor-native-replace`

**Özellikler:**
- Tüm URL formatlarını destekler (escaped, encoded, href formatları)
- Elementor JSON verisini doğrudan günceller
- WordPress cache temizler (Elementor, object cache, plugin cache'leri)
- `wp_update_post` çağrısı (cache plugin'leri için)

**Kurulum:**
1. `wordpress_functions_fix.php` dosyasını WordPress `functions.php` dosyasına ekleyin
2. WordPress cache'ini temizleyin
3. Permalink'leri yeniden kaydedin (Ayarlar → Kalıcı Bağlantılar)

---

## 📝 Lisans

Bu proje özel kullanım içindir.

## 👥 Geliştirici Notları

### Yeni Özellik Ekleme
1. Router'da yeni endpoint ekleyin (`routers/` veya modül içinde)
2. Gerekirse yeni model ekleyin (`core/database.py` veya modül `models.py`)
3. Template ekleyin (`templates/` dizinine)
4. Migration gerekirse `init_db()` veya modül `init_*_tables()` fonksiyonuna ekleyin

### Veritabanı Değişiklikleri
- Yeni kolon eklerken migration kodu yazın
- `PRAGMA table_info()` ile kolon kontrolü yapın
- `ALTER TABLE` ile kolon ekleyin

### Background Tasks
- `BackgroundTasks` kullanarak uzun süren işlemleri arka plana alın
- `system_status` objesini güncelleyerek header'da durum gösterin
- Log ekranı için `_add_log()` fonksiyonunu kullanın

---

## 📝 Değişiklik Geçmişi

### v2.6.0 (2025-12-XX)
- ✅ Site Tools: WordPress REST API entegrasyonu eklendi
- ✅ Site Tools: Redirect link otomatik düzeltme özelliği
- ✅ Site Tools: Elementor Native Replace endpoint'i (PHP)
- ✅ Site Tools: Detaylı log ekranı (gerçek zamanlı takip)
- ✅ Site Tools: Expandable redirect detayları (kaynak sayfa, redirect URL, final URL, status kodları)
- ✅ Site Tools: WordPress Application Password desteği
- ✅ Site Tools: CSS cache otomatik temizleme (Elementor)
- 📚 README: WordPress REST API ve redirect link düzeltme dokümantasyonu eklendi

### v2.5.0 (2025-12-XX)
- ✅ AI Helper: URL Denetim Detayları sayfası eklendi
- ✅ AI Helper: Live check özelliği (canlı HTML çekme ve link analizi)
- ✅ AI Helper: Hedef cluster link durumları gösterimi (var/yok)
- ✅ AI Helper: Kendi cluster link durumu gösterimi (X/4 link sayısı)
- ✅ AI Helper: AI'a gönderilen HTML versiyonunu dropdown ile görüntüleme ve kopyalama
- ✅ AI Helper: Advanced Auditor modülü eklendi (gelişmiş internal linking denetimi)
- ✅ AI Helper: Cluster hedef yönetimi (Otorite, Tematik, Dolaylı, Zorunlu hedefler)
- ✅ AI Helper: Cluster hedef güncelleme endpoint'i (`update-targets`)
- ✅ AI Helper: Cluster yönetimi (oluşturma, düzenleme, silme, URL taşıma)
- ✅ AI Helper: Toplu URL taşıma özelliği
- ✅ AI Helper: AI önerileri cluster'a göre gruplanmış gösterim
- ✅ AI Helper: Before/After karşılaştırması detay sayfasında
- 📚 README: URL denetim detayları ve Advanced Auditor dokümantasyonu eklendi

### v2.4.0 (2025-12-XX)
- ✅ AI Helper: Yeni modül eklendi (Autonomous Internal Linking Agent)
- ✅ AI Helper: Sayfa bazlı, paragraf bazlı analiz
- ✅ AI Helper: Internal link kontrolü (12'den fazla link varsa atlanır)
- ✅ AI Helper: Sadece `<p>` tag'leri işlenir (başlıklar hariç)
- ✅ AI Helper: Elementor kodları temizlenir, saf HTML AI'a gönderilir
- ✅ AI Helper: Manuel kümeleme (Crowns, Implant, Orthodontic, Veneer, Whitening, Dental Holiday)
- ✅ AI Helper: Küme bazlı denetim (AI provider seçimi ile)
- ✅ AI Helper: Retry mekanizması (503, 429, 500 hataları için exponential backoff)
- ✅ AI Helper: Periyodik analiz (her 10 dakikada bir)
- ✅ AI Helper: Random bekleme (paragraflar arasında 4-6 dakika)
- ✅ AI Helper: Toplu silme özellikleri (havuz temizleme, checkbox ile seçim)
- ✅ AI Helper: Orijinal paragraf ve AI önerisi görüntüleme
- ✅ AI Helper: Detaylı log izleme (prompt ve response loglama)
- 📚 README: AI Helper modülü dokümantasyonu eklendi

### v2.3.0 (2025-12-03)
- ✅ Entity Finder: Yeni modül eklendi (Wikipedia'dan entity bulma)
- ✅ Entity Finder: Anahtar kelime veya URL ile arama desteği
- ✅ Entity Finder: Otomatik kategorilendirme (10 dental kategorisi)
- ✅ Entity Finder: Relevance scoring (0-100 arası)
- ✅ Entity Finder: Entity Listesi sayfası eklendi
- ✅ Entity Finder: Kategori bazında entity kopyalama özelliği
- ✅ Entity Finder: source_section kolonu eklendi (gelecekteki bağlamsal mod için hazır)
- 🐛 Entity Finder: URL cache sorunu düzeltildi (aynı URL tekrar aranabilir)
- 📚 README: Entity Finder modülü dokümantasyonu eklendi

### v2.2.1 (2025-12-02)
- 🐛 Entity Analyzer: JavaScript buton sorunları düzeltildi
- ✅ Entity Analyzer: Tüm JavaScript kodları ES5 syntax ile yeniden yazıldı
- ✅ Entity Analyzer: Wikipedia Test özelliği eklendi (her entity için detaylı log ekranı)
- ✅ Entity Analyzer: Tüm butonlar global scope'ta tanımlandı (`window.functionName`)
- 📚 README: Entity Analyzer buton sorunları ve çözümleri dokümantasyonu eklendi
- **Düzeltme**: Syntax hataları ve scope sorunları çözüldü, tüm butonlar çalışır durumda

### v2.2.0 (2025-12-02)
- ✅ Entity Analyzer: Deepseek AI entegrasyonu eklendi (RapidAPI)
- ✅ Entity Analyzer: AI provider seçimi (Gemini / Deepseek) arama formuna eklendi
- ✅ Ayarlar: Deepseek AI ayarları ve test endpoint'i eklendi
- ✅ Services: `deepseek_ai.py` servisi oluşturuldu
- ✅ Config: Deepseek API key ve host ayarları eklendi
- 📚 README: Deepseek AI dokümantasyonu ve kullanım kılavuzu eklendi
- **Yeni Özellik**: Kullanıcı artık entity araması yaparken AI provider seçebilir

### v2.1.1 (2025-12-02)
- 📚 README: Gemini API quota limitleri ve 429 hatası dokümantasyonu eklendi
- 📚 README: Rate limiting ve çözüm önerileri eklendi

### v2.1.0 (2025-12-02)
- ✅ Entity Analyzer: Wikipedia Check direkt API entegrasyonu eklendi
- ✅ Entity Analyzer: Entity kopyalama özelliği eklendi (Clipboard API)
- ✅ Entity Analyzer: `is_cleaned` flag'i güncelleme sonrası otomatik resetlenir
- ✅ Entity Analyzer: Unique entity listesi virgülle ayrılmış format
- ✅ Entity Analyzer: Rakip site entity dağılım analizi
- 🐛 Wikipedia eşleştirme sorunu düzeltildi
- 🐛 Temizlik butonu güncelleme sonrası görünmeme sorunu düzeltildi

### v2.0.0 (2025-12-01)
- 🎉 İlk stabil versiyon yayınlandı

---

**Versiyon**: 2.6.0
**Son Güncelleme**: 2025-12-XX

