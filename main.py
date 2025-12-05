#!/usr/bin/env python3
# ============================================
# Rakip İçerik İstihbarat Sistemi V2
# Ana Uygulama Dosyası
# ============================================
# Başlatmak için: python main.py
# Tarayıcıda: http://localhost:8000
# ============================================

import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager

from config import settings
from core.database import init_db
from core.scheduler import background_scanner

# Router imports
from routers import dashboard, sites, logs, settings as settings_router, puanlama, system, queue
from site_tools import router as site_tools_router, init_site_tools_tables
from entity_analyzer import router as entity_analyzer_router
from entity_finder import router as entity_finder_router, init_entity_finder_tables
from agents.ai_helper import router as ai_helper_router, init_ai_helper_tables
from agents.observer.router import router as observer_router
from agents.observer.models import init_observer_tables
from agents.reviewer.router import router as reviewer_router
from agents.reviewer.models import init_reviewer_tables
from agents.dispatcher.router import router as dispatcher_router
from agents.dispatcher.models import init_dispatcher_tables
from agents.link_fixer.router import router as link_fixer_router
from agents.link_fixer.models import init_link_fixer_tables
from agents.controller.router import router as controller_router
from agents.controller.models import init_controller_tables
from agents.global_task import init_global_task_tables
from agents.reporter.router import router as reporter_router


# ============================================
# LIFESPAN (Startup & Shutdown)
# ============================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Uygulama yaşam döngüsü yönetimi.
    Startup ve shutdown işlemleri burada yapılır.
    """
    # === STARTUP ===
    print("=" * 50)
    print("🚀 Rakip İstihbarat Sistemi V2 Başlatılıyor...")
    print("=" * 50)
    
    # Veritabanını başlat
    init_db()
    
    # Site Tools tablolarını oluştur
    init_site_tools_tables()
    
    # Entity Analyzer tablolarını oluştur
    from entity_analyzer.models import init_entity_tables
    init_entity_tables()
    
    # Entity Finder tablolarını oluştur
    init_entity_finder_tables()
    
    # AI Helper tablolarını oluştur
    init_ai_helper_tables()
    
    # Observer Agent tablolarını oluştur
    init_observer_tables()
    
    # Reviewer Agent tablolarını oluştur
    init_reviewer_tables()
    
    # Dispatcher Agent tablolarını oluştur
    init_dispatcher_tables()
    
    # Link Fixer Agent tablolarını oluştur
    init_link_fixer_tables()

    # Controller Agent tablolarını oluştur
    init_controller_tables()
    
    # Global Task tablolarını oluştur
    init_global_task_tables()

    # Bekleyen entity search'leri temizle (restart sonrası)
    from core.database import SessionLocal
    from entity_analyzer.models import EntitySearch
    db = SessionLocal()
    try:
        # Tüm "pending" ve "processing" durumundaki aramaları iptal et
        pending_searches = db.query(EntitySearch).filter(
            EntitySearch.status.in_(["pending", "processing"])
        ).all()

        if pending_searches:
            for search in pending_searches:
                search.status = "cancelled"
                search.cancelled = True
            db.commit()
            print(f"🗑️  {len(pending_searches)} bekleyen arama temizlendi (restart)")
    except Exception as e:
        print(f"⚠️  Arama temizleme hatası: {e}")
    finally:
        db.close()

    # Arka plan scheduler'ı başlat
    background_scanner.start()
    
    # AI Helper periyodik analiz scheduler'ını başlat (her 24 saatte bir)
    from agents.ai_helper.periodic_analyzer import periodic_analyze_clusters
    from apscheduler.triggers.interval import IntervalTrigger
    
    if background_scanner.scheduler.running:
        background_scanner.scheduler.add_job(
            periodic_analyze_clusters,
            trigger=IntervalTrigger(hours=24),
            id='ai_helper_periodic_analyzer',
            name='AI Helper Periyodik Analiz',
            replace_existing=True,
            max_instances=1
        )
        print("⏰ AI Helper periyodik analiz ayarlandı: Her 24 saatte bir")
        
        # Dispatcher otomatik görev işlemci (her 30 saniyede bir)
        from agents.dispatcher.scheduler import dispatcher_auto_processor
        background_scanner.scheduler.add_job(
            dispatcher_auto_processor,
            trigger=IntervalTrigger(seconds=30),
            id='dispatcher_auto_processor',
            name='Dispatcher Otomatik Görev İşlemci',
            replace_existing=True,
            max_instances=1
        )
        print("⏰ Dispatcher otomatik görev işlemci ayarlandı: Her 30 saniyede bir")
        
        # Reviewer otomatik Observer rapor işlemci (her 60 saniyede bir)
        from agents.reviewer.worker import process_reports_to_queue
        from core.database import SessionLocal
        
        def reviewer_auto_processor():
            """Reviewer otomatik işlemci - Observer raporlarını kuyruğa ekler"""
            db = SessionLocal()
            try:
                count = process_reports_to_queue(db)
                if count > 0:
                    print(f"✅ Reviewer: {count} Observer raporu otomatik olarak kuyruğa eklendi")
            except Exception as e:
                print(f"⚠️ Reviewer otomatik işlemci hatası: {e}")
            finally:
                db.close()
        
        background_scanner.scheduler.add_job(
            reviewer_auto_processor,
            trigger=IntervalTrigger(seconds=60),
            id='reviewer_auto_processor',
            name='Reviewer Otomatik Observer Rapor İşlemci',
            replace_existing=True,
            max_instances=1
        )
        print("⏰ Reviewer otomatik Observer rapor işlemci ayarlandı: Her 60 saniyede bir")

        # Controller otomatik doğrulama işlemci (her 45 saniyede bir)
        from agents.controller.worker import auto_verify_pending_tasks, check_observer_verifications

        def controller_auto_processor():
            """Controller otomatik işlemci - Bekleyen görevleri doğrular"""
            try:
                # 1. Bekleyen görevleri doğrulamaya gönder
                verify_result = auto_verify_pending_tasks(batch_size=5)
                if verify_result.get('verified', 0) > 0:
                    print(f"✅ Controller: {verify_result['verified']} görev doğrulamaya gönderildi")

                # 2. Observer doğrulamalarını kontrol et
                check_result = check_observer_verifications()
                if check_result.get('success', 0) > 0 or check_result.get('failed', 0) > 0:
                    print(f"✅ Controller: {check_result['success']} başarılı, {check_result['failed']} başarısız doğrulama")
            except Exception as e:
                print(f"⚠️ Controller otomatik işlemci hatası: {e}")

        background_scanner.scheduler.add_job(
            controller_auto_processor,
            trigger=IntervalTrigger(seconds=45),
            id='controller_auto_processor',
            name='Controller Otomatik Doğrulama İşlemci',
            replace_existing=True,
            max_instances=1
        )
        print("⏰ Controller otomatik doğrulama işlemci ayarlandı: Her 45 saniyede bir")
        
        # Link Fixer sitemap güncelleme scheduler'ı (her gün saat 02:00'de)
        from agents.link_fixer.sitemap_manager import update_sitemap_urls
        from core.database import SessionLocal, Site
        from apscheduler.triggers.cron import CronTrigger
        import asyncio
        
        def link_fixer_sitemap_updater():
            """Link Fixer için sitemap URL'lerini güncelle (sync wrapper)"""
            db = SessionLocal()
            try:
                # WordPress API'si olan aktif siteleri al
                sites = db.query(Site).filter(
                    Site.is_active == True,
                    Site.wp_api_url.isnot(None),
                    Site.wp_api_username.isnot(None),
                    Site.wp_api_password.isnot(None)
                ).all()
                
                # Async fonksiyonu çalıştır
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    for site in sites:
                        try:
                            result = loop.run_until_complete(update_sitemap_urls(site.id, db))
                            print(f"✅ Link Fixer Sitemap Güncelleme ({site.name}): {result['updated']}/{result['total']} URL güncellendi")
                            if result['errors']:
                                print(f"⚠️ Hatalar: {', '.join(result['errors'])}")
                        except Exception as e:
                            print(f"⚠️ Link Fixer sitemap güncelleme hatası ({site.name}): {e}")
                finally:
                    loop.close()
            except Exception as e:
                print(f"❌ Link Fixer sitemap güncelleme genel hatası: {e}")
            finally:
                db.close()
        
        # Her gün saat 02:00'de çalış
        background_scanner.scheduler.add_job(
            link_fixer_sitemap_updater,
            trigger=CronTrigger(hour=2, minute=0),
            id='link_fixer_sitemap_updater',
            name='Link Fixer Sitemap Güncelleme',
            replace_existing=True,
            max_instances=1
        )
        print("⏰ Link Fixer sitemap güncelleme ayarlandı: Her gün saat 02:00")
    
    print(f"✅ Sunucu hazır: http://{settings.HOST}:{settings.PORT}")
    print("=" * 50)
    
    yield  # Uygulama çalışıyor
    
    # === SHUTDOWN ===
    print("\n🛑 Sistem kapatılıyor...")
    
    # Scheduler'ı durdur
    background_scanner.shutdown()
    
    print("✅ Temiz kapatma tamamlandı.")


# ============================================
# FASTAPI UYGULAMASI
# ============================================

app = FastAPI(
    title="Rakip İstihbarat Sistemi",
    description="Rakip sitelerin içerik değişikliklerini takip eden istihbarat sistemi",
    version="2.0.0",
    lifespan=lifespan
)

# Static dosyaları serve et
app.mount("/static", StaticFiles(directory=str(settings.STATIC_DIR)), name="static")

# Template engine
templates = Jinja2Templates(directory=str(settings.TEMPLATES_DIR))


# ============================================
# ROUTER'LARI EKLE
# ============================================

app.include_router(dashboard.router)
app.include_router(sites.router)
app.include_router(logs.router)
app.include_router(settings_router.router)
app.include_router(puanlama.router)
app.include_router(site_tools_router)
app.include_router(entity_analyzer_router)
app.include_router(entity_finder_router)
app.include_router(ai_helper_router)
app.include_router(observer_router)
app.include_router(reviewer_router)
app.include_router(dispatcher_router)
app.include_router(link_fixer_router)
app.include_router(controller_router)
app.include_router(reporter_router)
app.include_router(system.router)
app.include_router(queue.router)


# ============================================
# HATA SAYFALARI
# ============================================

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """404 hata sayfası"""
    return templates.TemplateResponse(
        "base.html",
        {
            "request": request,
            "current_page": None,
            "error": "Sayfa bulunamadı (404)"
        },
        status_code=404
    )


@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    """500 hata sayfası"""
    return templates.TemplateResponse(
        "base.html",
        {
            "request": request,
            "current_page": None,
            "error": "Sunucu hatası (500)"
        },
        status_code=500
    )


# ============================================
# ANA GİRİŞ NOKTASI
# ============================================

if __name__ == "__main__":
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║   🕵️  RAKİP İSTİHBARAT SİSTEMİ V2                         ║
    ║                                                           ║
    ║   Rakiplerinizin içerik hareketlerini 7/24 takip edin    ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        reload_excludes=["venv/*", "*.db", "__pycache__/*", ".git/*"] if settings.DEBUG else None,
        log_level="info" if settings.DEBUG else "warning"
    )
