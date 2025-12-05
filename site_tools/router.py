# ============================================
# Site Tools - Router & Endpoints
# DÜZELTİLMİŞ: Freshness ve HTTP fetch
# ============================================

from fastapi import APIRouter, Request, Depends, HTTPException, BackgroundTasks, Query, Form, Body
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, or_, case
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path
import asyncio

from core.database import get_db, Site, Page, get_setting, set_setting
from core.scheduler import system_status
from .models import PageAnalysis, InternalLink, init_site_tools_tables
from .analyzer import site_analyzer
from .wordpress_fix import WordPressLinkFixer
from fastapi import Body

# Template dizinleri - hem site_tools içindeki hem ana templates
SITE_TOOLS_TEMPLATE_DIR = Path(__file__).parent / "templates"
MAIN_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"

templates = Jinja2Templates(directory=[str(SITE_TOOLS_TEMPLATE_DIR), str(MAIN_TEMPLATE_DIR)])

router = APIRouter(prefix="/site-tools", tags=["Site Tools"])

# Tablo oluşturma (ilk çalıştırmada)
_tables_initialized = False


def ensure_tables():
    """Tabloların var olduğundan emin ol"""
    global _tables_initialized
    if not _tables_initialized:
        init_site_tools_tables()
        _tables_initialized = True


# ============================================
# YENİ SITE EKLEME
# ============================================

@router.get("/add", response_class=HTMLResponse)
async def add_site_form(request: Request):
    """Site Araçları için yeni site ekleme formu"""
    return templates.TemplateResponse("site_tools_add.html", {
        "request": request,
        "current_page": "site_tools"
    })


@router.post("/add")
async def add_site(
    request: Request,
    name: str = Form(...),
    domain: str = Form(...),
    sitemap_url: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Site Araçları için yeni site ekle (is_competitor=False)"""
    
    # Domain temizliği
    domain = domain.lower().strip()
    if domain.startswith("http://"):
        domain = domain[7:]
    if domain.startswith("https://"):
        domain = domain[8:]
    if domain.startswith("www."):
        domain = domain[4:]
    if domain.endswith("/"):
        domain = domain[:-1]
    
    # Aynı domain var mı kontrol et
    existing = db.query(Site).filter(Site.domain == domain).first()
    if existing:
        return templates.TemplateResponse("site_tools_add.html", {
            "request": request,
            "error": "Bu domain zaten ekli!",
            "current_page": "site_tools"
        })
    
    # Yeni site oluştur (is_competitor=False - Site Araçları için)
    site = Site(
        name=name,
        domain=domain,
        sitemap_url=sitemap_url,
        is_competitor=False  # Site Araçları için her zaman False
    )
    db.add(site)
    db.commit()
    db.refresh(site)
    
    return RedirectResponse(url=f"/site-tools/site/{site.id}", status_code=303)


# ============================================
# ANA SAYFA - DASHBOARD ÖZET
# ============================================

@router.get("/", response_class=HTMLResponse)
async def site_tools_index(request: Request, db: Session = Depends(get_db)):
    """Site Tools ana sayfası - özet dashboard"""
    ensure_tables()
    
    # Sadece "benim sitelerim"i al (is_competitor=False)
    my_sites = db.query(Site).filter(Site.is_competitor == False).all()
    
    # Freshness ayarını al
    freshness_days = int(get_setting(db, "FRESHNESS_THRESHOLD_DAYS") or 45)
    threshold_date = datetime.utcnow() - timedelta(days=freshness_days)
    
    # Her site için özet istatistikler
    sites_summary = []
    for site in my_sites:
        # Toplam sayfa
        page_count = db.query(func.count(Page.id)).filter(Page.site_id == site.id).scalar() or 0
        
        # Analiz edilmiş sayfa
        page_ids_subq = db.query(Page.id).filter(Page.site_id == site.id).subquery()
        analyzed_count = db.query(func.count(PageAnalysis.id)).filter(
            PageAnalysis.page_id.in_(page_ids_subq)
        ).scalar() or 0
        
        # Problemli sayfalar
        h1_issues = db.query(func.count(PageAnalysis.id)).filter(
            PageAnalysis.page_id.in_(page_ids_subq),
            PageAnalysis.h1_status.in_(["missing", "duplicate"])
        ).scalar() or 0
        
        schema_issues = db.query(func.count(PageAnalysis.id)).filter(
            PageAnalysis.page_id.in_(page_ids_subq),
            PageAnalysis.schema_status.in_(["missing", "error"])
        ).scalar() or 0
        
        broken_links = db.query(func.count(InternalLink.id)).filter(
            InternalLink.source_page_id.in_(page_ids_subq),
            InternalLink.is_broken == True
        ).scalar() or 0
        
        # Freshness - last_changed_at veya first_seen_at kullan
        # COALESCE: last_changed_at NULL ise first_seen_at kullan
        stale_pages = db.query(func.count(Page.id)).filter(
            Page.site_id == site.id,
            or_(
                Page.last_changed_at < threshold_date,
                Page.last_changed_at.is_(None)
            )
        ).scalar() or 0
        
        # Aslında first_seen_at'e bakmak daha mantıklı - hiç güncelleme olmamışsa
        # last_changed_at NULL demek ilk taramadan beri değişmemiş demek
        stale_pages_v2 = db.query(func.count(Page.id)).filter(
            Page.site_id == site.id,
            func.coalesce(Page.last_changed_at, Page.first_seen_at) < threshold_date
        ).scalar() or 0
        
        sites_summary.append({
            "site": site,
            "page_count": page_count,
            "analyzed_count": analyzed_count,
            "h1_issues": h1_issues,
            "schema_issues": schema_issues,
            "broken_links": broken_links,
            "stale_pages": stale_pages_v2,
            "freshness_days": freshness_days
        })
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "sites_summary": sites_summary,
        "current_page": "site_tools"
    })


# ============================================
# SITE DETAY SAYFASI
# ============================================

@router.get("/site/{site_id}", response_class=HTMLResponse)
async def site_detail(request: Request, site_id: int, db: Session = Depends(get_db)):
    """Site detay sayfası - tüm analizler"""
    ensure_tables()
    
    site = db.query(Site).filter(Site.id == site_id, Site.is_competitor == False).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site bulunamadı veya bu sizin siteniz değil")
    
    # Sayfaları al
    pages = db.query(Page).filter(Page.site_id == site_id).all()
    page_ids = [p.id for p in pages]
    
    # Analizleri al
    analyses = {}
    if page_ids:
        for analysis in db.query(PageAnalysis).filter(PageAnalysis.page_id.in_(page_ids)).all():
            analyses[analysis.page_id] = analysis
    
    # Sayfa + analiz birleştir
    pages_with_analysis = []
    for page in pages:
        analysis = analyses.get(page.id)
        pages_with_analysis.append({
            "page": page,
            "analysis": analysis
        })
    
    # İstatistikler
    h1_ok = sum(1 for p in pages_with_analysis if p["analysis"] and p["analysis"].h1_status == "ok")
    h1_missing = sum(1 for p in pages_with_analysis if p["analysis"] and p["analysis"].h1_status == "missing")
    h1_duplicate = sum(1 for p in pages_with_analysis if p["analysis"] and p["analysis"].h1_status == "duplicate")
    
    schema_ok = sum(1 for p in pages_with_analysis if p["analysis"] and p["analysis"].schema_status == "ok")
    schema_missing = sum(1 for p in pages_with_analysis if p["analysis"] and p["analysis"].schema_status == "missing")
    schema_error = sum(1 for p in pages_with_analysis if p["analysis"] and p["analysis"].schema_status == "error")
    
    total_broken_links = db.query(func.count(InternalLink.id)).filter(
        InternalLink.source_page_id.in_(page_ids),
        InternalLink.is_broken == True
    ).scalar() or 0 if page_ids else 0
    
    total_redirects = db.query(func.count(InternalLink.id)).filter(
        InternalLink.source_page_id.in_(page_ids),
        InternalLink.is_redirect == True
    ).scalar() or 0 if page_ids else 0
    
    return templates.TemplateResponse("detail.html", {
        "request": request,
        "site": site,
        "pages_with_analysis": pages_with_analysis,
        "stats": {
            "h1_ok": h1_ok,
            "h1_missing": h1_missing,
            "h1_duplicate": h1_duplicate,
            "schema_ok": schema_ok,
            "schema_missing": schema_missing,
            "schema_error": schema_error,
            "total_broken_links": total_broken_links,
            "total_redirects": total_redirects
        },
        "current_page": "site_tools"
    })


# ============================================
# FRESHNESS RAPORU
# ============================================

@router.get("/freshness/{site_id}", response_class=HTMLResponse)
async def freshness_report(request: Request, site_id: int, db: Session = Depends(get_db)):
    """
    Freshness raporu - eski sayfalar
    OPTİMİZE EDİLDİ: Veritabanındaki sitemap_lastmod kullanılıyor (sitemap parse edilmiyor)
    """
    ensure_tables()
    
    site = db.query(Site).filter(Site.id == site_id, Site.is_competitor == False).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site bulunamadı")
    
    # Freshness ayarını al
    freshness_days = int(get_setting(db, "FRESHNESS_THRESHOLD_DAYS") or 45)
    today = datetime.utcnow()
    freshness_threshold = today - timedelta(days=freshness_days)
    
    # Tüm sayfaları al (veritabanından direkt - çok daha hızlı!)
    all_pages = db.query(Page).filter(Page.site_id == site_id).all()
    
    stale_pages = []
    fresh_count = 0
    
    # Veritabanındaki sitemap_lastmod'u kullan (sitemap parse etmiyoruz!)
    for page in all_pages:
        if page.sitemap_lastmod:
            days_since_lastmod = (today - page.sitemap_lastmod).days
            
            if days_since_lastmod > freshness_days:
                # 45 günden fazla geçmiş - eski içerik
                stale_pages.append({
                    "page": page,
                    "age_days": days_since_lastmod,
                    "effective_date": page.sitemap_lastmod,
                    "source": "db_sitemap_lastmod"
                })
            else:
                # 45 günden az - güncel içerik
                fresh_count += 1
        else:
            # Hiç lastmod bilgisi yok - eski say (güvenli tarafta ol)
            stale_pages.append({
                "page": page,
                "age_days": 999,
                "effective_date": None,
                "source": "unknown"
            })
    
    # Yaşa göre sırala (en eski önce)
    stale_pages.sort(key=lambda x: x["age_days"], reverse=True)
    
    return templates.TemplateResponse("freshness.html", {
        "request": request,
        "site": site,
        "stale_pages": stale_pages,
        "fresh_count": fresh_count,
        "stale_count": len(stale_pages),
        "freshness_days": freshness_days,
        "current_page": "site_tools"
    })


# ============================================
# INTERNAL LINKS RAPORU
# ============================================

@router.get("/links/{site_id}", response_class=HTMLResponse)
async def internal_links_report(
    request: Request, 
    site_id: int, 
    filter: str = Query("all"),
    limit: int = Query(100, ge=50, le=10000),
    db: Session = Depends(get_db)
):
    """Internal links raporu - Pagination ile"""
    ensure_tables()
    
    site = db.query(Site).filter(Site.id == site_id, Site.is_competitor == False).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site bulunamadı")
    
    # Sayfa ID'leri
    page_ids = [p.id for p in db.query(Page.id).filter(Page.site_id == site_id).all()]
    
    if not page_ids:
        return templates.TemplateResponse("links.html", {
            "request": request,
            "site": site,
            "links": [],
            "filter": filter,
            "limit": limit,
            "stats": {"total": 0, "broken": 0, "redirect": 0, "ok": 0},
            "current_page": "site_tools"
        })
    
    # Linkleri filtrele
    query = db.query(InternalLink).filter(InternalLink.source_page_id.in_(page_ids))
    
    if filter == "broken":
        query = query.filter(InternalLink.is_broken == True)
    elif filter == "redirect":
        query = query.filter(InternalLink.is_redirect == True)
    
    # Limit uygula ve sırala
    if filter == "redirect":
        # Redirect linkler için önce status_code'a göre, sonra checked_at'e göre sırala
        links = query.order_by(InternalLink.status_code, desc(InternalLink.checked_at)).limit(limit).all()
    else:
        links = query.order_by(desc(InternalLink.checked_at)).limit(limit).all()
    
    # Source page bilgilerini ekle
    links_with_source = []
    for link in links:
        source_page = db.query(Page).filter(Page.id == link.source_page_id).first()
        links_with_source.append({
            "link": link,
            "source_page": source_page
        })
    
    # İstatistikler
    total_links = db.query(func.count(InternalLink.id)).filter(
        InternalLink.source_page_id.in_(page_ids)
    ).scalar() or 0
    
    broken_count = db.query(func.count(InternalLink.id)).filter(
        InternalLink.source_page_id.in_(page_ids),
        InternalLink.is_broken == True
    ).scalar() or 0
    
    redirect_count = db.query(func.count(InternalLink.id)).filter(
        InternalLink.source_page_id.in_(page_ids),
        InternalLink.is_redirect == True
    ).scalar() or 0
    
    # WordPress bilgileri kontrolü (redirect düzeltme için)
    has_wp_config = bool(site.wp_ssh_host and site.wp_ssh_user and site.wp_path)
    
    return templates.TemplateResponse("links.html", {
        "request": request,
        "site": site,
        "links": links_with_source,
        "filter": filter,
        "limit": limit,
        "total_links": total_links,
        "has_wp_config": has_wp_config,
        "stats": {
            "total": total_links,
            "broken": broken_count,
            "redirect": redirect_count,
            "ok": total_links - broken_count - redirect_count
        },
        "current_page": "site_tools"
    })


# ============================================
# ANALİZ BAŞLATMA
# ============================================

@router.post("/analyze/{site_id}")
async def start_analysis(
    site_id: int, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Site analizi başlat (arka planda)"""
    ensure_tables()
    
    site = db.query(Site).filter(Site.id == site_id, Site.is_competitor == False).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site bulunamadı")
    
    # Arka planda çalıştır
    background_tasks.add_task(run_site_analysis, site_id, site.domain)
    
    return {"status": "started", "message": f"{site.name} analizi başlatıldı"}


@router.post("/analyze-page/{page_id}")
async def analyze_single_page_endpoint(
    page_id: int,
    db: Session = Depends(get_db)
):
    """
    Tek bir sayfayı anlık analiz et (cache olmadan, taze veri)
    """
    ensure_tables()
    
    page = db.query(Page).filter(Page.id == page_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="Sayfa bulunamadı")
    
    site = db.query(Site).filter(Site.id == page.site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site bulunamadı")
    
    if site.is_competitor:
        raise HTTPException(status_code=403, detail="Sadece kendi siteleriniz analiz edilebilir")
    
    try:
        # System status güncelle
        system_status.current_task = "Sayfa analizi"
        system_status.current_site = site.name
        system_status.current_url = page.url[:60] + "..." if len(page.url) > 60 else page.url
        
        # Analyzer'ı yeniden başlat (cache temizle)
        await site_analyzer.close()
        
        # Sayfayı analiz et (cache olmadan, taze veri)
        result = await site_analyzer.analyze_page_full(page.url, site.domain)
        
        if not result:
            return {
                "status": "error",
                "message": "Sayfa çekilemedi veya analiz edilemedi"
            }
        
        # Mevcut analizi bul veya oluştur
        analysis = db.query(PageAnalysis).filter(PageAnalysis.page_id == page.id).first()
        if not analysis:
            analysis = PageAnalysis(page_id=page.id)
            db.add(analysis)
        
        # H1 sonuçları
        analysis.h1_status = result["h1"].status
        analysis.h1_count = result["h1"].count
        analysis.h1_contents = result["h1"].contents
        
        # Schema sonuçları
        analysis.schema_status = result["schema"].status
        analysis.schema_types = result["schema"].types
        analysis.schema_errors = result["schema"].errors
        
        # Internal links - önce eskileri sil
        db.query(InternalLink).filter(InternalLink.source_page_id == page.id).delete()
        db.flush()
        
        # Yeni linkleri ekle ve kontrol et
        internal_links = result["internal_links"]
        
        if internal_links:
            # Linkleri kontrol et (max 50 link per sayfa)
            links_to_check = internal_links[:50]
            link_results = await site_analyzer.check_links_batch(links_to_check)
            
            ok_count = 0
            redirect_count = 0
            broken_count = 0
            
            for j, link_result in enumerate(link_results):
                internal_link = InternalLink(
                    source_page_id=page.id,
                    target_url=links_to_check[j]["url"],
                    anchor_text=links_to_check[j].get("anchor_text", "")[:500],
                    status_code=link_result.status_code,
                    final_url=link_result.final_url,
                    final_status_code=link_result.final_status_code,
                    redirect_chain=link_result.redirect_chain,
                    redirect_count=len(link_result.redirect_chain),
                    is_broken=link_result.is_broken,
                    is_redirect=link_result.is_redirect,
                    checked_at=datetime.utcnow()
                )
                db.add(internal_link)
                
                if link_result.is_broken:
                    broken_count += 1
                elif link_result.is_redirect:
                    redirect_count += 1
                else:
                    ok_count += 1
            
            analysis.internal_links_total = len(internal_links)
            analysis.internal_links_ok = ok_count
            analysis.internal_links_redirect = redirect_count
            analysis.internal_links_broken = broken_count
        else:
            analysis.internal_links_total = 0
            analysis.internal_links_ok = 0
            analysis.internal_links_redirect = 0
            analysis.internal_links_broken = 0
        
        analysis.analyzed_at = datetime.utcnow()
        db.commit()
        
        # System status güncelle
        system_status.current_task = "Boşta"
        system_status.current_site = ""
        system_status.current_url = ""
        system_status.last_completed_task = f"Sayfa analizi: {page.url[:50]}"
        system_status.last_completed_time = datetime.utcnow()
        
        return {
            "status": "success",
            "message": "Sayfa analizi tamamlandı",
            "analysis": {
                "h1_status": analysis.h1_status,
                "h1_count": analysis.h1_count,
                "h1_contents": analysis.h1_contents,
                "schema_status": analysis.schema_status,
                "schema_types": analysis.schema_types,
                "schema_errors": analysis.schema_errors,
                "internal_links_total": analysis.internal_links_total,
                "internal_links_ok": analysis.internal_links_ok,
                "internal_links_redirect": analysis.internal_links_redirect,
                "internal_links_broken": analysis.internal_links_broken,
                "analyzed_at": analysis.analyzed_at.isoformat() if analysis.analyzed_at else None
            }
        }
    
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        
        # System status güncelle
        system_status.current_task = "Boşta"
        system_status.current_site = ""
        system_status.current_url = ""
        
        return {
            "status": "error",
            "message": f"Analiz hatası: {str(e)}"
        }
    finally:
        await site_analyzer.close()


async def run_site_analysis(site_id: int, site_domain: str):
    """
    Site analizi arka plan görevi.
    
    ÖNEMLİ: Bu fonksiyon her sayfa için:
    1. HTTP ile HTML çeker (düz metin değil!)
    2. H1 analizi yapar
    3. Schema analizi yapar
    4. Internal linkleri çıkarır
    5. Linkleri kontrol eder (200/301/404)
    """
    from core.database import SessionLocal
    
    db = SessionLocal()
    try:
        pages = db.query(Page).filter(Page.site_id == site_id).all()
        total = len(pages)
        
        # System status güncelle
        system_status.current_task = "Site analizi"
        system_status.current_site = site_domain
        system_status.current_url = ""
        
        print(f"🔍 Site analizi başladı: {site_domain} ({total} sayfa)")
        
        for i, page in enumerate(pages):
            try:
                print(f"📄 [{i+1}/{total}] Analiz ediliyor: {page.url[:60]}...")
                
                # System status güncelle
                system_status.current_task = f"Site analizi ({i+1}/{total})"
                system_status.current_url = page.url[:60] + "..." if len(page.url) > 60 else page.url
                
                # HTTP ile HTML çek ve analiz et
                result = await site_analyzer.analyze_page_full(page.url, site_domain)
                
                if not result:
                    print(f"⚠️ Sayfa çekilemedi: {page.url[:50]}")
                    continue
                
                # Mevcut analizi bul veya oluştur
                analysis = db.query(PageAnalysis).filter(PageAnalysis.page_id == page.id).first()
                if not analysis:
                    analysis = PageAnalysis(page_id=page.id)
                    db.add(analysis)
                
                # H1 sonuçları
                analysis.h1_status = result["h1"].status
                analysis.h1_count = result["h1"].count
                analysis.h1_contents = result["h1"].contents
                
                print(f"   H1: {analysis.h1_status} ({analysis.h1_count} adet)")
                
                # Schema sonuçları
                analysis.schema_status = result["schema"].status
                analysis.schema_types = result["schema"].types
                analysis.schema_errors = result["schema"].errors
                
                print(f"   Schema: {analysis.schema_status} ({result['schema'].types})")
                
                # Internal links - önce eskileri sil
                db.query(InternalLink).filter(InternalLink.source_page_id == page.id).delete()
                db.flush()
                
                # Yeni linkleri ekle ve kontrol et
                internal_links = result["internal_links"]
                print(f"   Internal Links: {len(internal_links)} adet")
                
                if internal_links:
                    # Linkleri kontrol et (max 50 link per sayfa)
                    links_to_check = internal_links[:50]
                    link_results = await site_analyzer.check_links_batch(links_to_check)
                    
                    ok_count = 0
                    redirect_count = 0
                    broken_count = 0
                    
                    for j, link_result in enumerate(link_results):
                        internal_link = InternalLink(
                            source_page_id=page.id,
                            target_url=links_to_check[j]["url"],
                            anchor_text=links_to_check[j].get("anchor_text", "")[:500],
                            status_code=link_result.status_code,
                            final_url=link_result.final_url,
                            final_status_code=link_result.final_status_code,
                            redirect_chain=link_result.redirect_chain,
                            redirect_count=len(link_result.redirect_chain),
                            is_broken=link_result.is_broken,
                            is_redirect=link_result.is_redirect,
                            checked_at=datetime.utcnow()
                        )
                        db.add(internal_link)
                        
                        if link_result.is_broken:
                            broken_count += 1
                        elif link_result.is_redirect:
                            redirect_count += 1
                        else:
                            ok_count += 1
                    
                    analysis.internal_links_total = len(internal_links)
                    analysis.internal_links_ok = ok_count
                    analysis.internal_links_redirect = redirect_count
                    analysis.internal_links_broken = broken_count
                    
                    print(f"   Link Status: {ok_count} OK, {redirect_count} Redirect, {broken_count} Broken")
                else:
                    analysis.internal_links_total = 0
                    analysis.internal_links_ok = 0
                    analysis.internal_links_redirect = 0
                    analysis.internal_links_broken = 0
                
                analysis.analyzed_at = datetime.utcnow()
                db.commit()
                
                # Rate limiting
                await asyncio.sleep(1)
            
            except Exception as e:
                print(f"❌ Sayfa analiz hatası ({page.url[:40]}): {e}")
                db.rollback()
                continue
        
        print(f"✅ Site analizi tamamlandı: {site_domain}")
        
        # System status güncelle
        system_status.current_task = "Boşta"
        system_status.current_site = ""
        system_status.current_url = ""
        system_status.last_completed_task = f"Site analizi: {site_domain}"
        system_status.last_completed_time = datetime.utcnow()
    
    except Exception as e:
        print(f"❌ Site analizi genel hata: {e}")
        import traceback
        traceback.print_exc()
        
        # System status güncelle
        system_status.current_task = "Boşta"
        system_status.current_site = ""
        system_status.current_url = ""
    finally:
        await site_analyzer.close()
        db.close()


# ============================================
# TEK SAYFA ANALİZİ (Otomatik tetikleme için)
# ============================================

async def analyze_single_page(page_id: int, site_domain: str):
    """Tek bir sayfayı analiz et - yeni sayfa eklendiğinde çağrılır"""
    from core.database import SessionLocal
    
    db = SessionLocal()
    try:
        page = db.query(Page).filter(Page.id == page_id).first()
        if not page:
            return
        
        result = await site_analyzer.analyze_page_full(page.url, site_domain)
        
        if not result:
            return
        
        # Analiz kaydı oluştur
        analysis = PageAnalysis(
            page_id=page.id,
            h1_status=result["h1"].status,
            h1_count=result["h1"].count,
            h1_contents=result["h1"].contents,
            schema_status=result["schema"].status,
            schema_types=result["schema"].types,
            schema_errors=result["schema"].errors,
            internal_links_total=len(result["internal_links"]),
            analyzed_at=datetime.utcnow()
        )
        db.add(analysis)
        db.commit()
        
        print(f"✅ Otomatik analiz tamamlandı: {page.url[:50]}")
    
    except Exception as e:
        print(f"❌ Otomatik analiz hatası: {e}")
    finally:
        await site_analyzer.close()
        db.close()


# ============================================
# API ENDPOINTS
# ============================================

@router.get("/api/my-sites", tags=["API"])
async def get_my_sites(db: Session = Depends(get_db)):
    """Site Araçları için kullanılacak siteleri döndür (is_competitor=False)"""
    my_sites = db.query(Site).filter(Site.is_competitor == False).order_by(Site.name).all()
    return [
        {
            "id": site.id,
            "name": site.name,
            "domain": site.domain
        }
        for site in my_sites
    ]


@router.get("/api/status/{site_id}")
async def get_analysis_status(site_id: int, db: Session = Depends(get_db)):
    """Site analiz durumunu döndür"""
    ensure_tables()
    
    page_count = db.query(func.count(Page.id)).filter(Page.site_id == site_id).scalar() or 0
    
    page_ids = db.query(Page.id).filter(Page.site_id == site_id).subquery()
    analyzed_count = db.query(func.count(PageAnalysis.id)).filter(
        PageAnalysis.page_id.in_(page_ids)
    ).scalar() or 0
    
    return {
        "total_pages": page_count,
        "analyzed_pages": analyzed_count,
        "pending_pages": page_count - analyzed_count,
        "progress_percent": (analyzed_count / page_count * 100) if page_count > 0 else 0
    }


# ============================================
# WORDPRESS AYARLARI
# ============================================

@router.post("/site/{site_id}/wordpress-settings")
async def save_wordpress_settings(
    site_id: int,
    wp_ssh_host: str = Body(None),
    wp_ssh_user: str = Body(None),
    wp_ssh_port: int = Body(22),
    wp_path: str = Body(None),
    wp_cli_path: str = Body("wp"),
    db: Session = Depends(get_db)
):
    """
    WordPress ayarlarını kaydet
    """
    ensure_tables()
    
    site = db.query(Site).filter(Site.id == site_id, Site.is_competitor == False).first()
    if not site:
        return JSONResponse({
            "success": False,
            "message": "Site bulunamadı"
        }, status_code=404)
    
    # Ayarları güncelle
    if wp_ssh_host:
        site.wp_ssh_host = wp_ssh_host
    if wp_ssh_user:
        site.wp_ssh_user = wp_ssh_user
    site.wp_ssh_port = wp_ssh_port
    if wp_path:
        site.wp_path = wp_path
    site.wp_cli_path = wp_cli_path or "wp"
    
    try:
        db.commit()
        return JSONResponse({
            "success": True,
            "message": "WordPress ayarları kaydedildi"
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({
            "success": False,
            "message": f"Hata: {str(e)}"
        }, status_code=500)


@router.post("/site/{site_id}/wordpress-api-settings")
async def save_wordpress_api_settings(
    site_id: int,
    wp_api_url: str = Body(None),
    wp_api_username: str = Body(None),
    wp_api_password: str = Body(None),
    db: Session = Depends(get_db)
):
    """
    WordPress REST API ayarlarını kaydet
    """
    ensure_tables()
    
    site = db.query(Site).filter(Site.id == site_id, Site.is_competitor == False).first()
    if not site:
        return JSONResponse({
            "success": False,
            "message": "Site bulunamadı"
        }, status_code=404)
    
    # Ayarları güncelle
    if wp_api_url:
        site.wp_api_url = wp_api_url
    if wp_api_username:
        site.wp_api_username = wp_api_username
    if wp_api_password:
        site.wp_api_password = wp_api_password
    
    try:
        db.commit()
        return JSONResponse({
            "success": True,
            "message": "WordPress REST API ayarları kaydedildi"
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({
            "success": False,
            "message": f"Hata: {str(e)}"
        }, status_code=500)


@router.post("/site/{site_id}/test-wordpress-api")
async def test_wordpress_api_connection(
    site_id: int,
    wp_api_url: str = Body(None),
    wp_api_username: str = Body(None),
    wp_api_password: str = Body(None),
    db: Session = Depends(get_db)
):
    """
    WordPress REST API bağlantısını test et
    """
    ensure_tables()
    
    site = db.query(Site).filter(Site.id == site_id, Site.is_competitor == False).first()
    if not site:
        return JSONResponse({
            "success": False,
            "message": "Site bulunamadı"
        }, status_code=404)
    
    # Eğer parametreler gönderilmemişse, site ayarlarından al
    if not wp_api_url:
        wp_api_url = site.wp_api_url
    if not wp_api_username:
        wp_api_username = site.wp_api_username
    if not wp_api_password:
        wp_api_password = site.wp_api_password
    
    if not wp_api_url or not wp_api_username or not wp_api_password:
        return JSONResponse({
            "success": False,
            "message": "WordPress URL, Kullanıcı Adı ve Application Password gerekli"
        }, status_code=400)
    
    try:
        from .wordpress_api_fix import WordPressAPILinkFixer
        
        fixer = WordPressAPILinkFixer(
            wp_url=wp_api_url,
            wp_username=wp_api_username,
            wp_password=wp_api_password
        )
        
        # WordPress versiyonunu kontrol et
        success, data, error = await fixer._make_request("GET", "")
        
        if success:
            wp_version = data.get('version', 'Bilinmiyor') if isinstance(data, dict) else 'Bilinmiyor'
            return JSONResponse({
                "success": True,
                "message": "Bağlantı başarılı",
                "wp_version": wp_version
            })
        else:
            return JSONResponse({
                "success": False,
                "message": f"REST API hatası: {error}"
            })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "message": f"Hata: {str(e)}"
        }, status_code=500)


@router.post("/site/{site_id}/test-wordpress")
async def test_wordpress_connection(
    site_id: int,
    wp_ssh_host: str = Body(None),
    wp_ssh_user: str = Body(None),
    wp_ssh_port: int = Body(22),
    wp_path: str = Body(None),
    wp_cli_path: str = Body("wp"),
    db: Session = Depends(get_db)
):
    """
    WordPress bağlantısını test et
    """
    ensure_tables()
    
    site = db.query(Site).filter(Site.id == site_id, Site.is_competitor == False).first()
    if not site:
        return JSONResponse({
            "success": False,
            "message": "Site bulunamadı"
        }, status_code=404)
    
    # Eğer parametreler gönderilmemişse, site ayarlarından al
    if not wp_ssh_host:
        wp_ssh_host = site.wp_ssh_host
    if not wp_ssh_user:
        wp_ssh_user = site.wp_ssh_user
    if not wp_path:
        wp_path = site.wp_path
    
    if not wp_ssh_host or not wp_ssh_user or not wp_path:
        return JSONResponse({
            "success": False,
            "message": "SSH Host, SSH User ve WordPress Path gerekli"
        }, status_code=400)
    
    try:
        from .wordpress_fix import WordPressLinkFixer
        
        fixer = WordPressLinkFixer(
            ssh_host=wp_ssh_host,
            ssh_user=wp_ssh_user,
            ssh_port=wp_ssh_port or 22,
            wp_path=wp_path,
            wp_cli_path=wp_cli_path or "wp"
        )
        
        # WP CLI versiyonunu kontrol et
        success, stdout, stderr = fixer._run_wp_cli("--version")
        
        if success:
            wp_version = stdout.strip() if stdout else "Bilinmiyor"
            return JSONResponse({
                "success": True,
                "message": "Bağlantı başarılı",
                "wp_version": wp_version
            })
        else:
            return JSONResponse({
                "success": False,
                "message": f"WP CLI hatası: {stderr or 'Bilinmeyen hata'}"
            })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "message": f"Hata: {str(e)}"
        }, status_code=500)


# ============================================
# WORDPRESS REDIRECT DÜZELTME
# ============================================

@router.post("/fix-redirect")
async def fix_redirect_link(
    link_id: int = Body(...),
    old_url: str = Body(...),
    new_url: str = Body(...),
    page_id: int = Body(...),
    dry_run: bool = Body(False),
    db: Session = Depends(get_db)
):
    """
    WordPress CLI ile redirect linki düzelt
    
    Args:
        link_id: InternalLink ID
        old_url: Eski URL (redirect olan)
        new_url: Yeni URL (final URL)
        page_id: Source page ID
        dry_run: Sadece test et, değişiklik yapma
    """
    ensure_tables()
    
    # Page ve Site bilgilerini al
    page = db.query(Page).filter(Page.id == page_id).first()
    if not page:
        return JSONResponse({
            "success": False,
            "message": "Sayfa bulunamadı"
        }, status_code=404)
    
    site = db.query(Site).filter(Site.id == page.site_id).first()
    if not site:
        return JSONResponse({
            "success": False,
            "message": "Site bulunamadı"
        }, status_code=404)
    
    # WordPress bilgileri kontrolü (SSH veya REST API)
    has_ssh = site.wp_ssh_host and site.wp_ssh_user and site.wp_path
    has_api = site.wp_api_url and site.wp_api_username and site.wp_api_password
    
    if not has_ssh and not has_api:
        return JSONResponse({
            "success": False,
            "message": "WordPress bilgileri eksik. Lütfen site ayarlarından WordPress SSH veya REST API bilgilerini girin."
        }, status_code=400)
    
    try:
        # SSH varsa SSH ile, yoksa REST API ile
        if has_ssh:
            from .wordpress_fix import WordPressLinkFixer
            
            fixer = WordPressLinkFixer(
                ssh_host=site.wp_ssh_host,
                ssh_user=site.wp_ssh_user,
                ssh_port=site.wp_ssh_port or 22,
                wp_path=site.wp_path,
                wp_cli_path=site.wp_cli_path or "wp"
            )
            
            # Log listesi oluştur
            logs = []
            logs.append({"message": f"SSH bağlantısı kuruldu", "type": "success"})
            logs.append({"message": f"Sayfa URL'den post ID bulunuyor: {page.url}", "type": "info"})
            
            # URL'den post ID bul
            post_id = fixer.get_post_id_by_url(page.url)
            if not post_id:
                logs.append({"message": f"❌ WordPress'te sayfa bulunamadı: {page.url}", "type": "error"})
                return JSONResponse({
                    "success": False,
                    "message": f"WordPress'te sayfa bulunamadı: {page.url}",
                    "logs": logs
                }, status_code=404)
            
            logs.append({"message": f"✅ Post ID bulundu: {post_id}", "type": "success"})
            
            # Linki düzelt
            result = fixer.fix_link_in_elementor(
                post_id=post_id,
                old_url=old_url,
                new_url=new_url,
                dry_run=dry_run,
                logs=logs
            )
            
            result["logs"] = logs
        else:
            # REST API ile
            from .wordpress_api_fix import WordPressAPILinkFixer
            
            fixer = WordPressAPILinkFixer(
                wp_url=site.wp_api_url,
                wp_username=site.wp_api_username,
                wp_password=site.wp_api_password
            )
            
            # Log listesi oluştur
            logs = []
            logs.append({"message": f"WordPress REST API bağlantısı kuruldu", "type": "success"})
            logs.append({"message": f"Sayfa URL'den post ID bulunuyor: {page.url}", "type": "info"})
            
            # URL'den post ID bul (log listesi ile)
            post_result = await fixer.get_post_by_url(page.url, logs=logs)
            if not post_result:
                logs.append({"message": f"❌ WordPress'te sayfa bulunamadı: {page.url}", "type": "error"})
                return JSONResponse({
                    "success": False,
                    "message": f"WordPress'te sayfa bulunamadı: {page.url}",
                    "logs": logs
                }, status_code=404)
            
            post_id, post_type = post_result
            logs.append({"message": f"✅ Post ID bulundu: {post_id} (type: {post_type})", "type": "success"})
            
            # Linki düzelt
            result = await fixer.fix_link_in_elementor(
                post_id=post_id,
                old_url=old_url,
                new_url=new_url,
                dry_run=dry_run,
                logs=logs,
                post_type=post_type
            )
            
            result["logs"] = logs
        
        return JSONResponse(result)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "message": f"Hata: {str(e)}"
        }, status_code=500)
