# ============================================
# Rakip İçerik İstihbarat Sistemi V2
# Sites Router - Site Yönetimi
# ============================================

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from datetime import datetime
from typing import Optional
import asyncio

from config import settings
from core.database import get_db, Site, Page, Log, ScanJob, ScanStatus
from core.scheduler import background_scanner

router = APIRouter(prefix="/sites", tags=["Sites"])
templates = Jinja2Templates(directory=str(settings.TEMPLATES_DIR))


# ============================================
# WORDPRESS TEST ENDPOINT (ÖNCE TANIMLANMALI - Route sıralaması için)
# ============================================

@router.post("/wordpress/test-connection")
async def test_wordpress_connection(
    request: Request
):
    """WordPress REST API bağlantısını test et"""
    from fastapi.responses import JSONResponse
    import httpx
    
    try:
        body = await request.json()
        wp_url = body.get('wp_url')
        wp_username = body.get('wp_username')
        wp_password = body.get('wp_password')
        
        if not wp_url or not wp_username or not wp_password:
            return JSONResponse({
                "success": False,
                "message": "Eksik parametreler: wp_url, wp_username, wp_password gerekli"
            }, status_code=400)
        
        test_url = f"{wp_url.rstrip('/')}/wp-json/wp/v2"
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                test_url,
                auth=(wp_username, wp_password)
            )
            if response.status_code == 200:
                return JSONResponse({
                    "success": True,
                    "message": "✅ WordPress REST API bağlantısı başarılı!"
                })
            else:
                error_text = response.text[:200] if response.text else ""
                return JSONResponse({
                    "success": False,
                    "message": f"❌ Bağlantı hatası: HTTP {response.status_code} - {error_text}"
                }, status_code=400)
    except Exception as e:
        return JSONResponse({
            "success": False,
            "message": f"❌ Bağlantı hatası: {str(e)}"
        }, status_code=500)


# ============================================
# SITE LIST & ADD
# ============================================

@router.get("/", response_class=HTMLResponse)
async def list_sites(request: Request, db: Session = Depends(get_db)):
    """Site listesi sayfası"""
    
    sites = db.query(Site).order_by(desc(Site.created_at)).all()
    
    # Her site için ek bilgiler
    sites_with_stats = []
    for site in sites:
        page_count = db.query(func.count(Page.id)).filter(Page.site_id == site.id).scalar() or 0
        
        # Son tarama durumu
        last_scan = db.query(ScanJob).filter(
            ScanJob.site_id == site.id
        ).order_by(desc(ScanJob.created_at)).first()
        
        # Aktif tarama var mı?
        is_scanning = background_scanner.is_scanning(site.id)
        
        sites_with_stats.append({
            "site": site,
            "page_count": page_count,
            "last_scan": last_scan,
            "is_scanning": is_scanning
        })
    
    return templates.TemplateResponse("sites.html", {
        "request": request,
        "sites": sites_with_stats,
        "current_page": "sites"
    })


@router.get("/add", response_class=HTMLResponse)
async def add_site_form(request: Request):
    """Yeni site ekleme formu"""
    return templates.TemplateResponse("site_form.html", {
        "request": request,
        "site": None,
        "current_page": "sites"
    })


@router.post("/add")
async def add_site(
    request: Request,
    name: str = Form(...),
    domain: str = Form(...),
    sitemap_url: Optional[str] = Form(None),
    is_competitor: bool = Form(True),
    db: Session = Depends(get_db)
):
    """Yeni site ekle"""
    
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
        return templates.TemplateResponse("site_form.html", {
            "request": request,
            "site": None,
            "error": "Bu domain zaten ekli!",
            "current_page": "sites"
        })
    
    # Yeni site oluştur
    site = Site(
        name=name,
        domain=domain,
        sitemap_url=sitemap_url if sitemap_url else None,
        is_competitor=is_competitor,
        is_active=True
    )
    
    db.add(site)
    db.commit()
    
    return RedirectResponse(url="/sites", status_code=303)


@router.get("/{site_id}", response_class=HTMLResponse)
async def site_detail(request: Request, site_id: int, db: Session = Depends(get_db)):
    """Site detay sayfası"""
    
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site bulunamadı")
    
    # Sayfalar
    pages = db.query(Page).filter(Page.site_id == site_id).order_by(desc(Page.last_checked_at)).all()
    
    # Son loglar
    page_ids = [p.id for p in pages]
    logs = []
    if page_ids:
        logs = db.query(Log).filter(Log.page_id.in_(page_ids)).order_by(desc(Log.created_at)).limit(50).all()
    
    # Tarama geçmişi
    scan_history = db.query(ScanJob).filter(
        ScanJob.site_id == site_id
    ).order_by(desc(ScanJob.created_at)).limit(10).all()
    
    # Aktif tarama
    is_scanning = background_scanner.is_scanning(site_id)
    
    return templates.TemplateResponse("site_detail.html", {
        "request": request,
        "site": site,
        "pages": pages,
        "logs": logs,
        "scan_history": scan_history,
        "is_scanning": is_scanning,
        "current_page": "sites"
    })


@router.post("/{site_id}/scan")
async def start_scan(site_id: int, db: Session = Depends(get_db)):
    """Site taramasını başlat"""
    
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site bulunamadı")
    
    # Tarama başlat
    job_id = await background_scanner.start_scan(site_id)
    
    if job_id:
        return {"status": "started", "job_id": job_id}
    else:
        return {"status": "already_running"}


@router.post("/{site_id}/stop-scan")
async def stop_scan(site_id: int):
    """Site taramasını durdur"""
    
    stopped = background_scanner.stop_scan(site_id)
    
    if stopped:
        return {"status": "stopping"}
    else:
        return {"status": "not_running"}


@router.post("/{site_id}/toggle")
async def toggle_site(site_id: int, db: Session = Depends(get_db)):
    """Site aktif/pasif durumunu değiştir"""
    
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site bulunamadı")
    
    site.is_active = not site.is_active
    db.commit()
    
    return {"status": "success", "is_active": site.is_active}


@router.delete("/{site_id}")
async def delete_site(site_id: int, db: Session = Depends(get_db)):
    """Siteyi sil"""
    
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site bulunamadı")
    
    # Tarama durdur
    background_scanner.stop_scan(site_id)
    
    # Sil (cascade ile pages, logs, scan_jobs da silinir)
    db.delete(site)
    db.commit()
    
    return {"status": "deleted"}


@router.get("/{site_id}/edit", response_class=HTMLResponse)
async def edit_site_form(request: Request, site_id: int, db: Session = Depends(get_db)):
    """Site düzenleme formu"""
    
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site bulunamadı")
    
    return templates.TemplateResponse("site_form.html", {
        "request": request,
        "site": site,
        "current_page": "sites"
    })


@router.post("/{site_id}/edit")
async def edit_site(
    request: Request,
    site_id: int,
    name: str = Form(...),
    domain: str = Form(...),
    sitemap_url: Optional[str] = Form(None),
    is_competitor: bool = Form(True),
    db: Session = Depends(get_db)
):
    """Siteyi güncelle"""
    
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site bulunamadı")
    
    site.name = name
    site.domain = domain.lower().strip()
    site.sitemap_url = sitemap_url if sitemap_url else None
    site.is_competitor = is_competitor
    site.updated_at = datetime.utcnow()
    
    db.commit()
    
    return RedirectResponse(url=f"/sites/{site_id}", status_code=303)


@router.post("/{site_id}/wordpress-connection")
async def save_wordpress_connection(
    request: Request,
    site_id: int,
    wp_api_url: Optional[str] = Form(None),
    wp_api_username: Optional[str] = Form(None),
    wp_api_password: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """WordPress REST API bağlantı bilgilerini kaydet"""
    
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site bulunamadı")
    
    # URL temizliği
    if wp_api_url:
        wp_api_url = wp_api_url.strip().rstrip('/')
        if not wp_api_url.startswith('http://') and not wp_api_url.startswith('https://'):
            wp_api_url = 'https://' + wp_api_url
    
    # Bilgileri kaydet
    site.wp_api_url = wp_api_url if wp_api_url else None
    site.wp_api_username = wp_api_username.strip() if wp_api_username else None
    # Şifre değişmediyse eski değeri koru (boş string gelirse değiştirme)
    if wp_api_password and wp_api_password.strip() and wp_api_password != "••••••••":
        site.wp_api_password = wp_api_password.strip()
    site.updated_at = datetime.utcnow()
    
    db.commit()
    
    # Bağlantı testi yap (opsiyonel)
    test_result = None
    test_password = wp_api_password if wp_api_password and wp_api_password != "••••••••" else site.wp_api_password
    if wp_api_url and wp_api_username and test_password:
        try:
            import httpx
            test_url = f"{wp_api_url}/wp-json/wp/v2"
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    test_url,
                    auth=(wp_api_username, test_password)
                )
                if response.status_code == 200:
                    test_result = {"success": True, "message": "✅ WordPress REST API bağlantısı başarılı!"}
                else:
                    error_text = response.text[:200] if response.text else ""
                    test_result = {"success": False, "message": f"❌ Bağlantı hatası: HTTP {response.status_code} - {error_text}"}
        except Exception as e:
            test_result = {"success": False, "message": f"❌ Bağlantı hatası: {str(e)}"}
    
    return RedirectResponse(
        url=f"/sites/{site_id}?wp_test={'success' if test_result and test_result['success'] else 'error' if test_result else 'saved'}&activeTab=wordpress",
        status_code=303
    )


