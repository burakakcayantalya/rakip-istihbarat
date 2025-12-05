# Agent Sistemi - Çalışma Mantığı ve Haberleşme Dokümantasyonu

## 📋 İçindekiler

1. [Genel Bakış](#genel-bakış)
2. [Agent Mimarisi](#agent-mimarisi)
3. [Görev Akışı (Workflow)](#görev-akışı-workflow)
4. [Agent Detayları](#agent-detayları)
5. [Haberleşme Protokolleri](#haberleşme-protokolleri)
6. [Veritabanı Yapısı](#veritabanı-yapısı)
7. [Otomatik İşlemler (Schedulers)](#otomatik-işlemler-schedulers)

---

## 🎯 Genel Bakış

Bu sistem, SEO sorunlarını tespit eden, önceliklendiren, düzelten ve doğrulayan **otonom agentlar** içeren bir **mikroservis mimarisi** kullanır. Her agent kendi sorumluluğuna odaklanır ve diğer agentlarla **asenkron haberleşme** yapar.

### Sistem Amacı
- **SEO sorunlarını otomatik tespit etmek** (kırık linkler, redirect'ler, duplicate linkler, vb.)
- **Sorunları önceliklendirmek** ve **uygun agent'a yönlendirmek**
- **Sorunları düzeltmek** (WordPress API üzerinden)
- **Düzeltmeleri doğrulamak** ve **raporlamak**

---

## 🏗️ Agent Mimarisi

### Agent Hiyerarşisi

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
│  (Görev tamamlandı mı? Doğrula!)                             │
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
│  (Observer raporlarını önceliklendirir)                     │
└─────────────────────────────────────────────────────────────┘
         ▲
         │ (Raporlar)
         │
┌─────────────────────────────────────────────────────────────┐
│                    OBSERVER AGENT                           │
│  (SEO sorunlarını tespit eder ve raporlar)                  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    AI HELPER AGENT                           │
│  (Internal linking optimizasyonu, duplicate link analizi)  │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔄 Görev Akışı (Workflow)

### Senaryo 1: Kırık Link Tespiti ve Düzeltme

```
1. OBSERVER
   ├─ Site'ı tarar
   ├─ Kırık link bulur (404, 410, vb.)
   └─ ObserverReport oluşturur
      └─ rule_name: "LINK_AUDIT"
      └─ severity: ERROR
      └─ details: {url: "...", status_code: 404}

2. REVIEWER (Otomatik - 60 saniyede bir)
   ├─ ObserverReport'ları alır
   ├─ Öncelik skoru hesaplar
   ├─ Action plan belirler (FIX_LINK)
   └─ ReviewerQueue'ya ekler

3. DISPATCHER (Otomatik - 30 saniyede bir)
   ├─ ReviewerQueue'dan görevleri alır
   ├─ Görev tipine göre agent belirler (FIX_LINK → FIXER)
   ├─ DispatcherTask oluşturur
   └─ Link Fixer'a görev atar

4. LINK FIXER
   ├─ DispatcherTask'ı alır
   ├─ WordPress API ile link'i düzeltir
   ├─ LinkFixTask oluşturur
   └─ Controller'a tamamlandı bildirimi gönderir

5. CONTROLLER (Otomatik - 45 saniyede bir)
   ├─ Tamamlandı bildirimini alır
   ├─ ControllerTask oluşturur
   ├─ Observer'a doğrulama görevi gönderir
   └─ Observer sonucunu bekler

6. OBSERVER (Doğrulama)
   ├─ Controller'dan doğrulama görevi alır
   ├─ Sadece o sayfayı kontrol eder
   ├─ Link'in düzeltilip düzeltilmediğini kontrol eder
   └─ ObserverReport oluşturur

7. CONTROLLER
   ├─ Observer sonucunu alır
   ├─ Hata yoksa → VERIFIED_SUCCESS
   ├─ Hata varsa → VERIFIED_FAILED
   └─ Başarısızsa Dispatcher'a retry görevi gönderir

8. REPORTER
   └─ Tüm bu süreci görüntüler ve loglar
```

### Senaryo 2: Duplicate Link Analizi

```
1. OBSERVER
   ├─ Duplicate link tespit eder
   └─ ObserverReport oluşturur
      └─ rule_name: "DUPLICATE_LINK_CHECK"

2. REVIEWER
   ├─ Duplicate link görevini alır
   ├─ Action plan: ANALYZE_DUPLICATE_LINKS
   └─ ReviewerQueue'ya ekler

3. DISPATCHER
   ├─ Görev tipine göre AI_HELPER'a yönlendirir
   └─ AIHelperOpportunity oluşturur

4. AI HELPER
   ├─ Duplicate link'i analiz eder
   ├─ Hangi paragraflarda olduğunu tespit eder
   └─ Controller'a tamamlandı bildirimi gönderir

5. CONTROLLER → OBSERVER → CONTROLLER
   └─ (Yukarıdaki doğrulama akışı)
```

---

## 🤖 Agent Detayları

### 1. OBSERVER AGENT
**Görevi:** SEO sorunlarını tespit etmek ve raporlamak

**Yapabilecekleri:**
- ✅ Full Audit (H1, Schema, Link kontrolü)
- ✅ Link Audit (Kırık linkler, redirect'ler)
- ✅ Freshness Check (Eski içerik tespiti)
- ✅ Duplicate Link Check
- ✅ Schema Check
- ✅ H1 Check

**Çıktıları:**
- `ObserverTask`: Görev kaydı
- `ObserverReport`: Tespit edilen sorunlar

**Haberleşme:**
- **Girdi:** Manuel görev oluşturma veya Controller'dan doğrulama görevi
- **Çıktı:** ObserverReport → Reviewer'a otomatik gönderilir (Controller doğrulaması değilse)

**Önemli Notlar:**
- Controller doğrulaması için sadece belirtilen sayfayı kontrol eder
- Normal görevlerde tüm site'ı tarar

---

### 2. REVIEWER AGENT
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

### 3. DISPATCHER AGENT
**Görevi:** Görevleri uygun agent'a yönlendirmek

**Yapabilecekleri:**
- ✅ ReviewerQueue'dan görevleri alır
- ✅ Görev tipine göre agent belirler (routing rules)
- ✅ DispatcherTask oluşturur
- ✅ Agent'a görev atar

**Routing Rules:**
- `FIX_LINK`, `FIX_301_LINK`, `FIX_404_LINK`, vb. → **FIXER**
- `ANALYZE_DUPLICATE_LINKS` → **AI_HELPER**

**Çıktıları:**
- `DispatcherTask`: Görev kaydı
- Agent'a özel task (LinkFixTask veya AIHelperOpportunity)

**Haberleşme:**
- **Girdi:** ReviewerQueue
- **Çıktı:** Link Fixer veya AI Helper'a görev atama

**Önemli Notlar:**
- `old_url` bulunamazsa görev FAILED olarak işaretlenir
- Observer report'tan URL çıkarmaya çalışır

---

### 4. LINK FIXER AGENT
**Görevi:** Kırık linkleri ve redirect'leri düzeltmek

**Yapabilecekleri:**
- ✅ WordPress API ile Elementor içeriğini günceller
- ✅ Kırık linkleri alternatif URL'lerle değiştirir
- ✅ Redirect linkleri düzeltir

**Çıktıları:**
- `LinkFixTask`: Görev kaydı

**Haberleşme:**
- **Girdi:** DispatcherTask (Dispatcher'dan)
- **Çıktı:** Controller'a tamamlandı bildirimi

**WordPress Entegrasyonu:**
- Elementor JSON verisini günceller
- Custom endpoint kullanır (daha güvenli)
- Fallback: Python tarafında JSON manipülasyonu

---

### 5. AI HELPER AGENT
**Görevi:** Internal linking optimizasyonu ve duplicate link analizi

**Yapabilecekleri:**
- ✅ Sitemap analizi ve URL clustering
- ✅ Internal linking gap analizi
- ✅ Duplicate link analizi
- ✅ AI ile link önerileri
- ✅ HTML proposal'ları oluşturur

**Çıktıları:**
- `AIHelperProject`: Proje kaydı
- `AIHelperCluster`: URL kümeleri
- `AIHelperOpportunity`: Link fırsatları
- `AIHelperProposal`: AI önerileri

**Haberleşme:**
- **Girdi:** DispatcherTask (duplicate link analizi için)
- **Çıktı:** Controller'a tamamlandı bildirimi

---

### 6. CONTROLLER AGENT
**Görevi:** Görevlerin başarıyla tamamlanıp tamamlanmadığını doğrulamak

**Yapabilecekleri:**
- ✅ Agent'lardan tamamlandı bildirimlerini alır
- ✅ Observer'a doğrulama görevi gönderir
- ✅ Observer sonucunu değerlendirir
- ✅ Başarısız görevleri retry eder

**Çıktıları:**
- `ControllerTask`: Doğrulama kaydı
- `ControllerStats`: İstatistikler

**Haberleşme:**
- **Girdi:** Agent tamamlandı bildirimleri (Link Fixer, AI Helper)
- **Çıktı:** Observer'a doğrulama görevi
- **Retry:** Dispatcher'a retry görevi (başarısız durumda)

**Doğrulama Süreci:**
1. Agent tamamlandı bildirimi alınır
2. Observer'a doğrulama görevi gönderilir (sadece o sayfa için)
3. Observer sonucu beklenir
4. Hata yoksa → VERIFIED_SUCCESS
5. Hata varsa → VERIFIED_FAILED → Retry

---

### 7. REPORTER AGENT
**Görevi:** Tüm görevlerin hikayesini görüntülemek ve log yönetimi

**Yapabilecekleri:**
- ✅ ControllerTask'ların timeline'ını gösterir
- ✅ Agentlar arası haberleşmeleri loglar
- ✅ Canlı log ekranı
- ✅ Log silme

**Çıktıları:**
- `ReporterLog`: Agent haberleşme logları

**Haberleşme:**
- **Girdi:** Tüm agentlardan log mesajları
- **Çıktı:** Dashboard ve API endpoint'leri

---

## 📡 Haberleşme Protokolleri

### 1. Observer → Reviewer
**Yöntem:** Otomatik (Observer görev tamamlandığında)
**Veri:** `ObserverReport`
**Trigger:** Observer görevi tamamlandığında (Controller doğrulaması değilse)

```python
# Observer worker.py içinde
if not is_controller_verification:
    from agents.reviewer.worker import process_reports_to_queue
    process_reports_to_queue(db, task.site_id)
```

---

### 2. Reviewer → Dispatcher
**Yöntem:** Otomatik (Scheduler - 30 saniyede bir)
**Veri:** `ReviewerQueue` → `DispatcherTask`
**Trigger:** Dispatcher scheduler

```python
# Dispatcher scheduler.py içinde
def process_reviewer_queue_batch():
    # ReviewerQueue'dan görevleri al
    # DispatcherTask oluştur
    # Agent'a ata
```

---

### 3. Dispatcher → Link Fixer / AI Helper
**Yöntem:** Otomatik (Dispatcher görev atama)
**Veri:** `DispatcherTask` → `LinkFixTask` veya `AIHelperOpportunity`
**Trigger:** Dispatcher görev atama

```python
# Dispatcher worker.py içinde
if task.assigned_agent == AgentType.FIXER:
    create_link_fixer_task(db, task)
elif task.assigned_agent == AgentType.AI_HELPER:
    create_ai_helper_task(db, task)
```

---

### 4. Link Fixer / AI Helper → Controller
**Yöntem:** HTTP API veya doğrudan fonksiyon çağrısı
**Veri:** Tamamlandı bildirimi
**Trigger:** Agent görevi tamamlandığında

```python
# Link Fixer router.py içinde
from agents.controller.worker import receive_completion_notification
receive_completion_notification(
    db=db,
    source_agent="FIXER",
    source_task_id=task.id,
    ...
)
```

---

### 5. Controller → Observer
**Yöntem:** Otomatik (Controller doğrulama)
**Veri:** `ObserverTask` (doğrulama için)
**Trigger:** Controller görev doğrulama

```python
# Controller worker.py içinde
observer_task = ObserverTask(
    site_id=controller_task.site_id,
    task_type=TaskType.LINK_AUDIT,
    description=f"🎯 Controller Doğrulaması: {page_url}",
    ...
)
```

---

### 6. Observer → Controller
**Yöntem:** Otomatik (Observer doğrulama tamamlandığında)
**Veri:** `ObserverReport` (doğrulama sonuçları)
**Trigger:** Controller doğrulama kontrolü

```python
# Controller worker.py içinde
def check_observer_verifications():
    # Observer task'larını kontrol et
    # Sonuçları değerlendir
    # ControllerTask'ı güncelle
```

---

### 7. Controller → Dispatcher (Retry)
**Yöntem:** Otomatik (Başarısız doğrulama)
**Veri:** `DispatcherTask` (retry için)
**Trigger:** Controller doğrulama başarısız olduğunda

```python
# Controller worker.py içinde
def retry_task_to_dispatcher(controller_task):
    dispatcher_task = DispatcherTask(
        source_type="CONTROLLER_RETRY",
        source_id=controller_task.id,
        ...
    )
```

---

## 🗄️ Veritabanı Yapısı

### Ana Tablolar

#### Observer
- `observer_tasks`: Görev kayıtları
- `observer_reports`: Tespit edilen sorunlar
- `observer_rules`: Dinamik kurallar

#### Reviewer
- `reviewer_queue`: Önceliklendirilmiş görevler

#### Dispatcher
- `dispatcher_tasks`: Görev yönlendirme kayıtları
- `agent_routing_rules`: Görev tipi → Agent eşleştirmeleri

#### Link Fixer
- `link_fix_tasks`: Link düzeltme görevleri

#### AI Helper
- `ai_helper_projects`: Projeler
- `ai_helper_clusters`: URL kümeleri
- `ai_helper_opportunities`: Link fırsatları
- `ai_helper_proposals`: AI önerileri
- `ai_helper_logs`: Log kayıtları

#### Controller
- `controller_tasks`: Doğrulama kayıtları
- `controller_stats`: İstatistikler

#### Reporter
- `reporter_logs`: Agent haberleşme logları

---

## ⏰ Otomatik İşlemler (Schedulers)

### 1. Dispatcher Auto Processor
**Sıklık:** Her 30 saniyede bir
**Görev:**
- ReviewerQueue'dan görevleri alır
- DispatcherTask oluşturur
- Agent'lara görev atar

### 2. Reviewer Auto Processor
**Sıklık:** Her 60 saniyede bir
**Görev:**
- ObserverReport'ları alır
- ReviewerQueue'ya ekler

### 3. Controller Auto Processor
**Sıklık:** Her 45 saniyede bir
**Görev:**
- Bekleyen görevleri doğrulamaya gönderir
- Observer doğrulamalarını kontrol eder

### 4. AI Helper Periodic Analyzer
**Sıklık:** Her 24 saatte bir
**Görev:**
- Aktif projeleri analiz eder
- Yeni link fırsatları bulur

### 5. Link Fixer Sitemap Updater
**Sıklık:** Her gün saat 02:00
**Görev:**
- Sitemap URL'lerini günceller
- Yeni URL'leri ekler

---

## 🔍 Debug ve Loglama

### Reporter Log Sistemi
- Tüm agentlar arası haberleşmeler loglanır
- Canlı log ekranı: `/agents/reporter/`
- Log seviyeleri: DEBUG, INFO, WARNING, ERROR, SUCCESS

### Log Ekleme
```python
from agents.reporter import add_reporter_log

add_reporter_log(
    db=db,
    level="INFO",
    source_agent="DISPATCHER",
    target_agent="FIXER",
    message="Görev atandı",
    details={...}
)
```

---

## 🚨 Hata Yönetimi

### Hata Senaryoları

1. **old_url bulunamadı**
   - Dispatcher, Observer report'tan URL çıkarmaya çalışır
   - Message'dan regex ile URL çıkarır
   - Bulunamazsa görev FAILED olarak işaretlenir

2. **Doğrulama başarısız**
   - Controller, Dispatcher'a retry görevi gönderir
   - Retry sayısı artar
   - Maksimum retry sonrası görev iptal edilir

3. **WordPress API hatası**
   - Link Fixer, alternatif yöntemler dener
   - Hata loglanır
   - Controller'a hata bildirimi gönderilir

---

## 📊 İstatistikler ve Raporlama

### Controller Stats
- Günlük/haftalık/aylık başarı oranları
- Agent bazlı istatistikler
- Retry sayıları

### Reporter Timeline
- Tüm görevlerin baştan sona hikayesi
- Accordion yapısında detaylı görüntüleme
- Her adımın detayları

---

## 🎯 Önemli Notlar

1. **Asenkron İşlemler:** Tüm agentlar asenkron çalışır, birbirini beklemez
2. **Otomatik Retry:** Başarısız görevler otomatik olarak retry edilir
3. **Controller Doğrulaması:** Sadece belirtilen sayfa kontrol edilir (tüm site değil)
4. **Observer Report Formatı:** `details` içinde `url` field'ı `old_url` olarak kullanılır
5. **WordPress Entegrasyonu:** Elementor JSON verisi güncellenir, custom endpoint tercih edilir

---

## 🔧 Geliştirme Notları

### Yeni Agent Ekleme
1. `agents/` klasörüne yeni klasör oluştur
2. `models.py`, `router.py`, `worker.py` dosyalarını oluştur
3. `main.py`'de router'ı ekle
4. Dispatcher routing rules'a ekle
5. Controller'a bildirim endpoint'i ekle

### Yeni Görev Tipi Ekleme
1. Dispatcher routing rules'a ekle
2. Reviewer action plan'a ekle
3. Observer task type'a ekle (gerekirse)

---

## 📝 Sonuç

Bu sistem, **otonom agentlar** ile **SEO sorunlarını otomatik tespit eden, önceliklendiren, düzelten ve doğrulayan** bir mimari kullanır. Her agent kendi sorumluluğuna odaklanır ve diğer agentlarla **asenkron haberleşme** yapar.

**Ana Akış:**
```
Observer → Reviewer → Dispatcher → Link Fixer/AI Helper → Controller → Observer → Controller
```

**Retry Akışı:**
```
Controller (FAILED) → Dispatcher (RETRY) → Link Fixer → Controller
```

**Log ve Raporlama:**
```
Tüm Agentlar → Reporter (Log) → Dashboard (Görüntüleme)
```

---

*Son Güncelleme: 2025-12-05*



