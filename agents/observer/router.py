# ============================================
# Observer Agent - Router & Endpoints
# ============================================

from fastapi import APIRouter, Request, Depends, HTTPException, BackgroundTasks, Query, Body
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, or_, and_
from datetime import datetime, timedelta
from typing import Optional, List
from pathlib import Path

from core.database import get_db, Site, Page, get_setting, set_setting
from .models import (
    ObserverTask, ObserverReport, ObserverRule,
    TaskStatus, TaskType, ReportSeverity,
    init_observer_tables
)

# Template dizinleri
OBSERVER_TEMPLATE_DIR = Path(__file__).parent / "templates"
MAIN_TEMPLATE_DIR = Path(__file__).parent.parent.parent / "templates"

templates = Jinja2Templates(directory=[str(OBSERVER_TEMPLATE_DIR), str(MAIN_TEMPLATE_DIR)])

router = APIRouter(prefix="/agents/observer", tags=["Observer Agent"])

# Tablo oluşturma (ilk çalıştırmada)
_tables_initialized = False


def ensure_tables():
    """Tabloların var olduğundan emin ol"""
    global _tables_initialized
    if not _tables_initialized:
        init_observer_tables()
        _tables_initialized = True


# ============================================
# SITE SEÇİMİ (Ana Sayfa)
# ============================================

def get_selected_site_id(request: Request, db: Session = None) -> Optional[int]:
    """
    Seçilen site ID'sini al (Database öncelikli, cookie fallback)
    """
    # Önce database'den al (kalıcı çözüm)
    if db:
        try:
            site_id_str = get_setting(db, "OBSERVER_SELECTED_SITE_ID")
            if site_id_str:
                try:
                    site_id = int(site_id_str)
                    if site_id > 0:
                        # Site'in hala var olduğunu kontrol et
                        site = db.query(Site).filter(
                            Site.id == site_id,
                            Site.is_competitor == False,
                            Site.is_active == True
                        ).first()
                        if site:
                            return site_id
                except (ValueError, TypeError):
                    pass
        except Exception:
            pass
    
    # Database'de yoksa cookie'den al (fallback)
    selected_site_id = request.cookies.get("agents_selected_site_id")
    if selected_site_id:
        try:
            site_id = int(selected_site_id)
            if site_id > 0:
                return site_id
        except (ValueError, TypeError):
            pass
    
    return None


def save_selected_site(db: Session, site_id: int) -> bool:
    """Seçilen site'i database'e kaydet (kalıcı)"""
    try:
        set_setting(db, "OBSERVER_SELECTED_SITE_ID", str(site_id))
        return True
    except Exception as e:
        print(f"⚠️ Site seçimi kaydedilemedi: {e}")
        return False


def clear_selected_site(db: Session = None, response: RedirectResponse = None) -> Optional[RedirectResponse]:
    """Seçilen site'i temizle (database ve cookie)"""
    if db:
        try:
            set_setting(db, "OBSERVER_SELECTED_SITE_ID", "")
        except Exception:
            pass
    
    if response:
        response.delete_cookie(key="agents_selected_site_id", path="/")
        return response
    return None


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def observer_main(request: Request, db: Session = Depends(get_db)):
    """Observer Agent - Ana Sayfa (Site seçimi veya dashboard)"""
    ensure_tables()
    
    # Database'den seçilen site'i kontrol et
    selected_site_id = get_selected_site_id(request, db)
    
    if selected_site_id:
        # Site seçilmişse dashboard'a yönlendir
        return RedirectResponse(url=f"/agents/observer/dashboard", status_code=303)
    else:
        # Site seçilmemişse site seçim ekranına yönlendir
        return RedirectResponse(url="/agents/observer/select-site", status_code=303)


@router.get("/select-site", response_class=HTMLResponse)
async def site_selection(request: Request, db: Session = Depends(get_db)):
    """Observer Agent - Site Seçimi Sayfası"""
    ensure_tables()
    
    # Bizim sitelerimiz
    my_sites = db.query(Site).filter(
        Site.is_competitor == False,
        Site.is_active == True
    ).all()
    
    return templates.TemplateResponse("observer/site_select.html", {
        "request": request,
        "current_page": "observer",
        "my_sites": my_sites
    })


@router.post("/select-site")
async def set_selected_site(request: Request, db: Session = Depends(get_db)):
    """Seçilen site'i cookie'ye kaydet"""
    try:
        # JSON body'yi al
        data = await request.json()
        site_id = data.get("site_id")
        
        if not site_id:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "site_id parametresi gerekli"}
            )
        
        # Site'in var olduğunu kontrol et
        site = db.query(Site).filter(Site.id == site_id, Site.is_competitor == False).first()
        if not site:
            return JSONResponse(
                status_code=404,
                content={"status": "error", "message": "Site bulunamadı"}
            )
        
        # Database'e kaydet (kalıcı)
        save_selected_site(db, site_id)
        
        # Cookie'ye de kaydet (fallback için)
        response = RedirectResponse(url="/agents/observer/dashboard", status_code=303)
        response.set_cookie(
            key="agents_selected_site_id",
            value=str(site_id),
            max_age=30 * 24 * 60 * 60,  # 30 gün
            httponly=True,
            samesite="lax"
        )
        return response
    except Exception as e:
        return JSONResponse(
            status_code=422,
            content={"status": "error", "message": f"Hata: {str(e)}"}
        )


@router.post("/api/clear-all-tasks")
async def clear_all_agent_tasks(db: Session = Depends(get_db)):
    """
    Tüm agent'lardaki görevleri ve raporları temizle
    - Observer tasks (ve tüm reports)
    - Reviewer queue items
    - Dispatcher tasks
    - Link Fixer tasks
    - Son 15 rapor (tüm raporlar zaten cascade delete ile silinir)
    """
    try:
        deleted_counts = {}
        
        # 1. Observer tasks (reports cascade delete ile silinecek)
        try:
            from .models import ObserverTask, ObserverReport
            # Önce reports'ları say
            observer_reports_count = db.query(ObserverReport).count()
            observer_tasks_count = db.query(ObserverTask).count()
            
            # Observer tasks'ları sil (cascade ile reports da silinir)
            db.query(ObserverTask).delete()
            deleted_counts["observer_tasks"] = observer_tasks_count
            deleted_counts["observer_reports"] = observer_reports_count
            
            # Eğer cascade delete çalışmadıysa, reports'ları manuel sil
            remaining_reports = db.query(ObserverReport).count()
            if remaining_reports > 0:
                db.query(ObserverReport).delete()
                deleted_counts["observer_reports"] += remaining_reports
        except Exception as e:
            print(f"⚠️ Observer tasks temizleme hatası: {e}")
            deleted_counts["observer_tasks"] = 0
            deleted_counts["observer_reports"] = 0
        
        # 2. Reviewer queue items
        try:
            from agents.reviewer.models import ReviewerQueue
            reviewer_count = db.query(ReviewerQueue).count()
            db.query(ReviewerQueue).delete()
            deleted_counts["reviewer_queue"] = reviewer_count
        except Exception as e:
            print(f"⚠️ Reviewer queue temizleme hatası: {e}")
            deleted_counts["reviewer_queue"] = 0
        
        # 3. Dispatcher tasks
        try:
            from agents.dispatcher.models import DispatcherTask
            dispatcher_count = db.query(DispatcherTask).count()
            db.query(DispatcherTask).delete()
            deleted_counts["dispatcher_tasks"] = dispatcher_count
        except Exception as e:
            print(f"⚠️ Dispatcher tasks temizleme hatası: {e}")
            deleted_counts["dispatcher_tasks"] = 0
        
        # 4. Link Fixer tasks
        try:
            from agents.link_fixer.models import LinkFixTask
            link_fixer_count = db.query(LinkFixTask).count()
            db.query(LinkFixTask).delete()
            deleted_counts["link_fix_tasks"] = link_fixer_count
        except Exception as e:
            print(f"⚠️ Link Fixer tasks temizleme hatası: {e}")
            deleted_counts["link_fix_tasks"] = 0
        
        # Commit tüm değişiklikler
        db.commit()
        
        total_deleted = sum([v for k, v in deleted_counts.items() if k != "observer_reports"])
        total_reports_deleted = deleted_counts.get("observer_reports", 0)
        
        return JSONResponse({
            "status": "success",
            "message": f"Tüm görevler ve raporlar temizlendi. Toplam {total_deleted} görev ve {total_reports_deleted} rapor silindi.",
            "deleted_counts": deleted_counts,
            "total_deleted": total_deleted,
            "total_reports_deleted": total_reports_deleted
        })
    
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ Görev temizleme hatası: {e}")
        print(error_trace)
        db.rollback()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Hata: {str(e)}"}
        )


@router.get("/dashboard", response_class=HTMLResponse)
async def observer_dashboard(request: Request, db: Session = Depends(get_db)):
    """Observer Agent - Dashboard (Seçilen site için)"""
    ensure_tables()
    
    # Database'den seçilen site'i al
    selected_site_id = get_selected_site_id(request, db)
    
    if not selected_site_id:
        # Site seçilmemişse site seçim ekranına yönlendir
        return RedirectResponse(url="/agents/observer/select-site", status_code=303)
    
    # Site'i kontrol et
    site = db.query(Site).filter(
        Site.id == selected_site_id,
        Site.is_competitor == False,
        Site.is_active == True
    ).first()
    
    if not site:
        # Site bulunamadıysa veya pasifse temizle ve site seçim ekranına yönlendir
        response = RedirectResponse(url="/agents/observer/select-site", status_code=303)
        clear_selected_site(db, response)
        return response
    
    # Dashboard'ı göster
    return await site_dashboard_internal(request, selected_site_id, db)


async def site_dashboard_internal(request: Request, site_id: int, db: Session):
    """Observer Agent - Site'e Özel Dashboard (Internal)"""
    try:
        ensure_tables()
        
        # Site kontrolü
        site = db.query(Site).filter(Site.id == site_id, Site.is_competitor == False).first()
        if not site:
            raise HTTPException(status_code=404, detail="Site bulunamadı")
        
        # Bu site için aktif görev
        active_task = None
        try:
            active_task = db.query(ObserverTask).filter(
                ObserverTask.site_id == site_id,
                ObserverTask.status == TaskStatus.RUNNING
            ).order_by(desc(ObserverTask.created_at)).first()
        except Exception as e:
            print(f"⚠️ Aktif görev sorgusu hatası: {e}")
        
        # Bu site için istatistikler
        pending_tasks = 0
        completed_tasks = 0
        reported_issues = 0
        recent_tasks = []
        
        try:
            pending_tasks = db.query(ObserverTask).filter(
                ObserverTask.site_id == site_id,
                ObserverTask.status == TaskStatus.PENDING
            ).count()
        except Exception as e:
            print(f"⚠️ Pending tasks sorgusu hatası: {e}")
        
        try:
            completed_tasks = db.query(ObserverTask).filter(
                ObserverTask.site_id == site_id,
                ObserverTask.status == TaskStatus.COMPLETED
            ).count()
        except Exception as e:
            print(f"⚠️ Completed tasks sorgusu hatası: {e}")
        
        try:
            reported_issues = db.query(ObserverReport).filter(
                ObserverReport.site_id == site_id
            ).count()
        except Exception as e:
            print(f"⚠️ Reported issues sorgusu hatası: {e}")
        
        try:
            recent_tasks = db.query(ObserverTask).filter(
                ObserverTask.site_id == site_id
            ).order_by(desc(ObserverTask.created_at)).limit(5).all()
        except Exception as e:
            print(f"⚠️ Recent tasks sorgusu hatası: {e}")
        
        # Son raporlanan hatalar (15 adet)
        recent_reports = []
        try:
            recent_reports = db.query(ObserverReport).filter(
                ObserverReport.site_id == site_id
            ).order_by(desc(ObserverReport.found_at)).limit(15).all()
        except Exception as e:
            print(f"⚠️ Recent reports sorgusu hatası: {e}")
        
        # Template context
        context = {
            "request": request,
            "current_page": "observer",
            "site": site,
            "active_task": active_task,
            "pending_tasks": pending_tasks,
            "completed_tasks": completed_tasks,
            "reported_issues": reported_issues,
            "recent_tasks": recent_tasks,
            "recent_reports": recent_reports
        }
        
        print(f"📋 Template context hazırlandı: site={site.name}, pending={pending_tasks}, completed={completed_tasks}, recent={len(recent_tasks)}")
        
        return templates.TemplateResponse("observer/site_dashboard.html", context)
    
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_trace = traceback.format_exc()
        print(f"❌ Dashboard hatası: {error_msg}")
        print(error_trace)
        
        # Hata sayfası göster - main.py'deki templates kullan
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

@router.get("/api/selected-site")
async def get_selected_site(request: Request, db: Session = Depends(get_db)):
    """Seçilen site bilgisini getir"""
    ensure_tables()
    
    selected_site_id = get_selected_site_id(request, db)
    
    if not selected_site_id:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": "Site seçilmemiş"}
        )
    
    site = db.query(Site).filter(
        Site.id == selected_site_id,
        Site.is_competitor == False,
        Site.is_active == True
    ).first()
    
    if not site:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": "Site bulunamadı"}
        )
    
    return {
        "status": "success",
        "site": {
            "id": site.id,
            "name": site.name,
            "domain": site.domain
        }
    }


@router.get("/api/tasks")
async def get_tasks(
    status: Optional[str] = Query(None),
    site_id: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    """Görevleri listele"""
    ensure_tables()
    
    query = db.query(ObserverTask)
    
    if status:
        query = query.filter(ObserverTask.status == TaskStatus[status])
    
    if site_id:
        query = query.filter(ObserverTask.site_id == site_id)
    
    tasks = query.order_by(desc(ObserverTask.created_at)).limit(50).all()
    
    return {
        "status": "success",
        "tasks": [
            {
                "id": task.id,
                "site_id": task.site_id,
                "task_type": task.task_type.value,
                "status": task.status.value,
                "progress_percentage": task.progress_percentage,
                "description": task.description,
                "current_item": task.current_item,
                "reports_count": task.reports_count,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None
            }
            for task in tasks
        ]
    }


@router.get("/api/tasks/{task_id}/logs")
async def get_task_logs(
    task_id: int,
    db: Session = Depends(get_db)
):
    """Görev loglarını getir"""
    ensure_tables()
    
    task = db.query(ObserverTask).filter(ObserverTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Görev bulunamadı")
    
    return {
        "status": "success",
        "logs": task.error_log or ""
    }


@router.get("/reports/{site_id}", response_class=HTMLResponse)
async def reports_page(
    request: Request,
    site_id: int,
    page: int = Query(1, ge=1),
    severity: Optional[str] = Query(None),
    rule: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Raporlar sayfası (Eski endpoint - geriye dönük uyumluluk için)"""
    # Database'den seçilen site'i kontrol et, eğer farklıysa güncelle
    selected_site_id = get_selected_site_id(request, db)
    if selected_site_id != site_id:
        save_selected_site(db, site_id)
        response = RedirectResponse(url=f"/agents/observer/reports", status_code=303)
        response.set_cookie(
            key="agents_selected_site_id",
            value=str(site_id),
            max_age=30 * 24 * 60 * 60,
            httponly=True,
            samesite="lax"
        )
        return response
    
    return await reports_page_internal(request, site_id, page, severity, rule, db)


@router.get("/reports", response_class=HTMLResponse)
async def reports_page_from_cookie(
    request: Request,
    page: int = Query(1, ge=1),
    severity: Optional[str] = Query(None),
    rule: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Raporlar sayfası (Database'den site alır)"""
    selected_site_id = get_selected_site_id(request, db)
    if not selected_site_id:
        return RedirectResponse(url="/agents/observer/select-site", status_code=303)
    
    return await reports_page_internal(request, selected_site_id, page, severity, rule, db)


async def reports_page_internal(
    request: Request,
    site_id: int,
    page: int,
    severity: Optional[str],
    rule: Optional[str],
    db: Session
):
    """Raporlar sayfası (Internal)"""
    try:
        ensure_tables()
        
        site = db.query(Site).filter(Site.id == site_id, Site.is_competitor == False).first()
        if not site:
            raise HTTPException(status_code=404, detail="Site bulunamadı")
        
        # Filtreleme
        query = db.query(ObserverReport).filter(ObserverReport.site_id == site_id)
        
        if severity:
            try:
                query = query.filter(ObserverReport.severity == ReportSeverity[severity])
            except KeyError:
                pass
        
        if rule:
            query = query.filter(ObserverReport.rule_name == rule)
        
        # Toplam sayı
        total_reports = query.count()
        
        # Sayfalama
        per_page = 50
        total_pages = (total_reports + per_page - 1) // per_page if total_reports > 0 else 1
        
        # Raporları al
        reports = query.order_by(desc(ObserverReport.found_at)).offset((page - 1) * per_page).limit(per_page).all()
        
        # İstatistikler
        error_count = 0
        warning_count = 0
        info_count = 0
        
        try:
            error_count = db.query(ObserverReport).filter(
                ObserverReport.site_id == site_id,
                ObserverReport.severity == ReportSeverity.ERROR
            ).count()
        except Exception as e:
            print(f"⚠️ Error count sorgusu hatası: {e}")
        
        try:
            warning_count = db.query(ObserverReport).filter(
                ObserverReport.site_id == site_id,
                ObserverReport.severity == ReportSeverity.WARNING
            ).count()
        except Exception as e:
            print(f"⚠️ Warning count sorgusu hatası: {e}")
        
        try:
            info_count = db.query(ObserverReport).filter(
                ObserverReport.site_id == site_id,
                ObserverReport.severity == ReportSeverity.INFO
            ).count()
        except Exception as e:
            print(f"⚠️ Info count sorgusu hatası: {e}")
        
        print(f"📋 Raporlar sayfası: site={site.name}, total={total_reports}, error={error_count}, warning={warning_count}, info={info_count}")
        
        return templates.TemplateResponse("observer/reports.html", {
            "request": request,
            "current_page": "observer",
            "site": site,
            "reports": reports,
            "total_reports": total_reports,
            "error_count": error_count,
            "warning_count": warning_count,
            "info_count": info_count,
            "current_page_num": page,
            "total_pages": total_pages,
            "severity_filter": severity,
            "rule_filter": rule
        })
    
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_trace = traceback.format_exc()
        print(f"❌ Raporlar sayfası hatası: {error_msg}")
        print(error_trace)
        
        # Hata sayfası göster
        from config import settings
        from fastapi.templating import Jinja2Templates
        main_templates = Jinja2Templates(directory=str(settings.TEMPLATES_DIR))
        
        return main_templates.TemplateResponse(
            "base.html",
            {
                "request": request,
                "current_page": None,
                "error": f"Raporlar sayfası yüklenirken hata oluştu: {error_msg}<br><pre>{error_trace}</pre>"
            },
            status_code=500
        )


@router.get("/api/reports")
async def get_reports(
    task_id: Optional[int] = Query(None),
    site_id: Optional[int] = Query(None),
    severity: Optional[str] = Query(None),
    limit: int = Query(100),
    db: Session = Depends(get_db)
):
    """Raporları listele"""
    ensure_tables()
    
    query = db.query(ObserverReport)
    
    if task_id:
        query = query.filter(ObserverReport.task_id == task_id)
    
    if site_id:
        query = query.filter(ObserverReport.site_id == site_id)
    
    if severity:
        query = query.filter(ObserverReport.severity == ReportSeverity[severity])
    
    reports = query.order_by(desc(ObserverReport.found_at)).limit(limit).all()
    
    return {
        "status": "success",
        "reports": [
            {
                "id": report.id,
                "task_id": report.task_id,
                "site_id": report.site_id,
                "page_id": report.page_id,
                "page_url": report.page_url,
                "rule_name": report.rule_name,
                "severity": report.severity.value,
                "message": report.message,
                "details": report.details,
                "found_at": report.found_at.isoformat() if report.found_at else None
            }
            for report in reports
        ]
    }


@router.get("/api/reports/{report_id}")
async def get_report_detail(
    report_id: int,
    db: Session = Depends(get_db)
):
    """Rapor detayını getir"""
    ensure_tables()
    
    report = db.query(ObserverReport).filter(ObserverReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Rapor bulunamadı")
    
    return {
        "status": "success",
        "report": {
            "id": report.id,
            "task_id": report.task_id,
            "site_id": report.site_id,
            "page_id": report.page_id,
            "page_url": report.page_url,
            "rule_name": report.rule_name,
            "severity": report.severity.value,
            "message": report.message,
            "details": report.details,
            "found_at": report.found_at.isoformat() if report.found_at else None
        }
    }


@router.post("/api/tasks/create")
async def create_task(
    request: Request,
    task_type: str = Body(...),
    description: Optional[str] = Body(None),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None
):
    """Yeni görev oluştur (Seçilen site için)"""
    try:
        ensure_tables()
        
        # Database'den seçilen site'i al
        selected_site_id = get_selected_site_id(request, db)
        if not selected_site_id:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Lütfen önce bir site seçin"}
            )
        
        # Site kontrolü
        site = db.query(Site).filter(
            Site.id == selected_site_id,
            Site.is_competitor == False,
            Site.is_active == True
        ).first()
        if not site:
            return JSONResponse(
                status_code=404,
                content={"status": "error", "message": "Site bulunamadı veya pasif"}
            )
        
        # Task type kontrolü
        try:
            task_type_enum = TaskType[task_type]
        except KeyError:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": f"Geçersiz görev tipi: {task_type}"}
            )
        
        # Parent GlobalTask oluştur (AUDIT_SCAN tipinde)
        from agents.global_task.worker import create_parent_audit_task
        parent_task = create_parent_audit_task(
            db=db,
            site_id=selected_site_id,
            task_description=description or f"{task_type_enum.value} görevi - Tarama başlatıldı",
            observer_task_id=None  # Henüz oluşturulmadı, sonra güncellenecek
        )
        
        # Yeni görev oluştur
        task = ObserverTask(
            global_task_id=parent_task.id,  # Parent task ID'sini kullan
            site_id=selected_site_id,
            task_type=task_type_enum,
            status=TaskStatus.PENDING,
            description=description or f"{task_type_enum.value} görevi"
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        
        # Parent GlobalTask'a observer_task_id'yi ekle
        from agents.global_task.worker import update_global_task_agent_id
        update_global_task_agent_id(db, parent_task.id, "OBSERVER", task.id)
        
        # Background task başlat
        from .worker import run_observer_task
        if background_tasks:
            background_tasks.add_task(run_observer_task, task.id)
        
        return {
            "status": "success",
            "message": "Görev oluşturuldu ve başlatıldı",
            "task_id": task.id
        }
    
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_trace = traceback.format_exc()
        print(f"❌ Görev oluşturma hatası: {error_msg}")
        print(error_trace)
        
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Görev oluşturulurken hata oluştu: {error_msg}",
                "error": error_msg
            }
        )


@router.get("/api/my-sites")
async def get_my_sites(db: Session = Depends(get_db)):
    """Bizim sitelerimizi listele"""
    sites = db.query(Site).filter(
        Site.is_competitor == False,
        Site.is_active == True
    ).all()
    
    return [
        {
            "id": site.id,
            "name": site.name,
            "domain": site.domain,
            "sitemap_url": site.sitemap_url
        }
        for site in sites
    ]


@router.post("/api/sites/add")
async def add_site(
    name: str = Body(...),
    domain: str = Body(...),
    sitemap_url: Optional[str] = Body(None),
    is_competitor: bool = Body(False),
    db: Session = Depends(get_db)
):
    """Yeni site ekle (Observer için)"""
    ensure_tables()
    
    # Domain kontrolü
    existing_site = db.query(Site).filter(Site.domain == domain).first()
    if existing_site:
        raise HTTPException(status_code=400, detail="Bu domain zaten kayıtlı")
    
    # Yeni site oluştur
    site = Site(
        name=name,
        domain=domain,
        sitemap_url=sitemap_url,
        is_competitor=is_competitor,
        is_active=True
    )
    db.add(site)
    db.commit()
    db.refresh(site)
    
    return {
        "status": "success",
        "message": "Site eklendi",
        "site_id": site.id
    }


# ============================================
# FRESHNESS RAPORU (site_tools'dan taşındı)
# ============================================

@router.get("/freshness", response_class=HTMLResponse)
async def freshness_report(request: Request, db: Session = Depends(get_db)):
    """
    Freshness Raporu Sayfası (Cookie'den site alır)
    """
    ensure_tables()
    
    selected_site_id = get_selected_site_id(request, db)
    if not selected_site_id:
        return RedirectResponse(url="/agents/observer/select-site", status_code=303)
    
    site = db.query(Site).filter(
        Site.id == selected_site_id,
        Site.is_competitor == False,
        Site.is_active == True
    ).first()
    if not site:
        clear_selected_site(db)
        return RedirectResponse(url="/agents/observer/select-site", status_code=303)
    
    # Freshness ayarını al
    from core.database import get_setting
    freshness_days = int(get_setting(db, "FRESHNESS_THRESHOLD_DAYS") or 45)
    today = datetime.utcnow()
    freshness_threshold = today - timedelta(days=freshness_days)
    
    # Tüm sayfaları al (veritabanından direkt - çok daha hızlı!)
    all_pages = db.query(Page).filter(Page.site_id == selected_site_id).all()
    
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
    
    # Observer raporlarını da göster (eğer varsa)
    freshness_reports = db.query(ObserverReport).filter(
        ObserverReport.site_id == selected_site_id,
        ObserverReport.rule_name == "FRESHNESS_CHECK"
    ).order_by(desc(ObserverReport.found_at)).limit(100).all()
    
    return templates.TemplateResponse("observer/freshness.html", {
        "request": request,
        "site": site,
        "stale_pages": stale_pages,
        "fresh_count": fresh_count,
        "stale_count": len(stale_pages),
        "freshness_days": freshness_days,
        "freshness_reports": freshness_reports,
        "current_page": "observer"
    })


@router.get("/freshness/{site_id}", response_class=HTMLResponse)
async def freshness_report_legacy(request: Request, site_id: int, db: Session = Depends(get_db)):
    """
    Freshness Raporu Sayfası (Eski endpoint - geriye dönük uyumluluk)
    Database'e kaydeder ve yeni endpoint'e yönlendirir
    """
    save_selected_site(db, site_id)
    response = RedirectResponse(url="/agents/observer/freshness", status_code=303)
    response.set_cookie(
        key="agents_selected_site_id",
        value=str(site_id),
        max_age=30 * 24 * 60 * 60,
        httponly=True,
        samesite="lax"
    )
    return response


# ============================================
# CONTROLLER DOĞRULAMALARI (Tamamlananlar)
# ============================================

@router.get("/api/controller-verifications")
async def get_controller_verifications(
    site_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """
    Controller doğrulamalarını getir
    Observer tarafından tamamlanan Controller task'larını listele
    """
    ensure_tables()

    # Controller task'larından Observer task ID'lerini al
    from agents.controller.models import ControllerTask, VerificationStatus

    query = db.query(ObserverTask).join(
        ControllerTask,
        ObserverTask.id == ControllerTask.observer_task_id
    )

    if site_id:
        query = query.filter(ObserverTask.site_id == site_id)

    if status:
        try:
            query = query.filter(ControllerTask.status == VerificationStatus[status])
        except KeyError:
            pass

    # Controller doğrulama görevlerini filtrele (description'da "Controller Doğrulaması" var)
    query = query.filter(ObserverTask.description.like('%Controller Doğrulaması%'))

    tasks = query.order_by(desc(ObserverTask.completed_at)).limit(limit).all()

    result = []
    for task in tasks:
        # Bu Observer task için Controller task'ı bul
        controller_task = db.query(ControllerTask).filter(
            ControllerTask.observer_task_id == task.id
        ).first()

        result.append({
            "id": task.id,
            "site_id": task.site_id,
            "task_type": task.task_type.value,
            "status": task.status.value,
            "description": task.description,
            "reports_count": task.reports_count,
            "progress_percentage": task.progress_percentage,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "controller_task": {
                "id": controller_task.id if controller_task else None,
                "status": controller_task.status.value if controller_task else None,
                "is_verified": controller_task.is_verified if controller_task else None,
                "page_url": controller_task.page_url if controller_task else None,
                "source_agent": controller_task.source_agent if controller_task else None,
                "task_type": controller_task.task_type if controller_task else None,
            } if controller_task else None
        })

    return {
        "status": "success",
        "tasks": result
    }

