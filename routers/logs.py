# ============================================
# Rakip İçerik İstihbarat Sistemi V2
# Logs Router - Değişiklik Logları
# ============================================

from fastapi import APIRouter, Request, Depends, Query, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional
from datetime import datetime, timedelta

from config import settings
from core.database import get_db, Site, Page, Log, ActionType

router = APIRouter(prefix="/logs", tags=["Logs"])
templates = Jinja2Templates(directory=str(settings.TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def list_logs(
    request: Request,
    db: Session = Depends(get_db),
    site_id: Optional[int] = Query(None),
    action_type: Optional[str] = Query(None),
    days: int = Query(7, ge=1, le=90),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=100)
):
    """Log listesi sayfası"""
    
    # Filtre tarihi
    since = datetime.utcnow() - timedelta(days=days)
    
    # Query oluştur
    query = db.query(Log).filter(Log.created_at >= since)
    
    # Site filtresi
    if site_id:
        page_ids = db.query(Page.id).filter(Page.site_id == site_id).subquery()
        query = query.filter(Log.page_id.in_(page_ids))
    
    # Action type filtresi
    if action_type:
        try:
            action_enum = ActionType[action_type.upper()]
            query = query.filter(Log.action_type == action_enum)
        except KeyError:
            pass
    
    # Toplam sayı
    total = query.count()
    
    # Sayfalama
    offset = (page - 1) * per_page
    logs = query.order_by(desc(Log.created_at)).offset(offset).limit(per_page).all()
    
    # Log'lara site ve sayfa bilgilerini ekle
    logs_with_details = []
    for log in logs:
        log_page = db.query(Page).filter(Page.id == log.page_id).first()
        if log_page:
            site = db.query(Site).filter(Site.id == log_page.site_id).first()
            logs_with_details.append({
                "log": log,
                "page": log_page,
                "site": site
            })
    
    # Siteler (filtre için)
    sites = db.query(Site).order_by(Site.name).all()
    
    # Sayfalama bilgisi
    total_pages = (total + per_page - 1) // per_page
    
    return templates.TemplateResponse("logs.html", {
        "request": request,
        "logs": logs_with_details,
        "sites": sites,
        "current_site_id": site_id,
        "current_action_type": action_type,
        "current_days": days,
        "current_page_num": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "current_page": "logs"
    })


@router.get("/{log_id}", response_class=HTMLResponse)
async def log_detail(request: Request, log_id: int, db: Session = Depends(get_db)):
    """Log detay sayfası (diff görüntüleme)"""
    
    log = db.query(Log).filter(Log.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Log bulunamadı")
    
    page = db.query(Page).filter(Page.id == log.page_id).first()
    site = db.query(Site).filter(Site.id == page.site_id).first() if page else None
    
    return templates.TemplateResponse("log_detail.html", {
        "request": request,
        "log": log,
        "page": page,
        "site": site,
        "current_page": "logs"
    })


@router.get("/api/{log_id}/diff")
async def get_log_diff(log_id: int, db: Session = Depends(get_db)):
    """Log diff bilgisini JSON olarak döndür"""
    
    log = db.query(Log).filter(Log.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Log bulunamadı")
    
    page = db.query(Page).filter(Page.id == log.page_id).first()
    site = db.query(Site).filter(Site.id == page.site_id).first() if page else None
    
    return {
        "id": log.id,
        "action_type": log.action_type.value,
        "diff_html": log.diff_html,
        "old_content_preview": log.old_content_preview,
        "new_content_preview": log.new_content_preview,
        "change_percentage": log.change_percentage,
        "words_added": log.words_added,
        "words_removed": log.words_removed,
        "created_at": log.created_at.isoformat(),
        "page_url": page.url if page else "",
        "page_title": page.title if page else "",
        "site_name": site.name if site else "",
        "site_domain": site.domain if site else ""
    }
