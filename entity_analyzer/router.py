# ============================================
# Entity Analyzer - Router & Endpoints
# ============================================

from fastapi import APIRouter, Request, Depends, HTTPException, BackgroundTasks, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from datetime import datetime
from typing import Optional
import json

from config import settings
from core.database import get_db, Site, Page
from core.scheduler import system_status
from entity_analyzer.models import EntitySearch, EntityResult, EntitySearchLog, MatchType, init_entity_tables
from entity_analyzer.analyzer import entity_matcher, EntityMatch
from services.google_search import google_search
from services.gemini_ai import GeminiService
from services.deepseek_ai import DeepseekService

router = APIRouter(prefix="/entity-analyzer", tags=["Entity Analyzer"])

# Template dizinleri
from pathlib import Path
ENTITY_TEMPLATE_DIR = Path(__file__).parent.parent / "templates" / "entity_analyzer"
MAIN_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=[str(ENTITY_TEMPLATE_DIR), str(MAIN_TEMPLATE_DIR)])

# AI servisleri
gemini_service = GeminiService()
deepseek_service = DeepseekService()

_tables_initialized = False

def ensure_tables():
    """Tabloların oluşturulduğundan emin ol"""
    global _tables_initialized
    if not _tables_initialized:
        init_entity_tables()
        _tables_initialized = True


# ============================================
# ANA SAYFA
# ============================================

@router.get("/", response_class=HTMLResponse)
async def entity_analyzer_index(request: Request, db: Session = Depends(get_db)):
    """Entity Analyzer ana sayfası"""
    ensure_tables()
    
    # Migration: is_cleaned kolonunu kontrol et ve ekle
    try:
        from sqlalchemy import text, inspect
        from core.database import engine
        
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(entity_searches)"))
            columns = [row[1] for row in result]
            if 'is_cleaned' not in columns:
                conn.execute(text("ALTER TABLE entity_searches ADD COLUMN is_cleaned BOOLEAN DEFAULT 0"))
                conn.commit()
                print("✅ Entity Analyzer: is_cleaned kolonu eklendi")
    except Exception as e:
        print(f"⚠️ Migration kontrolü hatası (normal olabilir): {e}")
    
    try:
        # Önceki aramaları al (en yeni önce)
        previous_searches = db.query(EntitySearch).order_by(desc(EntitySearch.created_at)).limit(20).all()
        
        # Her arama için sonuç sayılarını al
        searches_with_stats = []
        for search in previous_searches:
            exact_count = db.query(func.count(EntityResult.id)).filter(
                EntityResult.search_id == search.id,
                EntityResult.match_type == MatchType.EXACT
            ).scalar() or 0
            
            partial_count = db.query(func.count(EntityResult.id)).filter(
                EntityResult.search_id == search.id,
                EntityResult.match_type == MatchType.PARTIAL
            ).scalar() or 0
            
            low_count = db.query(func.count(EntityResult.id)).filter(
                EntityResult.search_id == search.id,
                EntityResult.match_type == MatchType.LOW
            ).scalar() or 0
            
            total_count = db.query(func.count(EntityResult.id)).filter(
                EntityResult.search_id == search.id
            ).scalar() or 0
            
            searches_with_stats.append({
                "search": search,
                "exact_count": exact_count,
                "partial_count": partial_count,
                "low_count": low_count,
                "total_count": total_count
            })
        
        # En son aramayı al (log göstermek için)
        latest_search = db.query(EntitySearch).order_by(desc(EntitySearch.created_at)).first()
        
        return templates.TemplateResponse("index.html", {
            "request": request,
            "previous_searches": searches_with_stats,
            "latest_search_id": latest_search.id if latest_search else None,
            "current_page": "entity_analyzer"
        })
    except Exception as e:
        import traceback
        error_msg = str(e)
        traceback.print_exc()
        # Hata durumunda basit bir sayfa göster
        from fastapi.responses import HTMLResponse
        return HTMLResponse(f"""
        <html>
        <head><title>Hata</title></head>
        <body>
            <h1>Entity Analyzer Sayfası Yüklenirken Hata Oluştu</h1>
            <p>Hata: {error_msg}</p>
            <p>Lütfen konsol loglarını kontrol edin.</p>
            <a href="/">Ana Sayfaya Dön</a>
        </body>
        </html>
        """, status_code=500)


# ============================================
# ENTITY ARAMA
# ============================================

@router.post("/search", tags=["API"])
async def search_entity(
    background_tasks: BackgroundTasks,
    search_term: str = Form(...),
    ai_provider: str = Form("gemini"),
    db: Session = Depends(get_db)
):
    """Entity araması başlat (arka planda)"""
    ensure_tables()

    if not search_term or len(search_term.strip()) < 2:
        return JSONResponse({
            "status": "error",
            "message": "Arama terimi en az 2 karakter olmalıdır"
        }, status_code=400)

    search_term = search_term.strip()

    # AI provider kontrolü
    if ai_provider not in ["gemini", "deepseek"]:
        ai_provider = "gemini"  # Varsayılan

    # Yeni arama kaydı oluştur
    search = EntitySearch(search_term=search_term)
    db.add(search)
    db.commit()
    db.refresh(search)

    # Arka planda analiz yap (ai_provider parametresini ekle)
    background_tasks.add_task(analyze_entity_task, search.id, search_term, False, ai_provider)

    ai_name = "Gemini AI" if ai_provider == "gemini" else "Deepseek AI"
    return JSONResponse({
        "status": "started",
        "message": f"'{search_term}' için entity analizi başlatıldı ({ai_name})",
        "search_id": search.id
    })


@router.post("/search/{search_id}/update", tags=["API"])
async def update_entity_search(
    search_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Mevcut aramayı güncelle (sonuçları sil ve yeniden analiz et)"""
    ensure_tables()
    
    search = db.query(EntitySearch).filter(EntitySearch.id == search_id).first()
    if not search:
        return JSONResponse({
            "status": "error",
            "message": "Arama bulunamadı"
        }, status_code=404)
    
    # Arka planda güncelleme yap
    background_tasks.add_task(analyze_entity_task, search.id, search.search_term, True)
    
    return JSONResponse({
        "status": "started",
        "message": f"'{search.search_term}' için entity analizi güncelleniyor",
        "search_id": search.id
    })


@router.post("/search/{search_id}/cancel", tags=["API"])
async def cancel_entity_search(
    search_id: int,
    db: Session = Depends(get_db)
):
    """Devam eden aramayı iptal et"""
    ensure_tables()

    search = db.query(EntitySearch).filter(EntitySearch.id == search_id).first()
    if not search:
        return JSONResponse({
            "status": "error",
            "message": "Arama bulunamadı"
        }, status_code=404)

    # İptal flag'ini set et
    search.cancelled = True
    search.status = "cancelled"
    db.commit()

    _add_log(db, search_id, "warning", "Kullanıcı tarafından iptal edildi")

    return JSONResponse({
        "status": "success",
        "message": "Arama iptal ediliyor..."
    })


@router.post("/entity/{entity_id}/test-wikipedia", tags=["API"])
async def test_wikipedia_for_entity(
    entity_id: int,
    db: Session = Depends(get_db)
):
    """
    Tek bir entity için Wikipedia doğrulamasını test et ve detaylı log döndür
    """
    ensure_tables()

    # Entity'yi bul
    entity = db.query(EntityResult).filter(EntityResult.id == entity_id).first()
    if not entity:
        return JSONResponse({
            "status": "error",
            "message": "Entity bulunamadı"
        }, status_code=404)

    logs = []

    def add_log(level: str, message: str, data: dict = None):
        """Log ekle"""
        log_entry = {
            "level": level,
            "message": message,
            "timestamp": datetime.utcnow().strftime("%H:%M:%S.%f")[:-3],
            "data": data
        }
        logs.append(log_entry)

    try:
        # Entity bilgilerini logla
        add_log("info", f"Entity test başladı", {
            "entity_id": entity.id,
            "entity_name": entity.entity_name,
            "source_url": entity.source_url
        })

        # Temizleme işlemi
        entity_name_cleaned = entity.entity_name.strip()
        add_log("info", f"Entity adı temizlendi", {
            "original": repr(entity.entity_name),
            "cleaned": repr(entity_name_cleaned)
        })

        # Wikipedia API isteği
        from urllib.parse import quote
        import httpx

        encoded_name = quote(entity_name_cleaned)
        wiki_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded_name}"

        add_log("info", "Wikipedia REST API isteği hazırlanıyor", {
            "entity_name": entity_name_cleaned,
            "encoded_name": encoded_name,
            "full_url": wiki_url
        })

        # User-Agent header'ı ekle (Wikipedia zorunlu tutuyor)
        headers = {
            "User-Agent": "RakipIstihbaratBot/2.0 (https://github.com/your-repo; contact@example.com) Python/httpx"
        }
        
        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            add_log("info", "HTTP GET isteği gönderiliyor...", {
                "url": wiki_url,
                "headers": headers
            })

            response = await client.get(wiki_url)

            add_log("info", f"HTTP Response alındı", {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "content_type": response.headers.get("content-type")
            })

            if response.status_code == 200:
                data = response.json()

                add_log("success", "Wikipedia entity bulundu!", {
                    "title": data.get("title"),
                    "description": data.get("description"),
                    "extract": data.get("extract", "")[:200] + "...",
                    "url": data.get("content_urls", {}).get("desktop", {}).get("page", "")
                })

                # Response yapısını detaylı göster
                add_log("debug", "Full Wikipedia Response", {
                    "keys": list(data.keys()),
                    "full_data": data
                })

                return JSONResponse({
                    "status": "success",
                    "found": True,
                    "entity_data": {
                        "title": data.get("title"),
                        "description": data.get("description"),
                        "extract": data.get("extract"),
                        "url": data.get("content_urls", {}).get("desktop", {}).get("page", "")
                    },
                    "logs": logs
                })

            elif response.status_code == 404:
                add_log("warning", "Entity direkt bulunamadı, search API deneniyor...", {
                    "status_code": 404
                })

                # Search API'yi dene
                search_url = f"https://en.wikipedia.org/api/rest_v1/page/search/{encoded_name}"
                add_log("info", "Wikipedia Search API isteği", {"url": search_url})

                search_response = await client.get(search_url, params={"limit": 5}, headers=headers)

                add_log("info", "Search Response alındı", {
                    "status_code": search_response.status_code
                })

                if search_response.status_code == 200:
                    search_data = search_response.json()
                    pages = search_data.get("pages", [])

                    add_log("info", f"Search sonucu: {len(pages)} sayfa bulundu", {
                        "pages": pages
                    })

                    if pages:
                        first_page = pages[0]
                        add_log("success", "İlk arama sonucu", {
                            "title": first_page.get("title"),
                            "key": first_page.get("key"),
                            "description": first_page.get("description"),
                            "extract": first_page.get("extract", "")
                        })

                        return JSONResponse({
                            "status": "success",
                            "found": True,
                            "search_result": True,
                            "entity_data": {
                                "title": first_page.get("title"),
                                "description": first_page.get("description"),
                                "extract": first_page.get("extract"),
                                "url": f"https://en.wikipedia.org/wiki/{quote(first_page.get('key', ''))}"
                            },
                            "logs": logs
                        })
                    else:
                        add_log("error", "Search sonucu boş", {})
                        return JSONResponse({
                            "status": "success",
                            "found": False,
                            "message": "Wikipedia'da entity bulunamadı",
                            "logs": logs
                        })
                else:
                    add_log("error", "Search API hatası", {
                        "status_code": search_response.status_code,
                        "body": search_response.text[:500]
                    })
                    return JSONResponse({
                        "status": "error",
                        "found": False,
                        "message": "Wikipedia search API hatası",
                        "logs": logs
                    })
            else:
                add_log("error", "Wikipedia API beklenmeyen hata", {
                    "status_code": response.status_code,
                    "body": response.text[:500]
                })

                return JSONResponse({
                    "status": "error",
                    "found": False,
                    "message": f"Wikipedia API hatası: {response.status_code}",
                    "logs": logs
                })

    except Exception as e:
        add_log("error", f"Exception oluştu: {str(e)}", {
            "exception_type": type(e).__name__,
            "exception_message": str(e)
        })
        import traceback
        add_log("error", "Stack trace", {
            "traceback": traceback.format_exc()
        })

        return JSONResponse({
            "status": "error",
            "found": False,
            "message": f"Hata: {str(e)}",
            "logs": logs
        })


@router.delete("/search/{search_id}", tags=["API"])
async def delete_entity_search(
    search_id: int,
    db: Session = Depends(get_db)
):
    """Arama kaydını ve sonuçlarını sil"""
    ensure_tables()
    
    search = db.query(EntitySearch).filter(EntitySearch.id == search_id).first()
    if not search:
        return JSONResponse({
            "status": "error",
            "message": "Arama bulunamadı"
        }, status_code=404)
    
    try:
        # Sonuçları sil (cascade ile otomatik silinir ama emin olmak için)
        db.query(EntityResult).filter(EntityResult.search_id == search_id).delete()
        
        # Log'ları sil
        db.query(EntitySearchLog).filter(EntitySearchLog.search_id == search_id).delete()
        
        # Arama kaydını sil
        db.delete(search)
        db.commit()
        
        return JSONResponse({
            "status": "success",
            "message": "Arama kaydı silindi"
        })
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "status": "error",
            "message": f"Silme hatası: {str(e)}"
        }, status_code=500)


def _add_log(db: Session, search_id: int, level: str, message: str, details: str = None):
    """Log kaydı ekle"""
    try:
        log = EntitySearchLog(
            search_id=search_id,
            level=level,
            message=message,
            details=details
        )
        db.add(log)
        db.commit()
    except Exception as e:
        print(f"⚠️ Log kaydetme hatası: {e}")


def is_english_text(text: str) -> bool:
    """Metnin İngilizce olup olmadığını kontrol et"""
    if not text or len(text) < 2:
        return False

    # Türkçe karakterler varsa False döndür
    turkish_chars = ['ç', 'ğ', 'ı', 'ö', 'ş', 'ü', 'Ç', 'Ğ', 'İ', 'Ö', 'Ş', 'Ü']
    for char in turkish_chars:
        if char in text:
            return False

    # İngilizce alfabe kontrolü (en az %70 İngilizce karakter olmalı)
    import re
    english_chars = re.findall(r'[a-zA-Z]', text)
    total_chars = len(re.findall(r'[a-zA-ZçğıöşüÇĞİÖŞÜ]', text))

    if total_chars == 0:
        return False

    english_ratio = len(english_chars) / total_chars
    return english_ratio >= 0.7


def should_skip_url(url: str) -> bool:
    """URL'nin analiz edilip edilmeyeceğini kontrol et"""
    if not url:
        return True

    url_lower = url.lower()

    # Tag, taxonomies, category gibi URL'leri atla
    skip_patterns = [
        '/tag/', '/tags/',
        '/category/', '/categories/',
        '/taxonomy/', '/taxonomies/',
        '/author/', '/authors/',
        '/archive/', '/archives/',
        '/page/',
        '/feed/',
        '/rss',
        '/xmlrpc',
        '/wp-json',
        '/api/',
    ]

    for pattern in skip_patterns:
        if pattern in url_lower:
            return True

    return False


async def analyze_entity_task(search_id: int, search_term: str, update_existing: bool = False, ai_provider: str = "gemini"):
    """Entity analiz görevi (arka planda çalışır)"""
    from core.database import SessionLocal

    db = SessionLocal()
    try:
        # Arama kaydını güncelle
        search = db.query(EntitySearch).filter(EntitySearch.id == search_id).first()
        if search:
            search.status = "processing"
            db.commit()

        ai_name = "Gemini AI" if ai_provider == "gemini" else "Deepseek AI"
        _add_log(db, search_id, "info", f"Entity analizi başlatıldı: {search_term} ({ai_name})")
        
        # System status güncelle
        system_status.current_task = "Entity Analizi"
        system_status.current_site = f"Arama: {search_term}"
        system_status.current_url = ""
        
        # Eğer güncelleme modundaysa mevcut sonuçları sil
        if update_existing:
            deleted_count = db.query(EntityResult).filter(EntityResult.search_id == search_id).count()
            db.query(EntityResult).filter(EntityResult.search_id == search_id).delete()

            # is_cleaned flag'ini resetle (yeni sonuçlar için tekrar temizlik yapılabilsin)
            search = db.query(EntitySearch).filter(EntitySearch.id == search_id).first()
            if search:
                search.is_cleaned = False

            db.commit()
            _add_log(db, search_id, "info", f"Mevcut sonuçlar silindi: {deleted_count} kayıt")
            system_status.current_url = "Mevcut sonuçlar silindi"
        
        # Rakip sitelerin sayfalarını al
        system_status.current_url = "Rakip sayfalar taranıyor..."
        _add_log(db, search_id, "info", "Rakip siteler taranıyor...")
        
        competitor_sites = db.query(Site).filter(
            Site.is_competitor == True,
            Site.is_active == True
        ).all()
        
        _add_log(db, search_id, "info", f"{len(competitor_sites)} aktif rakip site bulundu")
        
        # Rakip sayfalarını filtrele (meta title, description veya URL'de arama terimi geçen)
        from core.scraper import scraper
        from bs4 import BeautifulSoup
        
        competitor_pages = []
        total_pages = 0
        for site in competitor_sites:
            pages = db.query(Page).filter(Page.site_id == site.id).all()
            total_pages += len(pages)
            for page in pages:
                # Meta bilgilerini al (title ve URL'den)
                text_to_search = f"{page.title or ''} {page.url}".lower()
                if search_term.lower() in text_to_search:
                    # Meta description'ı çek (sayfa içeriğinden) - sadece gerekirse
                    meta_description = None
                    try:
                        # HTML'den meta description çıkar
                        html = await scraper._fetch_url(page.url)
                        if html:
                            soup = BeautifulSoup(html, 'lxml')
                            # meta name="description"
                            meta_desc_tag = soup.find('meta', attrs={'name': 'description'})
                            if meta_desc_tag and meta_desc_tag.get('content'):
                                meta_description = meta_desc_tag['content'].strip()
                            else:
                                # og:description'a bak
                                og_desc = soup.find('meta', property='og:description')
                                if og_desc and og_desc.get('content'):
                                    meta_description = og_desc['content'].strip()
                    except Exception as e:
                        error_msg = f"Meta description çekme hatası ({page.url}): {str(e)}"
                        print(f"⚠️ {error_msg}")
                        _add_log(db, search_id, "warning", error_msg)
                    
                    competitor_pages.append({
                        "page": page,
                        "site": site,
                        "meta_title": page.title,
                        "meta_description": meta_description,
                        "url": page.url
                    })
        
        _add_log(db, search_id, "info", f"{len(competitor_pages)} rakip sayfa bulundu (toplam {total_pages} sayfa taranı)")
        system_status.current_url = f"{len(competitor_pages)} rakip sayfa bulundu"
        
        # Google'dan ilk 10 sonucu al
        system_status.current_url = "Google'dan sonuçlar çekiliyor..."
        _add_log(db, search_id, "info", "Google'dan sonuçlar çekiliyor...")
        
        google_results = []
        try:
            google_search_results = await google_search.search(search_term, num_results=10)
            for result in google_search_results:
                google_results.append({
                    "title": result.title,
                    "description": result.description,
                    "url": result.url
                })
            _add_log(db, search_id, "success", f"Google'dan {len(google_results)} sonuç alındı")
        except Exception as e:
            error_msg = f"Google Search Hatası: {str(e)}"
            print(f"⚠️ {error_msg}")
            _add_log(db, search_id, "error", error_msg)
        
        # Tüm kaynakları analiz et
        all_sources = []
        
        # Rakip sayfaları (URL filtreleme ile)
        for item in competitor_pages:
            # URL kontrolü - tag/taxonomy gibi URL'leri atla
            if should_skip_url(item["url"]):
                _add_log(db, search_id, "info", f"URL atlandı (tag/taxonomy): {item['url'][:80]}")
                continue

            # İngilizce kontrolü - URL İngilizce değilse atla
            if not is_english_text(item["url"]):
                _add_log(db, search_id, "info", f"URL atlandı (İngilizce değil): {item['url'][:80]}")
                continue

            all_sources.append({
                "type": "competitor",
                "site_id": item["site"].id,
                "url": item["url"],
                "meta_title": item["meta_title"],
                "meta_description": item["meta_description"],
                "text": f"{item['meta_title'] or ''} {item['meta_description'] or ''} {item['url']}"
            })
        
        # Google sonuçları (URL filtreleme ile)
        for result in google_results:
            # URL kontrolü - tag/taxonomy gibi URL'leri atla
            if should_skip_url(result["url"]):
                _add_log(db, search_id, "info", f"Google URL atlandı (tag/taxonomy): {result['url'][:80]}")
                continue

            # İngilizce kontrolü - URL ve başlık İngilizce değilse atla
            url_english = is_english_text(result["url"])
            title_english = is_english_text(result["title"]) if result["title"] else False

            if not url_english or not title_english:
                _add_log(db, search_id, "info", f"Google URL atlandı (İngilizce değil): {result['url'][:80]}")
                continue

            all_sources.append({
                "type": "google",
                "site_id": None,
                "url": result["url"],
                "meta_title": result["title"],
                "meta_description": result["description"],
                "text": f"{result['title']} {result['description']}"
            })
        
        system_status.current_url = f"{len(all_sources)} kaynak analiz ediliyor..."
        _add_log(db, search_id, "info", f"Toplam {len(all_sources)} kaynak entity analizine başlanıyor...")
        
        # Her kaynağı analiz et
        saved_count = 0
        exact_count = 0
        partial_count = 0
        low_count = 0
        
        for i, source in enumerate(all_sources):
            try:
                system_status.current_url = f"Analiz: {i+1}/{len(all_sources)} - {source['url'][:50]}..."
                
                # İptal kontrolü
                search = db.query(EntitySearch).filter(EntitySearch.id == search_id).first()
                if search and search.cancelled:
                    _add_log(db, search_id, "warning", "Arama iptal edildi, işlem durduruluyor...")
                    break
                
                # YENİ MANTIK: Önce AI'ya gönder, entity'leri çıkarsın
                try:
                    # AI servisini seç
                    if ai_provider == "deepseek":
                        ai_service = deepseek_service
                        ai_name = "Deepseek"
                    else:
                        ai_service = gemini_service
                        ai_name = "Gemini"

                    _add_log(db, search_id, "info", f"Kaynak {i+1}: {ai_name}'ye gönderiliyor...")

                    # Meta bilgilerini detaylı olarak hazırla (None kontrolü yap)
                    meta_title = source.get('meta_title') or 'N/A'
                    meta_description = source.get('meta_description') or 'N/A'
                    url = source.get('url') or 'N/A'

                    meta_info = f"""Meta Title: {meta_title}
Meta Description: {meta_description}
URL: {url}
"""

                    # Log callback fonksiyonu
                    def log_callback(level, message):
                        _add_log(db, search_id, level, message)

                    # AI'ya gönderilecek tam metin (meta bilgileri + text)
                    full_text = f"{meta_info}\n{source['text']}"

                    # AI'ya gönderilen paketi log'a yazdır
                    _add_log(db, search_id, "info", f"🔵 {ai_name}'ye gönderilen paket:\n{full_text[:500]}...")

                    ai_entities = await ai_service.extract_entities(
                        full_text,
                        log_callback=log_callback
                    )

                    if ai_entities:
                        _add_log(db, search_id, "info", f"Kaynak {i+1}: {ai_name} {len(ai_entities)} entity buldu: {', '.join(ai_entities[:5])}")
                    else:
                        _add_log(db, search_id, "warning", f"Kaynak {i+1}: {ai_name} entity bulamadı")
                except Exception as e:
                    error_msg = f"{ai_name} hatası ({source['url']}): {str(e)}"
                    print(f"⚠️ {error_msg}")
                    _add_log(db, search_id, "error", error_msg)
                    ai_entities = []

                # AI'dan gelen entity'leri direkt kaydet (Wikipedia doğrulaması yapmadan)
                matches = []
                ai_entity_words = ai_entities if ai_entities else []

                # AI entity bulamadıysa log ekle
                if not ai_entities:
                    _add_log(db, search_id, "warning", f"Kaynak {i+1}: {ai_name} entity bulamadı, atlanıyor")
                
                # AI'dan gelen entity'leri direkt kaydet (Wikipedia olmadan)
                if ai_entities:
                    for entity_word in ai_entities:
                        # İngilizce kontrolü - İngilizce olmayan entity'leri atla
                        if not is_english_text(entity_word):
                            _add_log(db, search_id, "info", f"Entity atlandı (İngilizce değil): {entity_word}")
                            continue

                        # AI'dan gelen entity'yi kaydet
                        result = EntityResult(
                            search_id=search_id,
                            source_type=source["type"],
                            source_site_id=source["site_id"],
                            source_url=source["url"],
                            meta_title=source.get("meta_title") or "N/A",
                            meta_description=source.get("meta_description") or "N/A",
                            entity_name=entity_word,  # Direkt AI'dan gelen kelime
                            entity_url=None,  # Wikipedia eşleşmesi yok
                            match_type=MatchType.LOW,  # Düşük eşleşme olarak işaretle
                            match_score=50,  # Orta skor
                            matched_words=json.dumps([entity_word]),
                            wikipedia_summary=None,
                            is_ai_match=True  # AI'dan geldiği için True
                        )
                        db.add(result)
                        saved_count += 1
                        low_count += 1
                
                # Her 10 kayıtta bir commit ve log
                if saved_count > 0:
                    db.commit()
                    if saved_count % 10 == 0 or i < 3:
                        _add_log(db, search_id, "info", f"İlerleme: {saved_count} entity kaydedildi ({i+1}/{len(all_sources)} kaynak analiz edildi)")
                else:
                    # Hiç entity kaydedilmedi - debug için log ekle
                    if i < 5:  # İlk 5 kaynak için detaylı log
                        _add_log(db, search_id, "warning", f"Kaynak {i+1}: Hiç entity kaydedilemedi - {source['url'][:50]}")
            
            except Exception as e:
                error_msg = f"Entity analiz hatası ({source['url']}): {str(e)}"
                print(f"⚠️ {error_msg}")
                _add_log(db, search_id, "error", error_msg, json.dumps({"url": source["url"], "error": str(e)}))
                import traceback
                traceback.print_exc()
                continue
        
        db.commit()
        _add_log(db, search_id, "success", 
                 f"Analiz tamamlandı! Toplam {saved_count} entity bulundu (Tam: {exact_count}, Yarım: {partial_count}, Düşük: {low_count})")
        
        # Arama kaydını tamamlandı olarak işaretle
        search = db.query(EntitySearch).filter(EntitySearch.id == search_id).first()
        if search:
            search.status = "completed"
            db.commit()
        
        _add_log(db, search_id, "success", f"✅ Entity analizi başarıyla tamamlandı: {saved_count} entity kaydedildi")
        
        # System status güncelle
        system_status.last_completed_task = f"Entity Analizi: {search_term} ({saved_count} entity)"
        system_status.last_completed_time = datetime.utcnow()
        system_status.current_task = "Boşta"
        system_status.current_site = ""
        system_status.current_url = ""
        
        print(f"✅ Entity analizi tamamlandı: {search_term} ({saved_count} entity kaydedildi, {len(all_sources)} kaynak analiz edildi)")
        
    except Exception as e:
        error_msg = f"❌ Entity analiz hatası: {str(e)}"
        print(error_msg)
        import traceback
        traceback_str = traceback.format_exc()
        print(traceback_str)
        
        _add_log(db, search_id, "error", error_msg, traceback_str)
        
        # Hata durumunda arama kaydını güncelle
        try:
            search = db.query(EntitySearch).filter(EntitySearch.id == search_id).first()
            if search:
                search.status = "error"
                db.commit()
        except:
            pass
        
        system_status.current_task = "Boşta"
        system_status.current_site = ""
        system_status.current_url = ""
    finally:
        db.close()


# ============================================
# ARAMA DETAYLARI
# ============================================

@router.get("/search/{search_id}", response_class=HTMLResponse)
async def search_detail(request: Request, search_id: int, db: Session = Depends(get_db)):
    """Arama detay sayfası"""
    ensure_tables()
    
    # Migration kontrolü (is_cleaned kolonu için)
    try:
        from sqlalchemy import text
        from core.database import engine
        
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(entity_searches)"))
            columns = [row[1] for row in result]
            if 'is_cleaned' not in columns:
                conn.execute(text("ALTER TABLE entity_searches ADD COLUMN is_cleaned BOOLEAN DEFAULT 0"))
                conn.commit()
                print("✅ Entity Analyzer: is_cleaned kolonu eklendi")
    except Exception as e:
        print(f"⚠️ Migration kontrolü hatası: {e}")
    
    search = db.query(EntitySearch).filter(EntitySearch.id == search_id).first()
    if not search:
        raise HTTPException(status_code=404, detail="Arama bulunamadı")
    
    # Temizlik yapılmış mı kontrol et (is_cleaned flag'i için)
    is_cleaned = getattr(search, 'is_cleaned', False)
    
    # Tüm sonuçları al (debug için)
    all_results = db.query(EntityResult).filter(EntityResult.search_id == search_id).all()
    print(f"🔍 Debug: search_id={search_id}, toplam sonuç={len(all_results)}")
    
    # Sonuçları kategorilere göre ayır
    exact_results = db.query(EntityResult).filter(
        EntityResult.search_id == search_id,
        EntityResult.match_type == MatchType.EXACT
    ).order_by(desc(EntityResult.match_score)).all()
    
    partial_results = db.query(EntityResult).filter(
        EntityResult.search_id == search_id,
        EntityResult.match_type == MatchType.PARTIAL
    ).order_by(desc(EntityResult.match_score)).all()
    
    low_results = db.query(EntityResult).filter(
        EntityResult.search_id == search_id,
        EntityResult.match_type == MatchType.LOW
    ).order_by(desc(EntityResult.match_score)).all()
    
    # AI eşleşmeleri (Gemini ile bulunanlar)
    ai_results = db.query(EntityResult).filter(
        EntityResult.search_id == search_id,
        EntityResult.is_ai_match == True
    ).order_by(desc(EntityResult.match_score)).all()
    
    print(f"🔍 Debug: exact={len(exact_results)}, partial={len(partial_results)}, low={len(low_results)}, ai={len(ai_results)}")
    
    # En çok entity bulunan rakipler (yüzdelik oranla)
    from sqlalchemy import func
    competitor_stats = db.query(
        Site.name,
        func.count(EntityResult.id).label('entity_count')
    ).join(
        EntityResult, EntityResult.source_site_id == Site.id
    ).filter(
        EntityResult.search_id == search_id,
        Site.is_competitor == True
    ).group_by(Site.id, Site.name).order_by(desc('entity_count')).all()
    
    total_entities = len(all_results)
    competitor_percentages = []
    if total_entities > 0:
        for name, count in competitor_stats:
            percentage = round((count / total_entities) * 100, 1)
            competitor_percentages.append({
                "name": name,
                "count": count,
                "percentage": percentage
            })
    
    # Site bilgilerini ekle
    def enrich_results(results):
        enriched = []
        for result in results:
            site = None
            if result.source_site_id:
                site = db.query(Site).filter(Site.id == result.source_site_id).first()
            
            enriched.append({
                "result": result,
                "site": site
            })
        return enriched
    
    return templates.TemplateResponse("detail.html", {
        "request": request,
        "search": search,
        "exact_results": enrich_results(exact_results),
        "partial_results": enrich_results(partial_results),
        "low_results": enrich_results(low_results),
        "ai_results": enrich_results(ai_results),
        "competitor_percentages": competitor_percentages,
        "is_cleaned": is_cleaned,
        "current_page": "entity_analyzer"
    })


# ============================================
# API ENDPOINTS
# ============================================

@router.get("/api/searches", tags=["API"])
async def get_searches(db: Session = Depends(get_db)):
    """Önceki aramaları döndür"""
    ensure_tables()
    
    searches = db.query(EntitySearch).order_by(desc(EntitySearch.created_at)).limit(50).all()
    
    searches_data = []
    for search in searches:
        total_count = db.query(func.count(EntityResult.id)).filter(
            EntityResult.search_id == search.id
        ).scalar() or 0
        
        searches_data.append({
            "id": search.id,
            "search_term": search.search_term,
            "created_at": search.created_at.isoformat(),
            "total_results": total_count
        })
    
    return JSONResponse(searches_data)


@router.get("/api/search/{search_id}/logs", tags=["API"])
async def get_search_logs(search_id: int, db: Session = Depends(get_db)):
    """Arama loglarını getir"""
    ensure_tables()
    
    logs = db.query(EntitySearchLog).filter(
        EntitySearchLog.search_id == search_id
    ).order_by(EntitySearchLog.created_at).all()
    
    return JSONResponse({
        "logs": [
            {
                "id": log.id,
                "level": log.level,
                "message": log.message,
                "details": log.details,
                "created_at": log.created_at.isoformat()
            }
            for log in logs
        ]
    })


@router.post("/search/{search_id}/clean-duplicates", tags=["API"])
async def clean_duplicate_entities(
    search_id: int,
    db: Session = Depends(get_db)
):
    """Aynı entity'leri temizle - Her entity_name için sadece bir kayıt tut"""
    ensure_tables()
    
    try:
        search = db.query(EntitySearch).filter(EntitySearch.id == search_id).first()
        if not search:
            return JSONResponse({
                "status": "error",
                "message": "Arama bulunamadı"
            }, status_code=404)
        
        # Tüm sonuçları al
        all_results = db.query(EntityResult).filter(EntityResult.search_id == search_id).all()
        
        # Entity name'e göre grupla (case-insensitive)
        entity_groups = {}
        for result in all_results:
            entity_key = result.entity_name.lower().strip()
            if entity_key not in entity_groups:
                entity_groups[entity_key] = []
            entity_groups[entity_key].append(result)
        
        # Her grup için en iyi kaydı tut, diğerlerini sil
        deleted_count = 0
        kept_count = 0
        
        for entity_key, results in entity_groups.items():
            if len(results) > 1:
                # En iyi kaydı bul (öncelik: match_score, sonra id)
                best_result = max(results, key=lambda r: (r.match_score or 0, r.id))
                
                # Diğerlerini sil
                for result in results:
                    if result.id != best_result.id:
                        db.delete(result)
                        deleted_count += 1
                    else:
                        kept_count += 1
            else:
                kept_count += 1
        
        # Temizlik yapıldı olarak işaretle
        search.is_cleaned = True
        
        db.commit()
        
        return JSONResponse({
            "status": "success",
            "message": f"{deleted_count} tekrar eden entity silindi, {kept_count} benzersiz entity kaldı",
            "deleted_count": deleted_count,
            "kept_count": kept_count
        })
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "status": "error",
            "message": f"Temizlik hatası: {str(e)}"
        }, status_code=500)


@router.get("/search/{search_id}/entities-list", tags=["API"])
async def get_entities_list(
    search_id: int,
    db: Session = Depends(get_db)
):
    """Tüm unique entity'leri virgülle ayrılmış liste olarak döndür"""
    ensure_tables()

    try:
        search = db.query(EntitySearch).filter(EntitySearch.id == search_id).first()
        if not search:
            return JSONResponse({
                "status": "error",
                "message": "Arama bulunamadı"
            }, status_code=404)

        # Tüm entity'leri al
        all_results = db.query(EntityResult).filter(EntityResult.search_id == search_id).all()

        # Unique entity name'leri topla (case-insensitive, temizlenmiş)
        unique_entities = set()
        for result in all_results:
            entity_name = result.entity_name.strip()
            # Tek tırnak ve çift tırnak temizle
            entity_name = entity_name.strip("'\"").strip()
            if entity_name and len(entity_name) >= 2:
                # Küçük harfe çevirip set'e ekle
                unique_entities.add(entity_name.lower())

        # Alfabetik sırala
        sorted_entities = sorted(list(unique_entities))

        # Virgülle ayrılmış string oluştur
        entities_csv = ", ".join(sorted_entities)

        return JSONResponse({
            "status": "success",
            "entities": sorted_entities,
            "entities_csv": entities_csv,
            "count": len(sorted_entities)
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)


@router.post("/search/{search_id}/wikipedia-check", tags=["API"])
async def wikipedia_check_entities(
    search_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Temiz listedeki entity'leri Wikipedia'da doğrula"""
    ensure_tables()
    
    try:
        search = db.query(EntitySearch).filter(EntitySearch.id == search_id).first()
        if not search:
            return JSONResponse({
                "status": "error",
                "message": "Arama bulunamadı"
            }, status_code=404)
        
        # Temizlik yapılmış mı kontrol et
        is_cleaned = getattr(search, 'is_cleaned', False)
        if not is_cleaned:
            return JSONResponse({
                "status": "error",
                "message": "Önce 'Aynı Entity'leri Temizle' işlemini yapmalısınız"
            }, status_code=400)
        
        # Arka planda Wikipedia doğrulama işlemini başlat
        background_tasks.add_task(wikipedia_check_task, search_id)
        
        return JSONResponse({
            "status": "started",
            "message": "Wikipedia doğrulama işlemi başlatıldı"
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "status": "error",
            "message": f"Wikipedia check hatası: {str(e)}"
        }, status_code=500)


async def wikipedia_check_task(search_id: int):
    """Wikipedia doğrulama görevi (arka planda çalışır)"""
    from core.database import SessionLocal
    
    db = SessionLocal()
    try:
        search = db.query(EntitySearch).filter(EntitySearch.id == search_id).first()
        if not search:
            return
        
        _add_log(db, search_id, "info", "Wikipedia doğrulama işlemi başlatıldı...")
        
        # Temiz listedeki tüm entity'leri al (sadece kelimeler - entity_name'leri)
        all_results = db.query(EntityResult).filter(EntityResult.search_id == search_id).all()
        
        # Benzersiz entity name'leri al (sadece kelimeler)
        unique_entities = set()
        for result in all_results:
            entity_name = result.entity_name.strip()
            
            # Tek tırnak ve çift tırnak işaretlerini temizle (baştan ve sondan)
            entity_name = entity_name.strip("'\"")
            # İçerideki tek tırnak ve çift tırnak karakterlerini de temizle
            entity_name = entity_name.replace("'", "").replace('"', '')
            entity_name = entity_name.strip()
            
            # Sadece kelime olduğundan emin ol (boşluk, noktalama yok, sadece harf/rakam)
            if entity_name and ' ' not in entity_name and len(entity_name) >= 2:
                # Sadece alfanumerik karakterler veya tire/alt çizgi içeren kelimeler
                cleaned_name = entity_name.replace('-', '').replace('_', '')
                if cleaned_name.isalnum():
                    # Temizlenmiş kelimeyi ekle (küçük harfe çevir)
                    unique_entities.add(entity_name.lower())
        
        _add_log(db, search_id, "info", f"{len(unique_entities)} benzersiz entity Wikipedia'da doğrulanıyor...")
        
        updated_count = 0
        for i, entity_word in enumerate(unique_entities):
            try:
                # Entity kelimesini temizle (tek tırnak, çift tırnak, boşluk vb.)
                clean_word = entity_word.strip().strip("'\"").strip()
                if not clean_word or len(clean_word) < 2:
                    continue
                
                _add_log(db, search_id, "info", f"Wikipedia'da aranıyor: '{clean_word}'")
                
                # Her entity'yi Wikipedia'da ara (temizlenmiş kelimeyi kullan)
                # Wikipedia'dan entity bilgisini direkt al (text parametresi gereksiz)
                from entity_analyzer.analyzer import WikipediaAPI
                wikipedia = WikipediaAPI()
                entity_info = await wikipedia.get_entity_info(clean_word)

                if entity_info:
                    # Wikipedia'da bulundu, EntityMatch oluştur
                    from entity_analyzer.analyzer import EntityMatch
                    from entity_analyzer.models import MatchType
                    match = EntityMatch(
                        entity_name=entity_info.get("title", clean_word),
                        entity_url=entity_info.get("url", ""),
                        match_type=MatchType.EXACT,
                        match_score=100,
                        matched_words=[clean_word],
                        wikipedia_summary=entity_info.get("extract", "")
                    )
                else:
                    match = None
                
                if match:
                    # Bu entity_name'e sahip tüm kayıtları güncelle
                    results_to_update = db.query(EntityResult).filter(
                        EntityResult.search_id == search_id,
                        func.lower(EntityResult.entity_name) == entity_word.lower()
                    ).all()
                    
                    for result in results_to_update:
                        result.entity_name = match.entity_name
                        result.entity_url = match.entity_url
                        result.match_type = match.match_type
                        result.match_score = match.match_score
                        result.matched_words = json.dumps(match.matched_words)
                        result.wikipedia_summary = match.wikipedia_summary
                        updated_count += 1
                    
                    # Her 10 güncellemede bir commit
                    if updated_count % 10 == 0:
                        db.commit()
                        _add_log(db, search_id, "info", f"İlerleme: {updated_count} entity Wikipedia'da doğrulandı ({i+1}/{len(unique_entities)})")
                else:
                    _add_log(db, search_id, "warning", f"Wikipedia'da eşleşme bulunamadı: {entity_word}")
                
            except Exception as e:
                _add_log(db, search_id, "warning", f"Wikipedia doğrulama hatası ({entity_word}): {str(e)[:100]}")
                continue
        
        db.commit()
        _add_log(db, search_id, "success", f"✅ Wikipedia doğrulama tamamlandı! {updated_count} entity güncellendi")
        
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        _add_log(db, search_id, "error", f"Wikipedia check hatası: {str(e)}")
    finally:
        db.close()

