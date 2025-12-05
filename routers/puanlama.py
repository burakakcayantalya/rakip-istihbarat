# ============================================
# Rakip İçerik İstihbarat Sistemi V2
# Puanlama Router - Tazelik Tablosu
# ============================================

from fastapi import APIRouter, Request, Depends, Query, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import hashlib

from config import settings
from core.database import get_db, Page, Log, ActionType, Site, get_setting
from core.scoring import scoring_engine
from core.scraper import scraper
from core.scheduler import system_status


def get_site_color(site_id: int) -> str:
    """Site ID'sine göre tutarlı renk üret"""
    # Önceden tanımlı renkler (RGB formatında)
    colors = [
        (239, 68, 68),   # Kırmızı
        (59, 130, 246),  # Mavi
        (34, 197, 94),   # Yeşil
        (168, 85, 247),  # Mor
        (245, 158, 11),  # Turuncu
        (236, 72, 153),  # Pembe
        (14, 165, 233),  # Cyan
        (251, 146, 60),  # Turuncu 2
        (139, 92, 246),  # Mor 2
        (20, 184, 166),  # Teal
        (244, 63, 94),   # Kırmızı 2
        (59, 130, 246),  # Mavi 2
    ]
    
    # Site ID'sine göre renk seç (tutarlı olması için hash kullan)
    color_index = site_id % len(colors)
    r, g, b = colors[color_index]
    
    return f"rgba({r}, {g}, {b}, 0.8)"

router = APIRouter(prefix="/puanlama", tags=["Puanlama"])
templates = Jinja2Templates(directory=str(settings.TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def puanlama_page(
    request: Request, 
    db: Session = Depends(get_db),
    period: str = Query("week", regex="^(week|month|year)$")
):
    """Puanlama/Tazelik tablosu sayfası"""
    
    # Dönem seçimi
    if period == "week":
        days = 7
        period_label = "Haftalık"
    elif period == "month":
        days = 30
        period_label = "Aylık"
    else:
        days = 365
        period_label = "Yıllık"
    
    # Tüm sitelerin sıralamasını al
    rankings = scoring_engine.get_all_sites_ranking(db, days=days)
    
    # Freshness ayarını al
    freshness_days = int(get_setting(db, "FRESHNESS_THRESHOLD_DAYS") or 45)
    today = datetime.utcnow()
    freshness_threshold = today - timedelta(days=freshness_days)
    
    # Her site için freshness hesapla (veritabanındaki sitemap_lastmod kullanarak)
    # Bu çok daha hızlı çünkü sitemap parse etmiyoruz, sadece DB sorgusu yapıyoruz
    rankings_with_freshness = []
    for rank in rankings:
        site_id = rank["site_id"]
        
        # Veritabanından direkt freshness hesapla (sitemap_lastmod kullanarak)
        # SQL sorgusu ile çok daha hızlı - sitemap parse etmiyoruz!
        freshness_query = db.query(
            func.count(Page.id).label('total'),
            func.sum(
                case(
                    (Page.sitemap_lastmod.isnot(None), 
                     case(
                         ((Page.sitemap_lastmod >= freshness_threshold), 1),
                         else_=0
                     )),
                    else_=0
                )
            ).label('fresh')
        ).filter(Page.site_id == site_id)
        
        result = freshness_query.first()
        total_pages = result.total or 0
        fresh_pages = result.fresh or 0
        
        # Freshness yüzdesi
        freshness_percentage = 0
        freshness_score = 0
        if total_pages > 0:
            freshness_percentage = (fresh_pages / total_pages) * 100
            freshness_score = int(freshness_percentage)  # 0-100 arası skor
        
        # Rank'a freshness bilgilerini ekle
        rank["freshness_score"] = freshness_score
        rank["freshness_percentage"] = freshness_percentage
        rank["fresh_pages"] = fresh_pages
        rank["total_pages"] = total_pages
        rankings_with_freshness.append(rank)
    
    # Rakip ve bizim sitelerimizi ayır
    competitor_rankings = [r for r in rankings_with_freshness if r.get("is_competitor", False)]
    our_rankings = [r for r in rankings_with_freshness if not r.get("is_competitor", False)]
    
    # Genel istatistikler
    stats = scoring_engine.get_activity_summary(db, days=days)
    
    # Günlük aktivite grafiği için veri (SITEMAP LASTMOD TARİHİNE GÖRE)
    # TÜM aktif siteleri al (rakip + bizim sitelerimiz)
    all_active_sites = db.query(Site).filter(Site.is_active == True).all()
    all_site_ids = [s.id for s in all_active_sites]
    all_pages = db.query(Page).filter(Page.site_id.in_(all_site_ids)).all()
    
    # Tüm siteleri ve renklerini al
    site_colors = {site.id: get_site_color(site.id) for site in all_active_sites}
    
    # Günlük aktivite sayıları (sitemap_lastmod tarihine göre) - Site bazında
    daily_data = []
    today = datetime.utcnow().date()
    
    for i in range(min(days, 30)):  # Max 30 gün göster
        # Bugünden geriye doğru say (i=0 bugün, i=1 dün, ...)
        target_date = today - timedelta(days=i)
        
        day_new = 0
        day_update = 0
        site_updates = {}  # {site_id: {new: count, update: count}}
        
        # Her sayfa için sitemap_lastmod tarihine bak
        for page in all_pages:
            if not page.sitemap_lastmod:
                continue
            
            # lastmod tarihini normalize et (timezone bilgisini kaldır)
            lastmod = page.sitemap_lastmod
            if lastmod.tzinfo:
                lastmod = lastmod.replace(tzinfo=None)
            
            # Bu gün içinde mi kontrol et (sadece tarih karşılaştırması)
            lastmod_date = lastmod.date()
            
            if lastmod_date == target_date:
                # first_seen_at ile karşılaştır - yeni mi güncelleme mi?
                first_seen = page.first_seen_at
                site_id = page.site_id
                
                if site_id not in site_updates:
                    site_updates[site_id] = {"new": 0, "update": 0}
                
                if first_seen:
                    if first_seen.tzinfo:
                        first_seen = first_seen.replace(tzinfo=None)
                    first_seen_date = first_seen.date()
                    
                    # Eğer first_seen_at ile lastmod aynı günse yeni içerik
                    if first_seen_date == lastmod_date:
                        day_new += 1
                        site_updates[site_id]["new"] += 1
                    else:
                        # Farklı günlerdeyse güncelleme
                        day_update += 1
                        site_updates[site_id]["update"] += 1
                else:
                    # first_seen_at yoksa güncelleme say (güvenli tarafta ol)
                    day_update += 1
                    site_updates[site_id]["update"] += 1
        
        daily_data.append({
            "date": target_date.strftime("%d.%m"),
            "new": day_new,
            "update": day_update,
            "total": day_new + day_update,
            "site_updates": site_updates  # Site bazında güncellemeler
        })
    
    daily_data.reverse()  # Eski tarihten yeniye
    
    # Tüm siteleri ve renklerini template'e gönder
    all_sites_list = [
        {
            "id": site.id, 
            "name": site.name, 
            "color": get_site_color(site.id),
            "is_competitor": site.is_competitor
        }
        for site in all_active_sites
    ]
    
    return templates.TemplateResponse("puanlama.html", {
        "request": request,
        "rankings": rankings_with_freshness,
        "competitor_rankings": competitor_rankings,
        "our_rankings": our_rankings,
        "stats": stats,
        "daily_data": daily_data,
        "all_sites": all_sites_list,
        "site_colors": site_colors,
        "period": period,
        "period_label": period_label,
        "days": days,
        "freshness_days": freshness_days,
        "current_page": "puanlama"
    })


@router.get("/api/chart-data", tags=["API"])
async def get_chart_data(
    db: Session = Depends(get_db),
    days: int = Query(7, ge=1, le=365)
):
    """Grafik için veri döndür (SITEMAP LASTMOD TARİHİNE GÖRE - TÜM SİTELER)"""
    
    # TÜM aktif siteleri al (rakip + bizim sitelerimiz)
    all_active_sites = db.query(Site).filter(Site.is_active == True).all()
    all_site_ids = [s.id for s in all_active_sites]
    all_pages = db.query(Page).filter(Page.site_id.in_(all_site_ids)).all()
    
    # Günlük aktivite sayıları (sitemap_lastmod tarihine göre)
    daily_data = []
    today = datetime.utcnow().date()
    
    for i in range(min(days, 30)):
        # Bugünden geriye doğru say (i=0 bugün, i=1 dün, ...)
        target_date = today - timedelta(days=i)
        
        day_new = 0
        day_update = 0
        
        # Her sayfa için sitemap_lastmod tarihine bak
        for page in all_pages:
            if not page.sitemap_lastmod:
                continue
            
            # lastmod tarihini normalize et
            lastmod = page.sitemap_lastmod
            if lastmod.tzinfo:
                lastmod = lastmod.replace(tzinfo=None)
            
            # Bu gün içinde mi kontrol et (sadece tarih karşılaştırması)
            lastmod_date = lastmod.date()
            
            if lastmod_date == target_date:
                # first_seen_at ile karşılaştır
                first_seen = page.first_seen_at
                if first_seen:
                    if first_seen.tzinfo:
                        first_seen = first_seen.replace(tzinfo=None)
                    first_seen_date = first_seen.date()
                    
                    # Eğer first_seen_at ile lastmod aynı günse yeni içerik
                    if first_seen_date == lastmod_date:
                        day_new += 1
                    else:
                        day_update += 1
                else:
                    # first_seen_at yoksa güncelleme say
                    day_update += 1
        
        daily_data.append({
            "date": target_date.strftime("%d.%m"),
            "new": day_new,
            "update": day_update
        })
    
    daily_data.reverse()
    return daily_data


@router.post("/recheck-all-sites", tags=["API"])
async def recheck_all_sites(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Tüm sitelerin sitemap'lerini kontrol et ve sitemap_lastmod'ları güncelle"""
    
    # Tüm aktif siteleri al
    sites = db.query(Site).filter(Site.is_active == True).all()
    
    if not sites:
        return JSONResponse({
            "status": "error",
            "message": "Kontrol edilecek site bulunamadı"
        })
    
    # Arka planda çalıştır
    background_tasks.add_task(recheck_sitemaps_task, [s.id for s in sites])
    
    return JSONResponse({
        "status": "started",
        "message": f"{len(sites)} site için sitemap kontrolü başlatıldı",
        "sites_count": len(sites)
    })


async def recheck_sitemaps_task(site_ids: List[int]):
    """Sitemap kontrol görevi (arka planda çalışır)"""
    from core.database import SessionLocal
    
    db = SessionLocal()
    try:
        for site_id in site_ids:
            site = db.query(Site).filter(Site.id == site_id).first()
            if not site:
                continue
            
            system_status.current_task = "Sitemap kontrolü"
            system_status.current_site = site.name
            system_status.current_url = f"Sitemap: {site.domain}"
            
            # Sitemap URL'ini bul
            sitemap_url = site.sitemap_url
            if not sitemap_url:
                # Otomatik bul
                sitemaps = await scraper.find_sitemap(site.domain)
                if sitemaps:
                    sitemap_url = sitemaps[0]
                    site.sitemap_url = sitemap_url
                    db.commit()
            
            if not sitemap_url:
                print(f"⚠️ Sitemap bulunamadı: {site.domain}")
                continue
            
            # Sitemap'i parse et
            try:
                sitemap_result = await scraper.parse_sitemap(sitemap_url)
                sitemap_urls = sitemap_result.urls
                
                # Mevcut sayfaları al
                existing_pages = db.query(Page).filter(Page.site_id == site_id).all()
                existing_map: Dict[str, Page] = {p.url: p for p in existing_pages}
                
                # Sitemap'teki lastmod bilgilerini güncelle
                updated_count = 0
                for sitemap_url_obj in sitemap_urls:
                    url = sitemap_url_obj.url
                    lastmod = sitemap_url_obj.lastmod
                    
                    if url in existing_map:
                        existing_page = existing_map[url]
                        if lastmod:
                            lastmod_naive = lastmod.replace(tzinfo=None) if lastmod.tzinfo else lastmod
                            existing_page.sitemap_lastmod = lastmod_naive
                            updated_count += 1
                
                db.commit()
                print(f"✅ {site.name}: {updated_count} sayfa güncellendi")
                
            except Exception as e:
                print(f"❌ Hata ({site.name}): {str(e)}")
                continue
        
        system_status.current_task = "Boşta"
        system_status.current_site = ""
        system_status.current_url = ""
        
    finally:
        db.close()


@router.get("/api/activity-logs", tags=["API"])
async def get_activity_logs(
    db: Session = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
    site_id: Optional[int] = Query(None)  # Filtreleme için
):
    """Aktivite logları - Content Update ve New Content uyarıları (TÜM SİTELER)"""
    
    since = datetime.utcnow() - timedelta(days=days)
    
    # TÜM aktif siteleri al (rakip + bizim sitelerimiz)
    sites_query = db.query(Site.id).filter(Site.is_active == True)
    if site_id:
        sites_query = sites_query.filter(Site.id == site_id)
    site_ids = sites_query.subquery()
    all_pages = db.query(Page).filter(Page.site_id.in_(site_ids)).all()
    
    logs = []
    
    for page in all_pages:
        if not page.sitemap_lastmod:
            continue
        
        # lastmod tarihini normalize et
        lastmod = page.sitemap_lastmod
        if lastmod.tzinfo:
            lastmod = lastmod.replace(tzinfo=None)
        
        # Belirtilen süre içinde mi?
        if lastmod >= since:
            # first_seen_at ile karşılaştır
            first_seen = page.first_seen_at
            if first_seen:
                if first_seen.tzinfo:
                    first_seen = first_seen.replace(tzinfo=None)
                
                first_seen_date = first_seen.date()
                lastmod_date = lastmod.date()
                
                # Site bilgisini al
                site = db.query(Site).filter(Site.id == page.site_id).first()
                
                if first_seen_date == lastmod_date:
                    # Yeni içerik
                    logs.append({
                        "type": "new",
                        "site_id": page.site_id,
                        "site_name": site.name if site else "Bilinmeyen",
                        "site_color": get_site_color(page.site_id),
                        "is_competitor": site.is_competitor if site else False,
                        "page_title": page.title or page.url[:50],
                        "url": page.url,
                        "date": lastmod_date.strftime("%d.%m.%Y"),
                        "_timestamp": lastmod  # Geçici olarak datetime tut (sıralama için)
                    })
                else:
                    # Güncelleme - kaç gün sonra güncellendi?
                    days_between = (lastmod_date - first_seen_date).days
                    logs.append({
                        "type": "update",
                        "site_id": page.site_id,
                        "site_name": site.name if site else "Bilinmeyen",
                        "site_color": get_site_color(page.site_id),
                        "is_competitor": site.is_competitor if site else False,
                        "page_title": page.title or page.url[:50],
                        "url": page.url,
                        "date": lastmod_date.strftime("%d.%m.%Y"),
                        "first_seen_date": first_seen_date.strftime("%d.%m.%Y"),
                        "days_between": days_between,
                        "_timestamp": lastmod  # Geçici olarak datetime tut (sıralama için)
                    })
    
    # Tarihe göre sırala (en yeni önce) - datetime objesi ile sırala
    logs.sort(key=lambda x: x["_timestamp"], reverse=True)
    
    # Timestamp'i string'e çevir (JSON serialization için)
    for log in logs:
        log["timestamp"] = log["_timestamp"].isoformat()
        del log["_timestamp"]
    
    return JSONResponse(logs)


@router.get("/api/all-sites", tags=["API"])
async def get_all_sites(db: Session = Depends(get_db)):
    """Tüm aktif siteleri ve renklerini döndür (rakip + bizim sitelerimiz)"""
    all_sites = db.query(Site).filter(Site.is_active == True).order_by(Site.is_competitor.desc(), Site.name).all()
    
    sites = []
    for site in all_sites:
        sites.append({
            "id": site.id,
            "name": site.name,
            "color": get_site_color(site.id),
            "is_competitor": site.is_competitor
        })
    
    return JSONResponse(sites)

