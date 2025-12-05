# ============================================
# Controller Agent - Router & Endpoints
# ============================================

from fastapi import APIRouter, Request, Depends, HTTPException, Query, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc, func
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path

from core.database import get_db, Site
from .models import (
    ControllerTask, VerificationStatus, ControllerStats,
    init_controller_tables
)
from .worker import (
    receive_completion_notification,
    verify_task_completion,
    process_observer_verification_result,
    auto_verify_pending_tasks,
    check_observer_verifications
)

# Template dizinleri
CONTROLLER_TEMPLATE_DIR = Path(__file__).parent / "templates"
MAIN_TEMPLATE_DIR = Path(__file__).parent.parent.parent / "templates"

templates = Jinja2Templates(directory=[str(CONTROLLER_TEMPLATE_DIR), str(MAIN_TEMPLATE_DIR)])

router = APIRouter(prefix="/agents/controller", tags=["Controller Agent"])

# Tablo oluşturma (ilk çalıştırmada)
_tables_initialized = False


def ensure_tables():
    """Tabloların oluşturulduğundan emin ol"""
    global _tables_initialized
    if not _tables_initialized:
        init_controller_tables()
        _tables_initialized = True


# ============================================
# DASHBOARD
# ============================================

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def controller_dashboard(request: Request, db: Session = Depends(get_db)):
    """Controller Agent - Dashboard"""
    try:
        ensure_tables()

        # İstatistikler
        total_pending = db.query(ControllerTask).filter(
            ControllerTask.status == VerificationStatus.PENDING
        ).count()

        total_verifying = db.query(ControllerTask).filter(
            ControllerTask.status == VerificationStatus.VERIFYING
        ).count()

        total_verified_success = db.query(ControllerTask).filter(
            ControllerTask.status == VerificationStatus.VERIFIED_SUCCESS
        ).count()

        total_verified_failed = db.query(ControllerTask).filter(
            ControllerTask.status == VerificationStatus.VERIFIED_FAILED
        ).count()

        total_retry_assigned = db.query(ControllerTask).filter(
            ControllerTask.status == VerificationStatus.RETRY_ASSIGNED
        ).count()

        # Bugünkü istatistikler
        today = datetime.utcnow().date()
        today_stats = db.query(ControllerStats).filter(
            func.date(ControllerStats.date) == today,
            ControllerStats.period_type == "daily"
        ).first()

        # Bekleyen görevler
        pending_tasks = db.query(ControllerTask).filter(
            ControllerTask.status == VerificationStatus.PENDING
        ).order_by(asc(ControllerTask.created_at)).limit(20).all()

        # Doğrulanıyor
        verifying_tasks = db.query(ControllerTask).filter(
            ControllerTask.status == VerificationStatus.VERIFYING
        ).order_by(asc(ControllerTask.verification_started_at)).limit(10).all()

        # Başarılı doğrulamalar (son 20)
        verified_success_tasks = db.query(ControllerTask).filter(
            ControllerTask.status == VerificationStatus.VERIFIED_SUCCESS
        ).order_by(desc(ControllerTask.verification_completed_at)).limit(20).all()

        # Başarısız doğrulamalar (son 20)
        verified_failed_tasks = db.query(ControllerTask).filter(
            ControllerTask.status == VerificationStatus.VERIFIED_FAILED
        ).order_by(desc(ControllerTask.verification_completed_at)).limit(20).all()

        # Tekrar atananlar
        retry_assigned_tasks = db.query(ControllerTask).filter(
            ControllerTask.status == VerificationStatus.RETRY_ASSIGNED
        ).order_by(desc(ControllerTask.created_at)).limit(10).all()

        # Son 7 günlük başarı oranı grafiği için veri
        last_7_days = []
        for i in range(6, -1, -1):
            day = today - timedelta(days=i)
            day_stats = db.query(ControllerStats).filter(
                func.date(ControllerStats.date) == day,
                ControllerStats.period_type == "daily"
            ).first()

            if day_stats:
                last_7_days.append({
                    "date": day.strftime("%Y-%m-%d"),
                    "success_rate": day_stats.success_rate,
                    "total_verifications": day_stats.total_verifications
                })
            else:
                last_7_days.append({
                    "date": day.strftime("%Y-%m-%d"),
                    "success_rate": 0,
                    "total_verifications": 0
                })

        return templates.TemplateResponse("controller/dashboard.html", {
            "request": request,
            "current_page": "controller",
            "total_pending": total_pending,
            "total_verifying": total_verifying,
            "total_verified_success": total_verified_success,
            "total_verified_failed": total_verified_failed,
            "total_retry_assigned": total_retry_assigned,
            "today_stats": today_stats,
            "pending_tasks": pending_tasks,
            "verifying_tasks": verifying_tasks,
            "verified_success_tasks": verified_success_tasks,
            "verified_failed_tasks": verified_failed_tasks,
            "retry_assigned_tasks": retry_assigned_tasks,
            "last_7_days": last_7_days
        })

    except Exception as e:
        import traceback
        error_msg = str(e)
        error_trace = traceback.format_exc()
        print(f"❌ Controller dashboard hatası: {error_msg}")
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

@router.post("/api/notify-completion")
async def notify_completion(
    source_agent: str = Body(...),
    source_task_id: int = Body(...),
    site_id: int = Body(...),
    page_url: str = Body(...),
    task_type: str = Body(...),
    task_description: str = Body(...),
    agent_report: dict = Body(...),
    page_id: Optional[int] = Body(None),
    dispatcher_task_id: Optional[int] = Body(None),
    original_issue: Optional[dict] = Body(None),
    db: Session = Depends(get_db)
):
    """
    Agent'tan tamamlanma bildirimi al

    Body:
        - source_agent: Hangi agent'tan geldi (FIXER, AI_HELPER)
        - source_task_id: Agent'ın task ID'si
        - site_id: Site ID
        - page_id: Page ID (opsiyonel)
        - page_url: Sayfa URL'i
        - task_type: Görev tipi
        - task_description: Görev açıklaması
        - agent_report: Agent'ın raporladığı sonuç
        - dispatcher_task_id: Dispatcher task ID (opsiyonel)
        - original_issue: Orijinal sorun (opsiyonel)
    """
    ensure_tables()

    try:
        controller_task = receive_completion_notification(
            db=db,
            source_agent=source_agent,
            source_task_id=source_task_id,
            site_id=site_id,
            page_id=page_id,
            page_url=page_url,
            task_type=task_type,
            task_description=task_description,
            agent_report=agent_report,
            dispatcher_task_id=dispatcher_task_id,
            original_issue=original_issue
        )

        return {
            "status": "success",
            "message": "Tamamlanma bildirimi alındı",
            "controller_task_id": controller_task.id
        }

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ Tamamlanma bildirimi hatası: {e}")
        print(error_trace)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )


@router.post("/api/verify/{controller_task_id}")
async def verify_task(
    controller_task_id: int,
    db: Session = Depends(get_db)
):
    """Görevi Observer'a göndererek doğrula"""
    ensure_tables()

    try:
        result = verify_task_completion(db, controller_task_id)
        return result

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ Doğrulama hatası: {e}")
        print(error_trace)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )


@router.get("/api/tasks")
async def get_tasks(
    status: Optional[str] = Query(None),
    source_agent: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """Görevleri listele"""
    ensure_tables()

    query = db.query(ControllerTask)

    if status:
        try:
            query = query.filter(ControllerTask.status == VerificationStatus[status])
        except KeyError:
            pass

    if source_agent:
        query = query.filter(ControllerTask.source_agent == source_agent)

    tasks = query.order_by(desc(ControllerTask.created_at)).limit(limit).all()

    return {
        "status": "success",
        "tasks": [
            {
                "id": task.id,
                "source_agent": task.source_agent,
                "source_task_id": task.source_task_id,
                "page_url": task.page_url,
                "task_type": task.task_type,
                "status": task.status.value,
                "is_verified": task.is_verified,
                "retry_count": task.retry_count,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "verification_completed_at": task.verification_completed_at.isoformat() if task.verification_completed_at else None
            }
            for task in tasks
        ]
    }


@router.get("/api/tasks/{task_id}/history")
async def get_task_history(
    task_id: int,
    db: Session = Depends(get_db)
):
    """Görevin tüm geçmişini getir"""
    ensure_tables()

    task = db.query(ControllerTask).filter(ControllerTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Görev bulunamadı")

    # task_history JSON ise, Python listesine çevir
    import json
    task_history = task.task_history
    if isinstance(task_history, str):
        try:
            task_history = json.loads(task_history)
        except:
            task_history = []

    return {
        "status": "success",
        "task_id": task.id,
        "task_history": task_history
    }


@router.post("/api/auto-verify")
async def auto_verify(
    batch_size: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db)
):
    """Bekleyen görevleri otomatik olarak doğrula"""
    ensure_tables()

    try:
        result = auto_verify_pending_tasks(batch_size)
        return {
            "status": "success",
            "message": f"{result['verified']} görev doğrulamaya gönderildi",
            "result": result
        }

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ Otomatik doğrulama hatası: {e}")
        print(error_trace)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )


@router.post("/api/check-verifications")
async def check_verifications(db: Session = Depends(get_db)):
    """Observer doğrulamalarını kontrol et"""
    ensure_tables()

    try:
        result = check_observer_verifications()
        return {
            "status": "success",
            "message": f"{result['success']} başarılı, {result['failed']} başarısız",
            "result": result
        }

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ Doğrulama kontrolü hatası: {e}")
        print(error_trace)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )


@router.get("/api/stats")
async def get_stats(
    period: str = Query("daily", regex="^(daily|weekly|monthly)$"),
    db: Session = Depends(get_db)
):
    """İstatistikleri getir"""
    ensure_tables()

    # Son 30 günlük istatistik
    stats = db.query(ControllerStats).filter(
        ControllerStats.period_type == period
    ).order_by(desc(ControllerStats.date)).limit(30).all()

    return {
        "status": "success",
        "stats": [
            {
                "date": stat.date.isoformat() if stat.date else None,
                "total_verifications": stat.total_verifications,
                "verified_success": stat.verified_success,
                "verified_failed": stat.verified_failed,
                "retry_assigned": stat.retry_assigned,
                "success_rate": stat.success_rate,
                "fixer_success": stat.fixer_success,
                "fixer_failed": stat.fixer_failed,
                "ai_helper_success": stat.ai_helper_success,
                "ai_helper_failed": stat.ai_helper_failed
            }
            for stat in stats
        ]
    }
