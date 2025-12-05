# ============================================
# Dispatcher Agent - Router & Endpoints
# ============================================

from fastapi import APIRouter, Request, Depends, HTTPException, Query, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc, and_
from datetime import datetime
from typing import Optional, List
from pathlib import Path

from core.database import get_db, Site
from .models import (
    DispatcherTask, DispatcherTaskStatus, AgentType, AgentRoutingRule,
    get_agent_for_task, init_dispatcher_tables
)

# Template dizinleri
DISPATCHER_TEMPLATE_DIR = Path(__file__).parent / "templates"
MAIN_TEMPLATE_DIR = Path(__file__).parent.parent.parent / "templates"

templates = Jinja2Templates(directory=[str(DISPATCHER_TEMPLATE_DIR), str(MAIN_TEMPLATE_DIR)])

router = APIRouter(prefix="/agents/dispatcher", tags=["Dispatcher Agent"])

# Tablo oluşturma (ilk çalıştırmada)
_tables_initialized = False


def ensure_tables():
    """Tabloların oluşturulduğundan emin ol"""
    global _tables_initialized
    if not _tables_initialized:
        init_dispatcher_tables()
        _tables_initialized = True


# ============================================
# DASHBOARD
# ============================================

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dispatcher_dashboard(request: Request, db: Session = Depends(get_db)):
    """Dispatcher Agent - Dashboard"""
    try:
        ensure_tables()
        
        # Eski AgentType değerlerini temizle (OBSERVER, REVIEWER, ANALYZER -> FIXER veya None)
        # Eğer eski değerler varsa, bunları None yap veya FIXER'a çevir
        try:
            # Tüm görevleri al ve assigned_agent'ı kontrol et
            all_tasks = db.query(DispatcherTask).all()
            updated_count = 0
            
            for task in all_tasks:
                try:
                    # Eğer assigned_agent None değilse ve FIXER değilse
                    if task.assigned_agent is not None:
                        agent_value = task.assigned_agent.value if hasattr(task.assigned_agent, 'value') else str(task.assigned_agent)
                        
                        # Eski değerler (OBSERVER, REVIEWER, ANALYZER) varsa temizle
                        if agent_value not in ['FIXER', 'UNKNOWN']:
                            # Eğer link düzeltme görevi ise FIXER'a çevir
                            if task.task_type and ('LINK' in task.task_type.upper() or 'FIX' in task.task_type.upper()):
                                task.assigned_agent = AgentType.FIXER
                                updated_count += 1
                            else:
                                # Diğer görevler için None yap (artık desteklenmiyor)
                                task.assigned_agent = None
                                updated_count += 1
                except (AttributeError, ValueError) as e:
                    # Enum hatası varsa None yap
                    task.assigned_agent = None
                    updated_count += 1
            
            if updated_count > 0:
                db.commit()
                print(f"✅ {updated_count} eski AgentType değeri temizlendi")
        except Exception as cleanup_error:
            # Temizleme hatası önemli değil, devam et
            print(f"⚠️ Eski AgentType temizleme hatası (önemsiz): {cleanup_error}")
            db.rollback()
        
        # İstatistikler - Sadece FIXER agent için
        # Güvenli sorgu: assigned_agent None değilse ve FIXER ise
        try:
            total_pending = db.query(DispatcherTask).filter(
                DispatcherTask.status == DispatcherTaskStatus.PENDING,
                DispatcherTask.assigned_agent == AgentType.FIXER
            ).count()
        except Exception:
            total_pending = 0
        
        try:
            total_assigned = db.query(DispatcherTask).filter(
                DispatcherTask.status == DispatcherTaskStatus.ASSIGNED,
                DispatcherTask.assigned_agent == AgentType.FIXER
            ).count()
        except Exception:
            total_assigned = 0
        
        try:
            total_in_progress = db.query(DispatcherTask).filter(
                DispatcherTask.status == DispatcherTaskStatus.IN_PROGRESS,
                DispatcherTask.assigned_agent == AgentType.FIXER
            ).count()
        except Exception:
            total_in_progress = 0
        
        try:
            total_completed = db.query(DispatcherTask).filter(
                DispatcherTask.status == DispatcherTaskStatus.COMPLETED,
                DispatcherTask.assigned_agent == AgentType.FIXER
            ).count()
        except Exception:
            total_completed = 0
        
        # Bekleyen görevler (öncelik sırasına göre) - Sadece FIXER agent'a atanmış olanlar
        try:
            pending_tasks = db.query(DispatcherTask).filter(
                DispatcherTask.status == DispatcherTaskStatus.PENDING,
                DispatcherTask.assigned_agent == AgentType.FIXER
            ).order_by(
                desc(DispatcherTask.priority),
                asc(DispatcherTask.created_at)
            ).limit(20).all()
        except Exception:
            pending_tasks = []
        
        # Atanmış görevler - Sadece FIXER agent'a atanmış olanlar
        try:
            assigned_tasks = db.query(DispatcherTask).filter(
                DispatcherTask.status == DispatcherTaskStatus.ASSIGNED,
                DispatcherTask.assigned_agent == AgentType.FIXER
            ).order_by(asc(DispatcherTask.assigned_at)).limit(10).all()
        except Exception:
            assigned_tasks = []
        
        # İşlenmekte olanlar - Sadece FIXER agent'a atanmış olanlar
        try:
            in_progress_tasks = db.query(DispatcherTask).filter(
                DispatcherTask.status == DispatcherTaskStatus.IN_PROGRESS,
                DispatcherTask.assigned_agent == AgentType.FIXER
            ).order_by(asc(DispatcherTask.started_at)).limit(10).all()
        except Exception:
            in_progress_tasks = []
        
        # Son tamamlananlar - Sadece FIXER agent'a atanmış olanlar
        try:
            completed_tasks = db.query(DispatcherTask).filter(
                DispatcherTask.status == DispatcherTaskStatus.COMPLETED,
                DispatcherTask.assigned_agent == AgentType.FIXER
            ).order_by(desc(DispatcherTask.completed_at)).limit(10).all()
        except Exception:
            completed_tasks = []
        
        # Agent bazında istatistikler (sadece FIXER)
        try:
            agent_stats = {
                "FIXER": {
                    "pending": db.query(DispatcherTask).filter(
                        DispatcherTask.assigned_agent == AgentType.FIXER,
                        DispatcherTask.status == DispatcherTaskStatus.PENDING
                    ).count(),
                    "in_progress": db.query(DispatcherTask).filter(
                        DispatcherTask.assigned_agent == AgentType.FIXER,
                        DispatcherTask.status == DispatcherTaskStatus.IN_PROGRESS
                    ).count(),
                    "completed": db.query(DispatcherTask).filter(
                        DispatcherTask.assigned_agent == AgentType.FIXER,
                        DispatcherTask.status == DispatcherTaskStatus.COMPLETED
                    ).count()
                }
            }
        except Exception:
            agent_stats = {
                "FIXER": {
                    "pending": 0,
                    "in_progress": 0,
                    "completed": 0
                }
            }
        
        return templates.TemplateResponse("dispatcher/dashboard.html", {
            "request": request,
            "current_page": "dispatcher",
            "total_pending": total_pending,
            "total_assigned": total_assigned,
            "total_in_progress": total_in_progress,
            "total_completed": total_completed,
            "pending_tasks": pending_tasks,
            "assigned_tasks": assigned_tasks,
            "in_progress_tasks": in_progress_tasks,
            "completed_tasks": completed_tasks,
            "agent_stats": agent_stats
        })
    
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_trace = traceback.format_exc()
        print(f"❌ Dispatcher dashboard hatası: {error_msg}")
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

@router.post("/api/tasks/create")
async def create_task(
    task_name: str = Body(...),
    task_type: str = Body(...),
    site_id: int = Body(...),
    page_id: Optional[int] = Body(None),
    page_url: Optional[str] = Body(None),
    task_description: Optional[str] = Body(None),
    task_params: Optional[dict] = Body(None),
    priority: int = Body(0),
    source_type: Optional[str] = Body(None),
    source_id: Optional[int] = Body(None),
    db: Session = Depends(get_db)
):
    """Yeni görev oluştur"""
    ensure_tables()
    
    try:
        # Uygun agent'ı belirle
        assigned_agent = get_agent_for_task(task_type, db)
        
        if assigned_agent == AgentType.UNKNOWN:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": f"Görev tipi '{task_type}' için uygun agent bulunamadı"}
            )
        
        # Site kontrolü
        site = db.query(Site).filter(Site.id == site_id).first()
        if not site:
            return JSONResponse(
                status_code=404,
                content={"status": "error", "message": "Site bulunamadı"}
            )
        
        # Görev oluştur
        task = DispatcherTask(
            task_name=task_name,
            task_type=task_type,
            task_description=task_description,
            site_id=site_id,
            page_id=page_id,
            page_url=page_url,
            task_params=task_params or {},
            priority=priority,
            source_type=source_type,
            source_id=source_id,
            assigned_agent=assigned_agent,
            status=DispatcherTaskStatus.PENDING,
            created_at=datetime.utcnow()
        )
        
        db.add(task)
        db.commit()
        db.refresh(task)
        
        return {
            "status": "success",
            "message": "Görev oluşturuldu",
            "task": {
                "id": task.id,
                "task_name": task.task_name,
                "task_type": task.task_type,
                "assigned_agent": task.assigned_agent.value if task.assigned_agent else None,
                "status": task.status.value
            }
        }
    
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ Görev oluşturma hatası: {e}")
        print(error_trace)
        db.rollback()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )


@router.get("/api/tasks")
async def get_tasks(
    status: Optional[str] = Query(None),
    agent: Optional[str] = Query(None),
    site_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """Görevleri listele"""
    ensure_tables()
    
    query = db.query(DispatcherTask)
    
    if status:
        try:
            query = query.filter(DispatcherTask.status == DispatcherTaskStatus[status])
        except KeyError:
            pass
    
    if agent:
        try:
            query = query.filter(DispatcherTask.assigned_agent == AgentType[agent])
        except KeyError:
            pass
    
    if site_id:
        query = query.filter(DispatcherTask.site_id == site_id)
    
    # Öncelik sırasına göre sırala
    tasks = query.order_by(
        desc(DispatcherTask.priority),
        asc(DispatcherTask.created_at)
    ).limit(limit).all()
    
    return {
        "status": "success",
        "tasks": [
            {
                "id": task.id,
                "task_name": task.task_name,
                "task_type": task.task_type,
                "site_id": task.site_id,
                "page_url": task.page_url,
                "assigned_agent": task.assigned_agent.value if task.assigned_agent else None,
                "status": task.status.value,
                "priority": task.priority,
                "created_at": task.created_at.isoformat() if task.created_at else None
            }
            for task in tasks
        ]
    }


@router.post("/api/tasks/{task_id}/assign")
async def assign_task(
    task_id: int,
    db: Session = Depends(get_db)
):
    """Görevi agent'a ata ve işleme başlat"""
    ensure_tables()
    
    from .worker import assign_task_to_agent
    
    try:
        result = assign_task_to_agent(db, task_id)
        return result
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ Görev atama hatası: {e}")
        print(error_trace)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )


@router.post("/api/tasks/{task_id}/complete")
async def complete_task(
    task_id: int,
    result: Optional[dict] = Body(None),
    error_message: Optional[str] = Body(None),
    db: Session = Depends(get_db)
):
    """Görevi tamamla"""
    ensure_tables()
    
    task = db.query(DispatcherTask).filter(DispatcherTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Görev bulunamadı")
    
    task.status = DispatcherTaskStatus.COMPLETED
    task.completed_at = datetime.utcnow()
    if result:
        task.result = result
    if error_message:
        task.error_message = error_message
        task.status = DispatcherTaskStatus.FAILED
    
    db.commit()
    
    return {"status": "success", "message": "Görev tamamlandı"}


@router.post("/api/process-reviewer-queue")
async def process_reviewer_queue(
    batch_size: int = Query(None, ge=1, le=10000),
    auto_assign: bool = Query(True),
    db: Session = Depends(get_db)
):
    """
    Reviewer kuyruğundaki TÜM bekleyen öğeleri Dispatcher'a görev olarak ekle
    Manuel tetikleme için endpoint (otomatik sistem zaten çalışıyor)
    
    Args:
        batch_size: Artık kullanılmıyor, TÜM görevler işlenir (geriye uyumluluk için tutuldu)
        auto_assign: Görevleri otomatik olarak agent'lara ata (default: True)
    """
    ensure_tables()
    
    from .scheduler import process_reviewer_queue_batch, auto_assign_pending_tasks_batch
    from .worker import assign_task_to_agent
    
    try:
        # Reviewer queue'dan görevleri al: İlk 10'u anında ata, geri kalanını kuyruğa ekle
        result = process_reviewer_queue_batch()
        
        # Eğer auto_assign True ise, kuyruktaki görevlerden 10 tanesini öncelik sırasına göre ata
        if auto_assign and result.get("queued", 0) > 0:
            assign_result = auto_assign_pending_tasks_batch(10)
            result["assigned"] = assign_result["assigned"]
            result["assign_errors"] = assign_result["errors"]
        
        return {
            "status": "success",
            "message": f"{result['created']} görev oluşturuldu, {result.get('assigned', 0)} görev atandı",
            "result": result
        }
    
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ Reviewer queue işleme hatası: {e}")
        print(error_trace)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Hata: {str(e)}"}
        )

