# ============================================
# Kuyruk Yönetimi - Arka Plan Görev Takibi
# ============================================

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Dict

from core.database import get_db, ScanJob, ScanStatus, Site
from core.scheduler import background_scanner
from config import settings

router = APIRouter(prefix="/queue", tags=["Kuyruk"])

# Templates
from pathlib import Path
TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


@router.get("", response_class=HTMLResponse)
async def queue_page(request: Request, db: Session = Depends(get_db)):
    """Kuyruk sayfası - Tüm arka plan görevlerini göster"""
    try:
        # APScheduler görevlerini al
        scheduler_jobs = []
        if background_scanner.scheduler.running:
            for job in background_scanner.scheduler.get_jobs():
                scheduler_jobs.append({
                    "id": job.id,
                    "name": job.name or job.id,
                    "type": "scheduled",
                    "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                    "trigger": str(job.trigger) if hasattr(job, 'trigger') else None
                })
        
        # Çalışan tarama görevlerini al
        running_scans = []
        running_jobs = background_scanner.get_running_jobs()
        for site_id, job_id in running_jobs.items():
            scan_job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
            site = db.query(Site).filter(Site.id == site_id).first()
            if scan_job and site:
                running_scans.append({
                    "id": f"scan_{job_id}",
                    "job_id": job_id,
                    "site_id": site_id,
                    "name": f"Site Taraması: {site.name}",
                    "type": "scan",
                    "status": scan_job.status.value,
                    "progress": scan_job.progress_percent,
                    "scanned_pages": scan_job.scanned_pages,
                    "total_pages": scan_job.total_pages,
                    "started_at": scan_job.started_at.isoformat() if scan_job.started_at else None
                })
        
        # Bekleyen tarama görevlerini al
        pending_scans = []
        pending_jobs = db.query(ScanJob).filter(ScanJob.status == ScanStatus.PENDING).order_by(ScanJob.created_at.desc()).limit(10).all()
        for scan_job in pending_jobs:
            site = db.query(Site).filter(Site.id == scan_job.site_id).first()
            if site:
                pending_scans.append({
                    "id": f"scan_{scan_job.id}",
                    "job_id": scan_job.id,
                    "site_id": scan_job.site_id,
                    "name": f"Site Taraması: {site.name}",
                    "type": "scan",
                    "status": scan_job.status.value,
                    "created_at": scan_job.created_at.isoformat() if scan_job.created_at else None
                })
        
        return templates.TemplateResponse(
            "queue.html",
            {
                "request": request,
                "current_page": "queue",
                "scheduler_jobs": scheduler_jobs,
                "running_scans": running_scans,
                "pending_scans": pending_scans
            }
        )
    except Exception as e:
        return templates.TemplateResponse(
            "base.html",
            {
                "request": request,
                "current_page": None,
                "error": f"Kuyruk sayfası yüklenirken hata oluştu: {str(e)}"
            },
            status_code=500
        )


@router.get("/api/tasks", response_class=JSONResponse)
async def get_tasks(db: Session = Depends(get_db)):
    """Tüm görevleri JSON olarak döndür"""
    try:
        # APScheduler görevlerini al
        scheduler_jobs = []
        if background_scanner.scheduler.running:
            for job in background_scanner.scheduler.get_jobs():
                scheduler_jobs.append({
                    "id": job.id,
                    "name": job.name or job.id,
                    "type": "scheduled",
                    "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                    "trigger": str(job.trigger) if hasattr(job, 'trigger') else None
                })
        
        # Çalışan tarama görevlerini al
        running_scans = []
        running_jobs = background_scanner.get_running_jobs()
        for site_id, job_id in running_jobs.items():
            scan_job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
            site = db.query(Site).filter(Site.id == site_id).first()
            if scan_job and site:
                running_scans.append({
                    "id": f"scan_{job_id}",
                    "job_id": job_id,
                    "site_id": site_id,
                    "name": f"Site Taraması: {site.name}",
                    "type": "scan",
                    "status": scan_job.status.value,
                    "progress": scan_job.progress_percent,
                    "scanned_pages": scan_job.scanned_pages,
                    "total_pages": scan_job.total_pages,
                    "started_at": scan_job.started_at.isoformat() if scan_job.started_at else None
                })
        
        # Bekleyen tarama görevlerini al
        pending_scans = []
        pending_jobs = db.query(ScanJob).filter(ScanJob.status == ScanStatus.PENDING).order_by(ScanJob.created_at.desc()).limit(10).all()
        for scan_job in pending_jobs:
            site = db.query(Site).filter(Site.id == scan_job.site_id).first()
            if site:
                pending_scans.append({
                    "id": f"scan_{scan_job.id}",
                    "job_id": scan_job.id,
                    "site_id": scan_job.site_id,
                    "name": f"Site Taraması: {site.name}",
                    "type": "scan",
                    "status": scan_job.status.value,
                    "created_at": scan_job.created_at.isoformat() if scan_job.created_at else None
                })
        
        return JSONResponse({
            "status": "success",
            "scheduler_jobs": scheduler_jobs,
            "running_scans": running_scans,
            "pending_scans": pending_scans
        })
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": str(e)
        }, status_code=500)


@router.post("/task/{task_id}/cancel", response_class=JSONResponse)
async def cancel_task(task_id: str, db: Session = Depends(get_db)):
    """Görevi sonlandır"""
    try:
        # Tarama görevi mi?
        if task_id.startswith("scan_"):
            job_id = int(task_id.replace("scan_", ""))
            scan_job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
            
            if scan_job:
                # Çalışan tarama ise durdur
                if scan_job.site_id in background_scanner.get_running_jobs():
                    success = background_scanner.stop_scan(scan_job.site_id)
                    if success:
                        scan_job.status = ScanStatus.CANCELLED
                        scan_job.finished_at = datetime.utcnow()
                        db.commit()
                        return JSONResponse({
                            "status": "success",
                            "message": "Tarama görevi sonlandırıldı"
                        })
                
                # Bekleyen tarama ise iptal et
                if scan_job.status == ScanStatus.PENDING:
                    scan_job.status = ScanStatus.CANCELLED
                    scan_job.finished_at = datetime.utcnow()
                    db.commit()
                    return JSONResponse({
                        "status": "success",
                        "message": "Bekleyen tarama görevi iptal edildi"
                    })
            
            return JSONResponse({
                "status": "error",
                "message": "Görev bulunamadı"
            }, status_code=404)
        
        # Scheduled görev mi?
        elif background_scanner.scheduler.running:
            try:
                background_scanner.scheduler.remove_job(task_id)
                return JSONResponse({
                    "status": "success",
                    "message": "Periyodik görev kaldırıldı"
                })
            except Exception as e:
                return JSONResponse({
                    "status": "error",
                    "message": f"Görev kaldırılamadı: {str(e)}"
                }, status_code=400)
        
        return JSONResponse({
            "status": "error",
            "message": "Geçersiz görev ID'si"
        }, status_code=400)
        
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)






