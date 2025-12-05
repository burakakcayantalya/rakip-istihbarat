# ============================================
# Rakip İçerik İstihbarat Sistemi V2
# Dashboard Router
# ============================================

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from datetime import datetime, timedelta

from config import settings
from core.database import get_db, Site, Page, Log, ScanJob, ActionType, ScanStatus
from core.scoring import scoring_engine
from core.scheduler import background_scanner, system_status

router = APIRouter(tags=["Dashboard"])
templates = Jinja2Templates(directory=str(settings.TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """Ana dashboard sayfası"""
    
    try:
        # İstatistikleri al
        stats = scoring_engine.get_activity_summary(db, days=7)
        
        # Site sayıları
        total_sites = db.query(func.count(Site.id)).scalar() or 0
        competitor_sites = db.query(func.count(Site.id)).filter(Site.is_competitor == True).scalar() or 0
        our_sites = total_sites - competitor_sites
        
        # Son loglar (son 20)
        recent_logs = db.query(Log).order_by(desc(Log.created_at)).limit(20).all()
        
        # Log'lara site ve sayfa bilgilerini ekle
        logs_with_details = []
        for log in recent_logs:
            page = db.query(Page).filter(Page.id == log.page_id).first()
            if page:
                site = db.query(Site).filter(Site.id == page.site_id).first()
                logs_with_details.append({
                    "log": log,
                    "page": page,
                    "site": site
                })
        
        # Aktif taramalar
        active_scans = db.query(ScanJob).filter(
            ScanJob.status.in_([ScanStatus.PENDING, ScanStatus.RUNNING])
        ).all()
        
        # Site sıralaması
        rankings = scoring_engine.get_all_sites_ranking(db, days=7)
        
        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "stats": stats,
            "total_sites": total_sites,
            "competitor_sites": competitor_sites,
            "our_sites": our_sites,
            "recent_logs": logs_with_details,
            "active_scans": active_scans,
            "rankings": rankings[:10] if rankings else [],  # Top 10
            "current_page": "dashboard"
        })
    except Exception as e:
        import traceback
        error_msg = str(e)
        traceback.print_exc()
        # Hata durumunda boş dashboard göster
        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "stats": {
                "period_days": 7,
                "new_content_count": 0,
                "update_count": 0,
                "total_activity": 0,
                "active_sites": 0,
                "total_pages_tracked": 0,
                "most_active_competitor": None
            },
            "total_sites": 0,
            "competitor_sites": 0,
            "our_sites": 0,
            "recent_logs": [],
            "active_scans": [],
            "rankings": [],
            "current_page": "dashboard",
            "error": error_msg
        })


@router.get("/api/stats", tags=["API"])
async def get_stats(db: Session = Depends(get_db), days: int = 7):
    """Dashboard istatistiklerini JSON olarak döndür"""
    stats = scoring_engine.get_activity_summary(db, days=days)
    return stats


@router.get("/api/recent-activity", tags=["API"])
async def get_recent_activity(db: Session = Depends(get_db), limit: int = 20):
    """Son aktiviteleri JSON olarak döndür"""
    
    logs = db.query(Log).order_by(desc(Log.created_at)).limit(limit).all()
    
    result = []
    for log in logs:
        page = db.query(Page).filter(Page.id == log.page_id).first()
        if page:
            site = db.query(Site).filter(Site.id == page.site_id).first()
            result.append({
                "id": log.id,
                "action_type": log.action_type.value,
                "change_percentage": log.change_percentage,
                "created_at": log.created_at.isoformat(),
                "page_url": page.url,
                "page_title": page.title,
                "site_name": site.name if site else "Bilinmeyen",
                "site_domain": site.domain if site else ""
            })
    
    return result


@router.get("/api/rankings", tags=["API"])
async def get_rankings(db: Session = Depends(get_db), days: int = 7):
    """Site sıralamalarını JSON olarak döndür"""
    rankings = scoring_engine.get_all_sites_ranking(db, days=days)
    return rankings


@router.get("/api/system-status", tags=["API"])
async def get_system_status():
    """Sistem durumunu JSON olarak döndür - Header'da göstermek için"""
    status = background_scanner.get_status()
    return {
        "current_task": status.current_task,
        "current_site": status.current_site,
        "current_url": status.current_url,
        "queue_size": status.queue_size,
        "last_completed_task": status.last_completed_task,
        "last_completed_time": status.last_completed_time.isoformat() if status.last_completed_time else None,
        "running_jobs_count": len(background_scanner.get_running_jobs())
    }
