# ============================================
# Reviewer Agent - Router & Endpoints
# ============================================

from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc, and_
from datetime import datetime
from typing import Optional
from pathlib import Path

from core.database import get_db, Site
from agents.observer.models import ObserverReport, ReportSeverity
from .models import (
    ReviewerQueue, QueueStatus, PriorityScore,
    get_priority_score, get_action_plan,
    init_reviewer_tables
)

# Template dizinleri
REVIEWER_TEMPLATE_DIR = Path(__file__).parent / "templates"
MAIN_TEMPLATE_DIR = Path(__file__).parent.parent.parent / "templates"

templates = Jinja2Templates(directory=[str(REVIEWER_TEMPLATE_DIR), str(MAIN_TEMPLATE_DIR)])

router = APIRouter(prefix="/agents/reviewer", tags=["Reviewer Agent"])

# Tablo oluşturma (ilk çalıştırmada)
_tables_initialized = False


def ensure_tables():
    """Tabloların oluşturulduğundan emin ol"""
    global _tables_initialized
    if not _tables_initialized:
        init_reviewer_tables()
        _tables_initialized = True


# ============================================
# DASHBOARD
# ============================================

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def reviewer_dashboard(request: Request, db: Session = Depends(get_db)):
    """Reviewer Agent - Dashboard"""
    try:
        ensure_tables()
        
        # İstatistikler
        total_pending = db.query(ReviewerQueue).filter(
            ReviewerQueue.status == QueueStatus.PENDING
        ).count()
        
        total_in_progress = db.query(ReviewerQueue).filter(
            ReviewerQueue.status == QueueStatus.IN_PROGRESS
        ).count()
        
        total_completed = db.query(ReviewerQueue).filter(
            ReviewerQueue.status == QueueStatus.COMPLETED
        ).count()
        
        # Öncelik sırasına göre bekleyenler (en yüksek öncelik önce)
        pending_items = db.query(ReviewerQueue).filter(
            ReviewerQueue.status == QueueStatus.PENDING
        ).order_by(
            desc(ReviewerQueue.priority_score),
            asc(ReviewerQueue.created_at)
        ).limit(20).all()
        
        # İşlenmekte olanlar
        in_progress_items = db.query(ReviewerQueue).filter(
            ReviewerQueue.status == QueueStatus.IN_PROGRESS
        ).order_by(asc(ReviewerQueue.started_at)).limit(10).all()
        
        # Son tamamlananlar
        completed_items = db.query(ReviewerQueue).filter(
            ReviewerQueue.status == QueueStatus.COMPLETED
        ).order_by(desc(ReviewerQueue.completed_at)).limit(10).all()
        
        return templates.TemplateResponse("reviewer/dashboard.html", {
            "request": request,
            "current_page": "reviewer",
            "total_pending": total_pending,
            "total_in_progress": total_in_progress,
            "total_completed": total_completed,
            "pending_items": pending_items,
            "in_progress_items": in_progress_items,
            "completed_items": completed_items
        })
    
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_trace = traceback.format_exc()
        print(f"❌ Reviewer dashboard hatası: {error_msg}")
        print(error_trace)
        
        from config import settings
        from fastapi.templating import Jinja2Templates
        main_templates = Jinja2Templates(directory=str(settings.TEMPLATES_DIR))
        
        return main_templates.TemplateResponse(
            "base.html",
            {
                "request": request,
                "current_page": None,
                "error": f"Dashboard yüklenirken hata oluştu: {error_msg}<br><pre>{error_trace}</pre>"
            },
            status_code=500
        )


# ============================================
# API ENDPOINTS
# ============================================

@router.get("/api/queue")
async def get_queue(
    status: Optional[str] = Query(None),
    priority: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """Kuyruğu listele"""
    ensure_tables()
    
    query = db.query(ReviewerQueue)
    
    if status:
        try:
            query = query.filter(ReviewerQueue.status == QueueStatus[status])
        except KeyError:
            pass
    
    if priority:
        query = query.filter(ReviewerQueue.priority_score == priority)
    
    # Öncelik sırasına göre sırala
    items = query.order_by(
        desc(ReviewerQueue.priority_score),
        asc(ReviewerQueue.created_at)
    ).limit(limit).all()
    
    return {
        "status": "success",
        "items": [
            {
                "id": item.id,
                "observer_report_id": item.observer_report_id,
                "site_id": item.site_id,
                "page_url": item.page_url,
                "rule_name": item.rule_name,
                "severity": item.severity,
                "priority_score": item.priority_score,
                "status": item.status.value,
                "action_plan": item.action_plan,
                "action_type": item.action_type,
                "created_at": item.created_at.isoformat() if item.created_at else None
            }
            for item in items
        ]
    }


@router.post("/api/queue/{item_id}/start")
async def start_queue_item(
    item_id: int,
    db: Session = Depends(get_db)
):
    """Kuyruk öğesini işleme başlat"""
    ensure_tables()
    
    item = db.query(ReviewerQueue).filter(ReviewerQueue.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Kuyruk öğesi bulunamadı")
    
    if item.status != QueueStatus.PENDING:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Sadece bekleyen öğeler işleme alınabilir"}
        )
    
    item.status = QueueStatus.IN_PROGRESS
    item.started_at = datetime.utcnow()
    db.commit()
    
    return {"status": "success", "message": "İşleme başlatıldı"}


@router.post("/api/queue/{item_id}/complete")
async def complete_queue_item(
    item_id: int,
    notes: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Kuyruk öğesini tamamla"""
    ensure_tables()
    
    item = db.query(ReviewerQueue).filter(ReviewerQueue.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Kuyruk öğesi bulunamadı")
    
    item.status = QueueStatus.COMPLETED
    item.completed_at = datetime.utcnow()
    if notes:
        item.notes = notes
    db.commit()
    
    return {"status": "success", "message": "Tamamlandı"}


@router.post("/api/queue/{item_id}/skip")
async def skip_queue_item(
    item_id: int,
    notes: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Kuyruk öğesini atla"""
    ensure_tables()
    
    item = db.query(ReviewerQueue).filter(ReviewerQueue.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Kuyruk öğesi bulunamadı")
    
    item.status = QueueStatus.SKIPPED
    item.completed_at = datetime.utcnow()
    if notes:
        item.notes = notes
    db.commit()
    
    return {"status": "success", "message": "Atlandı"}


@router.post("/api/process-observer-reports")
async def process_observer_reports(
    site_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """Observer raporlarını işle ve kuyruğa ekle"""
    ensure_tables()
    
    from .worker import process_reports_to_queue
    
    try:
        count = process_reports_to_queue(db, site_id)
        return {
            "status": "success",
            "message": f"{count} rapor kuyruğa eklendi",
            "count": count
        }
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ Observer raporları işlenirken hata: {e}")
        print(error_trace)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )


# ============================================
# TAMAMLANAMAYAN GÖREVLER (Controller Retry)
# ============================================

@router.get("/api/failed-tasks")
async def get_failed_tasks(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """
    Controller tarafından başarısız bulunup tekrar kuyruğa alınan görevleri getir
    """
    ensure_tables()

    from agents.controller.models import ControllerTask, VerificationStatus
    from agents.dispatcher.models import DispatcherTask

    # Controller tarafından VERIFIED_FAILED olarak işaretlenmiş görevler
    failed_controller_tasks = db.query(ControllerTask).filter(
        ControllerTask.status == VerificationStatus.VERIFIED_FAILED
    ).order_by(desc(ControllerTask.verification_completed_at)).limit(limit).all()

    result = []
    for controller_task in failed_controller_tasks:
        # Bu görev için Dispatcher'da retry task var mı?
        retry_task = db.query(DispatcherTask).filter(
            DispatcherTask.source_type == "CONTROLLER_RETRY",
            DispatcherTask.source_id == controller_task.id
        ).order_by(desc(DispatcherTask.created_at)).first()

        # Bu görev için Reviewer'da queue item var mı?
        reviewer_item = None
        if controller_task.observer_report:
            observer_report_id = controller_task.observer_report.get("observer_task_id") if isinstance(controller_task.observer_report, dict) else None
            if observer_report_id:
                reviewer_item = db.query(ReviewerQueue).filter(
                    ReviewerQueue.page_url == controller_task.page_url,
                    ReviewerQueue.rule_name == controller_task.task_type
                ).order_by(desc(ReviewerQueue.created_at)).first()

        result.append({
            "id": controller_task.id,
            "page_url": controller_task.page_url,
            "task_type": controller_task.task_type,
            "task_description": controller_task.task_description,
            "source_agent": controller_task.source_agent,
            "retry_count": controller_task.retry_count,
            "verification_completed_at": controller_task.verification_completed_at.isoformat() if controller_task.verification_completed_at else None,
            "verification_notes": controller_task.verification_notes,
            "observer_report": controller_task.observer_report,
            "retry_task": {
                "id": retry_task.id if retry_task else None,
                "status": retry_task.status.value if retry_task else None,
                "created_at": retry_task.created_at.isoformat() if retry_task and retry_task.created_at else None
            } if retry_task else None,
            "reviewer_item": {
                "id": reviewer_item.id if reviewer_item else None,
                "status": reviewer_item.status.value if reviewer_item else None,
                "priority_score": reviewer_item.priority_score if reviewer_item else None
            } if reviewer_item else None
        })

    return {
        "status": "success",
        "failed_tasks": result
    }





