# ============================================
# Link Fixer Agent - Router & Endpoints
# ============================================

from fastapi import APIRouter, Request, Depends, HTTPException, BackgroundTasks, Query, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc
from datetime import datetime
from typing import Optional, List
from pathlib import Path

from core.database import get_db, Site, Page
from agents.dispatcher.models import DispatcherTask, DispatcherTaskStatus
from .models import (
    LinkFixTask, LinkFixTaskStatus,
    init_link_fixer_tables
)
from .wordpress_fixer import WordPressAPILinkFixer

# Template dizinleri
LINK_FIXER_TEMPLATE_DIR = Path(__file__).parent / "templates"
MAIN_TEMPLATE_DIR = Path(__file__).parent.parent.parent / "templates"

templates = Jinja2Templates(directory=[str(LINK_FIXER_TEMPLATE_DIR), str(MAIN_TEMPLATE_DIR)])

router = APIRouter(prefix="/agents/link-fixer", tags=["Link Fixer Agent"])

# Tablo oluşturma (ilk çalıştırmada)
_tables_initialized = False


def ensure_tables():
    """Tabloların oluşturulduğundan emin ol"""
    global _tables_initialized
    if not _tables_initialized:
        init_link_fixer_tables()
        _tables_initialized = True


# ============================================
# DASHBOARD
# ============================================

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def link_fixer_dashboard(request: Request, db: Session = Depends(get_db)):
    """Link Fixer Agent - Dashboard"""
    try:
        ensure_tables()
        
        # İstatistikler
        total_pending = db.query(LinkFixTask).filter(
            LinkFixTask.status == LinkFixTaskStatus.PENDING
        ).count()
        
        total_in_progress = db.query(LinkFixTask).filter(
            LinkFixTask.status == LinkFixTaskStatus.IN_PROGRESS
        ).count()
        
        total_completed = db.query(LinkFixTask).filter(
            LinkFixTask.status == LinkFixTaskStatus.COMPLETED
        ).count()
        
        total_failed = db.query(LinkFixTask).filter(
            LinkFixTask.status == LinkFixTaskStatus.FAILED
        ).count()
        
        # Bekleyen görevler - DispatcherTask ve ObserverReport bilgileriyle birlikte
        try:
            # Önce tüm görevleri say (debug için)
            all_tasks_count = db.query(LinkFixTask).count()
            pending_tasks_count = db.query(LinkFixTask).filter(
                LinkFixTask.status == LinkFixTaskStatus.PENDING
            ).count()
            in_progress_count = db.query(LinkFixTask).filter(
                LinkFixTask.status == LinkFixTaskStatus.IN_PROGRESS
            ).count()
            completed_count = db.query(LinkFixTask).filter(
                LinkFixTask.status == LinkFixTaskStatus.COMPLETED
            ).count()
            failed_count = db.query(LinkFixTask).filter(
                LinkFixTask.status == LinkFixTaskStatus.FAILED
            ).count()
            
            print(f"📊 Link Fixer Dashboard: Toplam {all_tasks_count} görev")
            print(f"   - PENDING: {pending_tasks_count}")
            print(f"   - IN_PROGRESS: {in_progress_count}")
            print(f"   - COMPLETED: {completed_count}")
            print(f"   - FAILED: {failed_count}")
            
            # Tüm görevleri listele (debug için)
            all_tasks = db.query(LinkFixTask).order_by(asc(LinkFixTask.created_at)).limit(50).all()
            print(f"📋 Link Fixer Dashboard: Son 50 görev:")
            for t in all_tasks:
                print(f"   - ID: {t.id}, Status: {t.status.value}, Page URL: {t.page_url[:50] if t.page_url else 'None'}...")
            
            pending_tasks_query = db.query(LinkFixTask).filter(
                LinkFixTask.status == LinkFixTaskStatus.PENDING
            ).order_by(asc(LinkFixTask.created_at)).limit(20)
            
            pending_tasks_raw = pending_tasks_query.all()
            print(f"📋 Link Fixer Dashboard: {len(pending_tasks_raw)} bekleyen görev bulundu (query sonucu)")
            
            pending_tasks_with_details = []
            for task in pending_tasks_raw:
                print(f"  - Görev ID: {task.id}, Page URL: {task.page_url}, Old URL: {task.old_url}, New URL: {task.new_url}")
                task_description = None
                error_message = None
                
                try:
                    # DispatcherTask'ı bul (agent_task_id ile)
                    dispatcher_task = db.query(DispatcherTask).filter(
                        DispatcherTask.agent_task_id == task.id
                    ).first()
                    
                    if dispatcher_task:
                        task_description = dispatcher_task.task_description or None
                        
                        # ObserverReport'u bul
                        if dispatcher_task.task_params:
                            observer_report_id = dispatcher_task.task_params.get("observer_report_id")
                            
                            if observer_report_id:
                                try:
                                    from agents.observer.models import ObserverReport
                                    observer_report = db.query(ObserverReport).filter(
                                        ObserverReport.id == observer_report_id
                                    ).first()
                                    
                                    if observer_report:
                                        error_message = observer_report.message
                                except Exception as e:
                                    print(f"⚠️ ObserverReport sorgusu hatası: {e}")
                    
                    # Eğer DispatcherTask bulunamadıysa, ReviewerQueue üzerinden ara
                    if not dispatcher_task or not task_description:
                        try:
                            from agents.reviewer.models import ReviewerQueue
                            # LinkFixTask ile aynı page_url'e sahip reviewer item'ı bul
                            reviewer_item = db.query(ReviewerQueue).filter(
                                ReviewerQueue.page_url == task.page_url,
                                ReviewerQueue.observer_report_id.isnot(None)
                            ).first()
                            
                            if reviewer_item:
                                if reviewer_item.observer_report_id:
                                    from agents.observer.models import ObserverReport
                                    observer_report = db.query(ObserverReport).filter(
                                        ObserverReport.id == reviewer_item.observer_report_id
                                    ).first()
                                    
                                    if observer_report:
                                        error_message = observer_report.message
                                        if reviewer_item.action_plan:
                                            task_description = reviewer_item.action_plan
                        except Exception as e:
                            print(f"⚠️ ReviewerQueue sorgusu hatası: {e}")
                
                except Exception as e:
                    print(f"⚠️ Task detay çekme hatası (task_id={task.id}): {e}")
                    import traceback
                    traceback.print_exc()
                
                # Task bilgilerini dictionary olarak ekle
                created_at_str = None
                if task.created_at:
                    try:
                        created_at_str = task.created_at.strftime('%d.%m.%Y %H:%M')
                    except:
                        created_at_str = str(task.created_at)
                
                task_dict = {
                    "id": task.id,
                    "site_id": task.site_id,
                    "page_id": task.page_id,
                    "page_url": task.page_url or "",
                    "old_url": task.old_url or "",
                    "new_url": task.new_url or "",
                    "link_id": task.link_id,
                    "status": task.status,
                    "created_at": task.created_at,  # Template'de kullanılacak
                    "created_at_str": created_at_str,  # Formatlanmış string
                    "task_description": task_description,
                    "error_message": error_message
                }
                
                pending_tasks_with_details.append(task_dict)
        except Exception as e:
            print(f"❌ Bekleyen görevler sorgusu hatası: {e}")
            import traceback
            traceback.print_exc()
            pending_tasks_with_details = []
        
        # İşlenmekte olanlar
        in_progress_tasks = db.query(LinkFixTask).filter(
            LinkFixTask.status == LinkFixTaskStatus.IN_PROGRESS
        ).order_by(asc(LinkFixTask.started_at)).limit(10).all()
        
        # Son tamamlananlar
        completed_tasks = db.query(LinkFixTask).filter(
            LinkFixTask.status == LinkFixTaskStatus.COMPLETED
        ).order_by(desc(LinkFixTask.completed_at)).limit(10).all()
        
        # Son başarısızlar
        failed_tasks = db.query(LinkFixTask).filter(
            LinkFixTask.status == LinkFixTaskStatus.FAILED
        ).order_by(desc(LinkFixTask.completed_at)).limit(10).all()
        
        return templates.TemplateResponse("link_fixer/dashboard.html", {
            "request": request,
            "current_page": "link_fixer",
            "total_pending": total_pending,
            "total_in_progress": total_in_progress,
            "total_completed": total_completed,
            "total_failed": total_failed,
            "pending_tasks": pending_tasks_with_details,
            "in_progress_tasks": in_progress_tasks,
            "completed_tasks": completed_tasks,
            "failed_tasks": failed_tasks
        })
    
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_trace = traceback.format_exc()
        print(f"❌ Link Fixer dashboard hatası: {error_msg}")
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

@router.post("/api/fix-link")
async def fix_link(
    page_url: str = Body(...),
    old_url: str = Body(...),
    new_url: str = Body(...),
    site_id: int = Body(...),
    page_id: Optional[int] = Body(None),
    link_id: Optional[int] = Body(None),
    dry_run: bool = Body(False),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None
):
    """Link düzeltme görevi oluştur ve çalıştır"""
    ensure_tables()
    
    try:
        # Site kontrolü
        site = db.query(Site).filter(Site.id == site_id).first()
        if not site:
            return JSONResponse(
                status_code=404,
                content={"status": "error", "message": "Site bulunamadı"}
            )
        
        # WordPress API bilgileri kontrolü
        if not site.wp_api_url or not site.wp_api_username or not site.wp_api_password:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "WordPress REST API bilgileri eksik"}
            )
        
        # Görev oluştur
        task = LinkFixTask(
            site_id=site_id,
            page_id=page_id,
            page_url=page_url,
            old_url=old_url,
            new_url=new_url,
            link_id=link_id,
            status=LinkFixTaskStatus.PENDING,
            created_at=datetime.utcnow()
        )
        
        db.add(task)
        db.commit()
        db.refresh(task)
        
        # Arka planda çalıştır
        if not dry_run:
            background_tasks.add_task(
                execute_link_fix,
                task_id=task.id,
                site_id=site_id
            )
        
        return {
            "status": "success",
            "message": "Görev oluşturuldu" + (" (dry run)" if dry_run else ""),
            "task_id": task.id
        }
    
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ Link düzeltme görevi oluşturma hatası: {e}")
        print(error_trace)
        db.rollback()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )


async def execute_link_fix(task_id: int, site_id: int):
    """Link düzeltme görevini çalıştır"""
    from core.database import SessionLocal
    
    db = SessionLocal()
    try:
        ensure_tables()
        
        task = db.query(LinkFixTask).filter(LinkFixTask.id == task_id).first()
        if not task:
            print(f"❌ Görev bulunamadı: {task_id}")
            return
        
        site = db.query(Site).filter(Site.id == site_id).first()
        if not site:
            task.status = LinkFixTaskStatus.FAILED
            task.error_message = "Site bulunamadı"
            db.commit()
            return
        
        # Görev durumunu güncelle
        task.status = LinkFixTaskStatus.IN_PROGRESS
        task.started_at = datetime.utcnow()
        db.commit()
        
        # WordPress API fixer oluştur
        fixer = WordPressAPILinkFixer(
            wp_url=site.wp_api_url,
            wp_username=site.wp_api_username,
            wp_password=site.wp_api_password
        )
        
        # Log listesi
        logs = []
        logs.append({"message": f"🔄 WordPress bağlantısı kontrol ediliyor...", "type": "info"})
        
        # URL'den post ID bul
        post_result = await fixer.get_post_by_url(task.page_url, logs=logs)
        if not post_result:
            task.status = LinkFixTaskStatus.FAILED
            task.error_message = "WordPress'te sayfa bulunamadı"
            task.logs = "\n".join([f"[{log.get('type', 'info')}] {log.get('message', '')}" for log in logs])
            task.completed_at = datetime.utcnow()
            db.commit()
            return
        
        post_id, post_type = post_result
        task.wp_post_id = post_id
        task.wp_post_type = post_type
        
        # Linki düzelt
        print(f"🔧 Link Fixer: Link düzeltme işlemi başlatılıyor...")
        print(f"   Post ID: {post_id}, Post Type: {post_type}")
        print(f"   Old URL: {task.old_url}")
        print(f"   New URL: {task.new_url}")
        
        result = await fixer.fix_link_in_elementor(
            post_id=post_id,
            old_url=task.old_url,
            new_url=task.new_url,
            post_type=post_type,
            dry_run=False,
            logs=logs
        )
        
        # Sonuçları logla
        print(f"\n{'='*60}")
        print(f"📊 LINK DÜZELTME SONUCU")
        print(f"{'='*60}")
        print(f"✅ Başarılı: {result.get('success', False)}")
        print(f"📝 Mesaj: {result.get('message', 'N/A')}")
        print(f"🔢 Değiştirilen Link Sayısı: {result.get('changes_count', 0)}")
        if result.get('success'):
            print(f"✅ İŞLEM BAŞARILI!")
        else:
            print(f"❌ İŞLEM BAŞARISIZ!")
            print(f"⚠️ Hata: {result.get('message', 'Bilinmeyen hata')}")
        print(f"{'='*60}\n")
        
        # Sonuçları kaydet
        if result.get("success"):
            task.status = LinkFixTaskStatus.COMPLETED
            task.result = result
            
            # Eğer link zaten değiştirilmişse özel mesaj
            if result.get("already_fixed", False):
                print(f"✅ Link Fix Task durumu: COMPLETED (Link zaten değiştirilmiş)")
                print(f"   📝 Mesaj: {result.get('message', 'Link zaten değiştirilmiş')}")
            else:
                print(f"✅ Link Fix Task durumu: COMPLETED")
        else:
            task.status = LinkFixTaskStatus.FAILED
            task.error_message = result.get("message", "Bilinmeyen hata")
            task.result = result
            print(f"❌ Link Fix Task durumu: FAILED")
            print(f"   Hata mesajı: {task.error_message}")

        task.logs = "\n".join([f"[{log.get('type', 'info')}] {log.get('message', '')}" for log in logs])
        task.completed_at = datetime.utcnow()
        db.commit()
        print(f"💾 Link Fix Task veritabanına kaydedildi (ID: {task.id})")

        # ✅ Controller'a tamamlanma bildirimi gönder
        if task.status == LinkFixTaskStatus.COMPLETED:
            try:
                from agents.controller.worker import receive_completion_notification

                # Dispatcher task ID'yi bul (task_params'tan)
                dispatcher_task_id = None
                if hasattr(task, 'dispatcher_task_id'):
                    dispatcher_task_id = task.dispatcher_task_id

                # Reporter log ekle (Controller'a bildirim öncesi)
                try:
                    from agents.reporter import add_reporter_log
                    
                    # Mesajı already_fixed durumuna göre ayarla
                    already_fixed = result.get("already_fixed", False)
                    if already_fixed:
                        log_message = f"Link zaten değiştirilmiş: {task.old_url} -> {task.new_url} (manuel değişiklik veya önceki işlem)"
                        log_level = "INFO"
                    else:
                        log_message = f"Link düzeltme tamamlandı: {task.old_url} -> {task.new_url}"
                        log_level = "SUCCESS"
                    
                    add_reporter_log(
                        db=db,
                        level=log_level,
                        source_agent="FIXER",
                        target_agent="CONTROLLER",
                        message=log_message,
                        details={
                            "link_fix_task_id": task.id,
                            "old_url": task.old_url,
                            "new_url": task.new_url,
                            "status": task.status.value,
                            "result": task.result,
                            "wp_post_id": task.wp_post_id,
                            "wp_post_type": task.wp_post_type,
                            "already_fixed": already_fixed  # Özel flag
                        },
                        link_fix_task_id=task.id,
                        dispatcher_task_id=dispatcher_task_id,
                        global_task_id=task.global_task_id
                    )
                except Exception as log_error:
                    print(f"⚠️ Reporter log ekleme hatası: {log_error}")
                
                # Controller'a bildir (global_task_id'yi de aktar)
                already_fixed = result.get("already_fixed", False)
                task_description = f"Link düzeltme: {task.old_url} -> {task.new_url}"
                if already_fixed:
                    task_description = f"Link zaten değiştirilmiş: {task.old_url} -> {task.new_url} (manuel değişiklik veya önceki işlem)"
                
                receive_completion_notification(
                    db=db,
                    source_agent="FIXER",
                    source_task_id=task.id,
                    site_id=task.site_id,
                    page_id=task.page_id,
                    page_url=task.page_url,
                    task_type="FIX_LINK",
                    task_description=task_description,
                    agent_report={
                        "status": "completed",
                        "old_url": task.old_url,
                        "new_url": task.new_url,
                        "wp_post_id": task.wp_post_id,
                        "wp_post_type": task.wp_post_type,
                        "result": task.result,
                        "logs": logs,
                        "already_fixed": already_fixed  # Özel flag: Observer'a bildirilecek
                    },
                    dispatcher_task_id=dispatcher_task_id,
                    original_issue={"type": "broken_link", "url": task.old_url},
                    global_task_id=task.global_task_id  # LinkFixTask'tan global_task_id'yi aktar
                )
                print(f"✅ Link Fixer: Controller'a bildirim gönderildi (Task ID: {task.id})")
            except Exception as notify_error:
                print(f"⚠️ Link Fixer: Controller'a bildirim gönderilemedi: {notify_error}")
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ Link düzeltme hatası: {e}")
        print(error_trace)
        
        if task:
            task.status = LinkFixTaskStatus.FAILED
            task.error_message = str(e)
            task.completed_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


@router.get("/api/tasks")
async def get_tasks(
    status: Optional[str] = Query(None),
    site_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """Görevleri listele"""
    ensure_tables()
    
    query = db.query(LinkFixTask)
    
    if status:
        try:
            query = query.filter(LinkFixTask.status == LinkFixTaskStatus[status])
        except KeyError:
            pass
    
    if site_id:
        query = query.filter(LinkFixTask.site_id == site_id)
    
    tasks = query.order_by(desc(LinkFixTask.created_at)).limit(limit).all()
    
    return {
        "status": "success",
        "tasks": [
            {
                "id": task.id,
                "site_id": task.site_id,
                "page_url": task.page_url,
                "old_url": task.old_url,
                "new_url": task.new_url,
                "status": task.status.value,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None
            }
            for task in tasks
        ]
    }


@router.get("/api/tasks/{task_id}")
async def get_task_detail(
    task_id: int,
    db: Session = Depends(get_db)
):
    """Görev detayını getir"""
    ensure_tables()
    
    task = db.query(LinkFixTask).filter(LinkFixTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Görev bulunamadı")
    
    return {
        "status": "success",
        "task": {
            "id": task.id,
            "site_id": task.site_id,
            "page_url": task.page_url,
            "old_url": task.old_url,
            "new_url": task.new_url,
            "status": task.status.value,
            "wp_post_id": task.wp_post_id,
            "wp_post_type": task.wp_post_type,
            "result": task.result,
            "error_message": task.error_message,
            "logs": task.logs,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None
        }
    }


@router.post("/api/process-dispatcher-task")
async def process_dispatcher_task(
    dispatcher_task_id: int = Body(...),
    db: Session = Depends(get_db)
):
    """Dispatcher'dan gelen görevi işle"""
    ensure_tables()
    
    dispatcher_task = db.query(DispatcherTask).filter(
        DispatcherTask.id == dispatcher_task_id
    ).first()
    
    if not dispatcher_task:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": "Dispatcher görevi bulunamadı"}
        )
    
    # Task params'dan bilgileri al
    task_params = dispatcher_task.task_params or {}
    page_url = task_params.get("page_url") or dispatcher_task.page_url
    old_url = task_params.get("old_url")
    new_url = task_params.get("new_url")
    
    if not page_url or not old_url or not new_url:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Eksik parametreler: page_url, old_url, new_url gerekli"}
        )
    
    # Link fix task oluştur
    task = LinkFixTask(
        site_id=dispatcher_task.site_id,
        page_id=dispatcher_task.page_id,
        page_url=page_url,
        old_url=old_url,
        new_url=new_url,
        status=LinkFixTaskStatus.PENDING,
        created_at=datetime.utcnow()
    )
    
    db.add(task)
    db.commit()
    db.refresh(task)
    
    # Dispatcher task'ı güncelle
    dispatcher_task.status = DispatcherTaskStatus.IN_PROGRESS
    dispatcher_task.started_at = datetime.utcnow()
    dispatcher_task.agent_task_id = task.id
    db.commit()
    
    return {
        "status": "success",
        "message": "Görev oluşturuldu",
        "task_id": task.id
    }


@router.post("/api/tasks/{task_id}/start-fix")
async def start_fix_task(
    task_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Link düzeltme görevini başlat"""
    ensure_tables()
    
    task = db.query(LinkFixTask).filter(LinkFixTask.id == task_id).first()
    if not task:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": "Görev bulunamadı"}
        )
    
    if task.status != LinkFixTaskStatus.PENDING:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": f"Görev zaten {task.status.value} durumunda"}
        )
    
    # Site kontrolü
    site = db.query(Site).filter(Site.id == task.site_id).first()
    if not site:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": "Site bulunamadı"}
        )
    
    # WordPress API bilgileri kontrolü
    if not site.wp_api_url or not site.wp_api_username or not site.wp_api_password:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "WordPress REST API bilgileri eksik"}
        )
    
    # Arka planda düzeltmeyi başlat
    background_tasks.add_task(
        execute_link_fix,
        task_id=task.id,
        site_id=task.site_id
    )
    
    return {
        "status": "success",
        "message": "Düzeltme başlatıldı",
        "task_id": task.id
    }


