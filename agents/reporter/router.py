# ============================================
# Reporter Agent - Router & Endpoints
# Tüm agent'ların görev hikayelerini gösterir
# ============================================

from fastapi import APIRouter, Request, Depends, Query, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc, or_
from datetime import datetime, timedelta
from typing import Optional, List
from pathlib import Path

from core.database import get_db, Site, Page
from agents.observer.models import ObserverTask, ObserverReport, TaskStatus as ObserverTaskStatus
from agents.reviewer.models import ReviewerQueue, QueueStatus
from agents.dispatcher.models import DispatcherTask, DispatcherTaskStatus
from agents.link_fixer.models import LinkFixTask, LinkFixTaskStatus
from agents.controller.models import ControllerTask, VerificationStatus
from agents.reporter.models import ReporterLog, init_reporter_tables
from agents.reporter.models import ReporterLog, init_reporter_tables
from fastapi import Body

# Template dizinleri
REPORTER_TEMPLATE_DIR = Path(__file__).parent / "templates"
MAIN_TEMPLATE_DIR = Path(__file__).parent.parent.parent / "templates"

templates = Jinja2Templates(directory=[str(REPORTER_TEMPLATE_DIR), str(MAIN_TEMPLATE_DIR)])

router = APIRouter(prefix="/agents/reporter", tags=["Reporter Agent"])

# Tabloları başlat
init_reporter_tables()


# ============================================
# DASHBOARD
# ============================================

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def reporter_dashboard(request: Request, db: Session = Depends(get_db)):
    """Reporter Agent - Parent-Child task görünümü ile tüm görevlerin hikayesini göster"""
    try:
        from agents.global_task.models import GlobalTask, GlobalTaskStatus
        
        # Parent task'ları al (parent_id NULL olanlar)
        parent_tasks_query = db.query(GlobalTask).filter(
            GlobalTask.parent_id == None
        ).order_by(desc(GlobalTask.created_at)).limit(50)
        
        parent_tasks_list = parent_tasks_query.all()

        # Her parent için child task'ları al
        parent_with_children = []
        for parent in parent_tasks_list:
            try:
                children = db.query(GlobalTask).filter(
                    GlobalTask.parent_id == parent.id
                ).order_by(desc(GlobalTask.created_at)).all()
                
                # Child task'ların durumlarını hesapla
                children_stats = {
                    "total": len(children),
                    "completed": len([c for c in children if c.status == GlobalTaskStatus.COMPLETED]),
                    "failed": len([c for c in children if c.status == GlobalTaskStatus.FAILED]),
                    "in_progress": len([c for c in children if c.status == GlobalTaskStatus.IN_PROGRESS]),
                    "pending": len([c for c in children if c.status == GlobalTaskStatus.PENDING])
                }
                
                parent_with_children.append({
                    "parent": parent,
                    "children": children,
                    "children_stats": children_stats
                })
            except Exception as e:
                print(f"⚠️ Parent {parent.id} için child task'lar alınırken hata: {e}")
                parent_with_children.append({
                    "parent": parent,
                    "children": [],
                    "children_stats": {"total": 0, "completed": 0, "failed": 0, "in_progress": 0, "pending": 0}
                })
        
        # İstatistikler (Parent task'lar için)
        total_parents = db.query(GlobalTask).filter(GlobalTask.parent_id == None).count()
        total_children = db.query(GlobalTask).filter(GlobalTask.parent_id != None).count()
        total_tasks = db.query(GlobalTask).count()

        return templates.TemplateResponse("reporter/dashboard.html", {
            "request": request,
            "current_page": "reporter",
            "parent_tasks": parent_with_children,
            "total_parents": total_parents,
            "total_children": total_children,
            "total_tasks": total_tasks
        })

    except Exception as e:
        import traceback
        error_msg = str(e)
        error_trace = traceback.format_exc()
        print(f"❌ Reporter dashboard hatası: {error_msg}")
        print(error_trace)
        print(f"   Error type: {type(e).__name__}")
        print(f"   Error args: {e.args}")

        from config import settings
        from fastapi.templating import Jinja2Templates
        main_templates = Jinja2Templates(directory=str(settings.TEMPLATES_DIR))

        try:
        return main_templates.TemplateResponse(
            "base.html",
            {
                "request": request,
                "current_page": None,
                "error": f"Dashboard yüklenirken hata oluştu: {error_msg}<br><pre>{error_trace}</pre>"
            },
            status_code=500
        )
        except Exception as template_error:
            print(f"❌ Error template render hatası: {template_error}")
            from fastapi.responses import HTMLResponse
            return HTMLResponse(
                content=f"<html><body><h1>Reporter Dashboard Hatası</h1><p>{error_msg}</p><pre>{error_trace}</pre></body></html>",
                status_code=500
            )


# ============================================
# GÖREV HİKAYESİ DETAY
# ============================================

@router.get("/story/{controller_task_id}", response_class=HTMLResponse)
async def story_detail(
    controller_task_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Bir görevin tüm hikayesini göster"""
    try:
        # Controller task'ı al
        controller_task = db.query(ControllerTask).filter(
            ControllerTask.id == controller_task_id
        ).first()

        if not controller_task:
            return templates.TemplateResponse("reporter/story_not_found.html", {
                "request": request,
                "current_page": "reporter"
            })

        # İlgili tüm kayıtları al
        timeline = build_story_timeline(db, controller_task)

        return templates.TemplateResponse("reporter/story_detail.html", {
            "request": request,
            "current_page": "reporter",
            "controller_task": controller_task,
            "timeline": timeline
        })

    except Exception as e:
        import traceback
        error_msg = str(e)
        error_trace = traceback.format_exc()
        print(f"❌ Story detail hatası: {error_msg}")
        print(error_trace)

        return templates.TemplateResponse(
            "base.html",
            {
                "request": request,
                "current_page": "reporter",
                "error": f"Hikaye yüklenirken hata oluştu: {error_msg}<br><pre>{error_trace}</pre>"
            },
            status_code=500
        )


def build_story_timeline(db: Session, controller_task: ControllerTask) -> list:
    """Görev hikayesi timeline'ını oluştur (global_task_id ile tüm işlemleri bul)"""
    timeline = []

    # GlobalTask ID varsa, tüm agent işlemlerini global_task_id ile bul
    global_task_id = controller_task.global_task_id
    if global_task_id:
        from agents.global_task.models import GlobalTask
        global_task = db.query(GlobalTask).filter(GlobalTask.id == global_task_id).first()
        if global_task:
            timeline.append({
                "step": 0,
                "agent": "GlobalTask",
                "action": "Görev Başlatıldı",
                "status": global_task.status.value,
                "timestamp": global_task.created_at,
                "details": {
                    "task_type": global_task.task_type,
                    "task_description": global_task.task_description,
                    "global_task_id": global_task.id,
                    "observer_task_id": global_task.observer_task_id,
                    "reviewer_queue_id": global_task.reviewer_queue_id,
                    "dispatcher_task_id": global_task.dispatcher_task_id,
                    "link_fix_task_id": global_task.link_fix_task_id,
                    "controller_task_id": global_task.controller_task_id
                }
            })

    # 0. Orijinal Observer Report (İlk Tespit) - global_task_id ile bul
    original_observer_report = None
    original_observer_task = None
    
    if global_task_id:
        # GlobalTask'tan observer_task_id'yi al
        from agents.global_task.models import GlobalTask
        global_task = db.query(GlobalTask).filter(GlobalTask.id == global_task_id).first()
        if global_task and global_task.observer_task_id:
            original_observer_task = db.query(ObserverTask).filter(
                ObserverTask.id == global_task.observer_task_id
            ).first()
            
            if original_observer_task:
                # Observer task'ın raporlarını al
                original_observer_reports = db.query(ObserverReport).filter(
                    ObserverReport.task_id == original_observer_task.id,
                    ObserverReport.global_task_id == global_task_id
                ).all()
                
                if original_observer_reports:
                    original_observer_report = original_observer_reports[0]  # İlk raporu al
    
    # Eğer global_task_id ile bulunamadıysa, eski yöntemle bul
    if not original_observer_report:
        if controller_task.original_issue and isinstance(controller_task.original_issue, dict):
            # original_issue'dan ObserverReport ID'sini bul
            original_report_id = controller_task.original_issue.get("observer_report_id")
            if original_report_id:
                original_observer_report = db.query(ObserverReport).filter(
                    ObserverReport.id == original_report_id
                ).first()
        
        # Eğer original_issue'da yoksa, Reviewer item üzerinden bul
        if not original_observer_report:
            reviewer_item = db.query(ReviewerQueue).filter(
                ReviewerQueue.page_url == controller_task.page_url,
                ReviewerQueue.rule_name.like(f"%{controller_task.task_type}%")
            ).first()
            
            if reviewer_item and reviewer_item.observer_report_id:
                original_observer_report = db.query(ObserverReport).filter(
                    ObserverReport.id == reviewer_item.observer_report_id
                ).first()
        
        # Orijinal Observer Report varsa, onun task'ını bul
        if original_observer_report:
            original_observer_task = db.query(ObserverTask).filter(
            ObserverTask.id == original_observer_report.task_id
        ).first()
        
        if original_observer_task:
            timeline.append({
                "step": 0,
                "agent": "Observer",
                "action": "İlk Hata Tespiti",
                "status": original_observer_task.status.value,
                "timestamp": original_observer_task.created_at,
                "details": {
                    "task_type": original_observer_task.task_type.value,
                    "description": original_observer_task.description,
                    "progress": f"{original_observer_task.progress_percentage}%",
                    "reports_count": original_observer_task.reports_count or 0
                }
            })
            
            # İlk Observer Report
            timeline.append({
                "step": "0a",
                "agent": "Observer",
                "action": "İlk Rapor Oluşturuldu",
                "status": "COMPLETED",
                "timestamp": original_observer_report.found_at or original_observer_task.created_at,
                "details": {
                    "rule_name": original_observer_report.rule_name,
                    "severity": original_observer_report.severity.value,
                    "message": original_observer_report.message,
                    "details": original_observer_report.details
                }
            })

    # 1. Observer - Doğrulama Görevi (eğer varsa - controller_task.observer_report'dan)
    if controller_task.observer_report and isinstance(controller_task.observer_report, dict):
        observer_task_id = controller_task.observer_report.get("observer_task_id")
        if observer_task_id:
            observer_task = db.query(ObserverTask).filter(
                ObserverTask.id == observer_task_id
            ).first()

            if observer_task:
                timeline.append({
                    "step": 1,
                    "agent": "Observer",
                    "action": "Doğrulama Taraması",
                    "status": observer_task.status.value,
                    "timestamp": observer_task.created_at,
                    "details": {
                        "task_type": observer_task.task_type.value,
                        "description": observer_task.description,
                        "progress": f"{observer_task.progress_percentage}%",
                        "reports_count": observer_task.reports_count or 0
                    }
                })

                # Observer Verification Reports
                observer_reports = db.query(ObserverReport).filter(
                    ObserverReport.task_id == observer_task_id
                ).all()

                if observer_reports:
                    timeline.append({
                        "step": "1a",
                        "agent": "Observer",
                        "action": "Doğrulama Raporları",
                        "status": "COMPLETED",
                        "timestamp": observer_task.completed_at or observer_task.created_at,
                        "details": {
                            "reports": [
                                {
                                    "rule_name": r.rule_name,
                                    "severity": r.severity.value,
                                    "message": r.message,
                                    "details": r.details
                                }
                                for r in observer_reports
                            ]
                        }
                    })

    # 2. Reviewer - Değerlendirme
    reviewer_item = None
    if controller_task.dispatcher_task_id:
        # Dispatcher task üzerinden Reviewer item'ı bul
        dispatcher_task = db.query(DispatcherTask).filter(
            DispatcherTask.id == controller_task.dispatcher_task_id
        ).first()
        
        if dispatcher_task and dispatcher_task.source_type == "REVIEWER_QUEUE" and dispatcher_task.source_id:
            reviewer_item = db.query(ReviewerQueue).filter(
                ReviewerQueue.id == dispatcher_task.source_id
            ).first()
    
    # Eğer dispatcher_task_id ile bulunamadıysa, page_url ve rule_name ile ara
    if not reviewer_item:
    reviewer_item = db.query(ReviewerQueue).filter(
        ReviewerQueue.page_url == controller_task.page_url,
        ReviewerQueue.rule_name.like(f"%{controller_task.task_type}%")
    ).first()

    if reviewer_item:
        timeline.append({
            "step": 2,
            "agent": "Reviewer",
            "action": "Önceliklendirme",
            "status": reviewer_item.status.value,
            "timestamp": reviewer_item.created_at,
            "details": {
                "priority_score": reviewer_item.priority_score,
                "severity": reviewer_item.severity,
                "action_plan": reviewer_item.action_plan,
                "action_type": reviewer_item.action_type,
                "observer_report_id": reviewer_item.observer_report_id
            }
        })

    # 3. Dispatcher - Görev Atama (global_task_id ile bul)
    dispatcher_task = None
    if global_task_id:
        # GlobalTask'tan dispatcher_task_id'yi al
        from agents.global_task.models import GlobalTask
        global_task = db.query(GlobalTask).filter(GlobalTask.id == global_task_id).first()
        if global_task and global_task.dispatcher_task_id:
            dispatcher_task = db.query(DispatcherTask).filter(
                DispatcherTask.id == global_task.dispatcher_task_id
            ).first()
    
    # Eğer global_task_id ile bulunamadıysa, eski yöntemle bul
    if not dispatcher_task:
        if controller_task.dispatcher_task_id:
            # Controller task'ın dispatcher_task_id'sini kullan
            dispatcher_task = db.query(DispatcherTask).filter(
                DispatcherTask.id == controller_task.dispatcher_task_id
            ).first()
        
        # Eğer dispatcher_task_id ile bulunamadıysa, page_url ve task_type ile ara
        if not dispatcher_task:
    dispatcher_task = db.query(DispatcherTask).filter(
        DispatcherTask.page_url == controller_task.page_url,
        DispatcherTask.task_type == controller_task.task_type
    ).first()

    if dispatcher_task:
        timeline.append({
            "step": 3,
            "agent": "Dispatcher",
            "action": "Görev Atama",
            "status": dispatcher_task.status.value,
            "timestamp": dispatcher_task.created_at,
            "details": {
                "assigned_agent": dispatcher_task.assigned_agent.value if dispatcher_task.assigned_agent else "N/A",
                "priority": dispatcher_task.priority,
                "task_description": dispatcher_task.task_description,
                "assigned_at": dispatcher_task.assigned_at,
                "agent_task_id": dispatcher_task.agent_task_id,
                "started_at": dispatcher_task.started_at,
                "completed_at": dispatcher_task.completed_at
            }
        })

    # 4. Link Fixer / AI Helper - Düzeltme
    if controller_task.source_agent == "FIXER":
        # GlobalTask'tan link_fix_task_id'yi al (önce)
        link_fix_task = None
        if global_task_id:
            from agents.global_task.models import GlobalTask
            global_task = db.query(GlobalTask).filter(GlobalTask.id == global_task_id).first()
            if global_task and global_task.link_fix_task_id:
                link_fix_task = db.query(LinkFixTask).filter(
                    LinkFixTask.id == global_task.link_fix_task_id
                ).first()
        
        # Eğer global_task_id ile bulunamadıysa, dispatcher_task'ın agent_task_id'sini kullan
        if not link_fix_task:
            if dispatcher_task and dispatcher_task.agent_task_id:
                link_fix_task = db.query(LinkFixTask).filter(
                    LinkFixTask.id == dispatcher_task.agent_task_id
                ).first()
            
            # Eğer agent_task_id ile bulunamadıysa, page_url ile ara
            if not link_fix_task:
        link_fix_task = db.query(LinkFixTask).filter(
            LinkFixTask.page_url == controller_task.page_url
        ).order_by(desc(LinkFixTask.created_at)).first()

        if link_fix_task:
            timeline.append({
                "step": 4,
                "agent": "Link Fixer",
                "action": "Link Düzeltme",
                "status": link_fix_task.status.value,
                "timestamp": link_fix_task.created_at,
                "details": {
                    "old_url": link_fix_task.old_url,
                    "new_url": link_fix_task.new_url,
                    "started_at": link_fix_task.started_at,
                    "completed_at": link_fix_task.completed_at,
                    "result": link_fix_task.result,
                    "error_message": link_fix_task.error_message,
                    "wp_post_id": link_fix_task.wp_post_id,
                    "wp_post_type": link_fix_task.wp_post_type
                }
            })
    
    elif controller_task.source_agent == "AI_HELPER":
        # AI Helper görevleri
        if dispatcher_task and dispatcher_task.agent_task_id:
            # AI Helper opportunity'yi bul
            from agents.ai_helper.models import AIHelperOpportunity
            ai_helper_opportunity = db.query(AIHelperOpportunity).filter(
                AIHelperOpportunity.id == dispatcher_task.agent_task_id
            ).first()
            
            if ai_helper_opportunity:
                timeline.append({
                    "step": 4,
                    "agent": "AI Helper",
                    "action": "Internal Linking Analizi",
                    "status": ai_helper_opportunity.status,
                    "timestamp": ai_helper_opportunity.created_at,
                    "details": {
                        "source_url": ai_helper_opportunity.source_url,
                        "target_url": ai_helper_opportunity.target_url,
                        "target_keyword": ai_helper_opportunity.target_keyword,
                        "confidence_score": ai_helper_opportunity.confidence_score,
                        "internal_link_status": ai_helper_opportunity.internal_link_status,
                        "html_snippet": ai_helper_opportunity.html_snippet,
                        "paragraph_index": ai_helper_opportunity.paragraph_index
                    }
                })
                
                # AI Helper Proposal'ları
                from agents.ai_helper.models import AIHelperProposal
                proposals = db.query(AIHelperProposal).filter(
                    AIHelperProposal.opportunity_id == ai_helper_opportunity.id
                ).order_by(desc(AIHelperProposal.created_at)).all()
                
                if proposals:
                    timeline.append({
                        "step": "4a",
                        "agent": "AI Helper",
                        "action": "Proposal Oluşturuldu",
                        "status": "COMPLETED",
                        "timestamp": proposals[0].created_at,
                        "details": {
                            "proposals_count": len(proposals),
                            "latest_proposal": {
                                "original_snippet": proposals[0].original_snippet,
                                "proposed_snippet": proposals[0].proposed_snippet,
                                "ai_confidence_score": proposals[0].ai_confidence_score
                            }
                }
            })

    # 5. Controller - Görev Kaydı (Agent'tan Bildirim Alındı)
    timeline.append({
        "step": 5,
        "agent": "Controller",
        "action": "Görev Bildirimi Alındı",
        "status": controller_task.status.value,
        "timestamp": controller_task.created_at,
        "details": {
            "task_type": controller_task.task_type,
            "task_description": controller_task.task_description,
            "source_agent": controller_task.source_agent,
            "source_task_id": controller_task.source_task_id,
            "agent_report": controller_task.agent_report,
            "agent_completion_time": controller_task.agent_completion_time,
            "retry_count": controller_task.retry_count
        }
    })

    # 6. Controller - Doğrulama Başlatıldı
    if controller_task.verification_started_at:
        timeline.append({
            "step": 6,
            "agent": "Controller",
            "action": "Doğrulama Başlatıldı",
            "status": "VERIFYING",
            "timestamp": controller_task.verification_started_at,
            "details": {
                "observer_task_id": controller_task.observer_task_id
            }
        })

    # 7. Observer - Doğrulama Taraması (eğer observer_task_id varsa ve step 1'de eklenmediyse)
    if controller_task.observer_task_id:
        # Step 1'de zaten eklenmiş mi kontrol et
        already_added = any(
            item.get("step") == 1 and item.get("agent") == "Observer" 
            for item in timeline
        )
        
        if not already_added:
        verification_task = db.query(ObserverTask).filter(
            ObserverTask.id == controller_task.observer_task_id
        ).first()

        if verification_task:
            timeline.append({
                    "step": 7,
                "agent": "Observer",
                "action": "Doğrulama Taraması",
                "status": verification_task.status.value,
                "timestamp": verification_task.created_at,
                "details": {
                    "description": verification_task.description,
                    "progress": f"{verification_task.progress_percentage}%",
                    "completed_at": verification_task.completed_at
                }
            })

                # Observer Verification Reports (eğer step 1a'da eklenmediyse)
            verification_reports = db.query(ObserverReport).filter(
                ObserverReport.task_id == controller_task.observer_task_id
            ).all()

            if verification_reports:
                    already_added_reports = any(
                        item.get("step") == "1a" and item.get("agent") == "Observer"
                        for item in timeline
                    )
                    
                    if not already_added_reports:
                timeline.append({
                            "step": "7a",
                    "agent": "Observer",
                    "action": "Doğrulama Sonucu",
                    "status": "COMPLETED",
                    "timestamp": verification_task.completed_at or verification_task.created_at,
                    "details": {
                        "reports_count": len(verification_reports),
                        "has_errors": any(r.severity.value in ["ERROR", "WARNING"] for r in verification_reports),
                        "reports": [
                            {
                                "rule_name": r.rule_name,
                                "severity": r.severity.value,
                                        "message": r.message,
                                        "details": r.details
                            }
                            for r in verification_reports
                        ]
                    }
                })

    # 8. Controller - Final Doğrulama
    if controller_task.verification_completed_at:
    timeline.append({
            "step": 8,
        "agent": "Controller",
        "action": "Final Doğrulama",
        "status": controller_task.status.value,
            "timestamp": controller_task.verification_completed_at,
        "details": {
            "is_verified": controller_task.is_verified,
            "verification_notes": controller_task.verification_notes,
            "retry_count": controller_task.retry_count,
                "observer_report": controller_task.observer_report,
                "observer_verification_time": controller_task.observer_verification_time
        }
    })

    # 9. Retry (varsa)
    if controller_task.retry_count > 0:
        retry_dispatcher_task = db.query(DispatcherTask).filter(
            DispatcherTask.source_type == "CONTROLLER_RETRY",
            DispatcherTask.source_id == controller_task.id
        ).order_by(desc(DispatcherTask.created_at)).first()

        if retry_dispatcher_task:
            timeline.append({
                "step": 9,
                "agent": "Dispatcher",
                "action": f"Retry #{controller_task.retry_count}",
                "status": retry_dispatcher_task.status.value,
                "timestamp": retry_dispatcher_task.created_at,
                "details": {
                    "retry_count": controller_task.retry_count,
                    "assigned_agent": retry_dispatcher_task.assigned_agent.value if retry_dispatcher_task.assigned_agent else "N/A",
                    "task_description": retry_dispatcher_task.task_description,
                    "priority": retry_dispatcher_task.priority,
                    "agent_task_id": retry_dispatcher_task.agent_task_id
                }
            })
            
            # Retry Link Fixer task'ı (eğer varsa)
            if retry_dispatcher_task.assigned_agent and retry_dispatcher_task.assigned_agent.value == "FIXER" and retry_dispatcher_task.agent_task_id:
                retry_link_fix_task = db.query(LinkFixTask).filter(
                    LinkFixTask.id == retry_dispatcher_task.agent_task_id
                ).first()
                
                if retry_link_fix_task:
                    timeline.append({
                        "step": "9a",
                        "agent": "Link Fixer",
                        "action": f"Retry #{controller_task.retry_count} - Link Düzeltme",
                        "status": retry_link_fix_task.status.value,
                        "timestamp": retry_link_fix_task.created_at,
                        "details": {
                            "old_url": retry_link_fix_task.old_url,
                            "new_url": retry_link_fix_task.new_url,
                            "started_at": retry_link_fix_task.started_at,
                            "completed_at": retry_link_fix_task.completed_at,
                            "result": retry_link_fix_task.result,
                            "error_message": retry_link_fix_task.error_message
                        }
                    })

    # 10. Task History (Controller task'ın tüm olayları)
    if controller_task.task_history:
        import json
        task_history = controller_task.task_history
        if isinstance(task_history, str):
            try:
                task_history = json.loads(task_history)
            except:
                task_history = []
        
        if isinstance(task_history, list) and len(task_history) > 0:
            for history_item in task_history:
                if isinstance(history_item, dict):
                    event_type = history_item.get("event_type", "")
                    message = history_item.get("message", "")
                    timestamp_str = history_item.get("timestamp", "")
                    data = history_item.get("data", {})
                    
                    # Timestamp'i parse et
                    try:
                        if timestamp_str:
                            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                        else:
                            timestamp = controller_task.created_at
                    except:
                        timestamp = controller_task.created_at
                    
                    # Timeline'da zaten var mı kontrol et (duplicate önleme)
                    # Sadece önemli event'leri ekle
                    important_events = [
                        "TASK_CREATED", "AGENT_COMPLETION", "VERIFICATION_STARTED",
                        "OBSERVER_TASK_CREATED", "VERIFICATION_SUCCESS", "VERIFICATION_FAILED",
                        "RETRY_ASSIGNED", "VERIFICATION_ERROR"
                    ]
                    
                    if event_type in important_events:
                        timeline.append({
                            "step": f"history_{event_type}",
                            "agent": "Controller",
                            "action": event_type.replace("_", " ").title(),
                            "status": "INFO",
                            "timestamp": timestamp,
                            "details": {
                                "message": message,
                                "data": data
                }
            })

    # Tarihe göre sırala
    timeline.sort(key=lambda x: x["timestamp"] if x["timestamp"] else datetime.min)

    return timeline


# ============================================
# API: Görev Ara
# ============================================

@router.get("/api/search")
async def search_stories(
    query: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    agent: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """Görevleri ara"""
    query_filter = db.query(ControllerTask)

    if query:
        query_filter = query_filter.filter(
            or_(
                ControllerTask.page_url.like(f"%{query}%"),
                ControllerTask.task_description.like(f"%{query}%"),
                ControllerTask.task_type.like(f"%{query}%")
            )
        )

    if status:
        try:
            query_filter = query_filter.filter(
                ControllerTask.status == VerificationStatus[status]
            )
        except KeyError:
            pass

    if agent:
        query_filter = query_filter.filter(ControllerTask.source_agent == agent)

    stories = query_filter.order_by(
        desc(ControllerTask.created_at)
    ).limit(limit).all()

    return {
        "status": "success",
        "stories": [
            {
                "id": story.id,
                "page_url": story.page_url,
                "task_type": story.task_type,
                "status": story.status.value,
                "source_agent": story.source_agent,
                "is_verified": story.is_verified,
                "retry_count": story.retry_count,
                "created_at": story.created_at.isoformat() if story.created_at else None,
                "completed_at": story.verification_completed_at.isoformat() if story.verification_completed_at else None
            }
            for story in stories
        ]
    }


# ============================================
# LOG ENDPOINTS
# ============================================

@router.get("/api/logs")
async def get_logs(
    level: Optional[str] = Query(None),
    source_agent: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    since_minutes: int = Query(60, ge=1, le=1440),
    db: Session = Depends(get_db)
):
    """Canlı logları getir - Task ID'ye göre gruplandırılmış"""
    try:
        since = datetime.utcnow() - timedelta(minutes=since_minutes)
        
        query = db.query(ReporterLog).filter(
            ReporterLog.created_at >= since
        )
        
        if level and level.upper() != "ALL":
            query = query.filter(ReporterLog.log_level == level.upper())
        
        if source_agent and source_agent.upper() != "ALL":
            query = query.filter(ReporterLog.source_agent == source_agent.upper())
        
        # En eski en üstte, en yeni en altta (asc sıralama)
        logs = query.order_by(asc(ReporterLog.created_at)).limit(limit).all()
        
        # Logları global_task_id'ye göre grupla
        from collections import defaultdict
        logs_by_task = defaultdict(list)
        logs_without_task = []
        
        for log in logs:
            log_data = {
                "id": log.id,
                "level": log.log_level,
                "source_agent": log.source_agent,
                "target_agent": log.target_agent,
                "message": log.message,
                "details": log.details_json or {},
                "created_at": log.created_at.isoformat() if log.created_at else None,
                "global_task_id": log.global_task_id
            }
            
            if log.global_task_id:
                logs_by_task[log.global_task_id].append(log_data)
            else:
                logs_without_task.append(log_data)
        
        # Her task için ilk log'un zamanını al (grup başlığı için)
        task_groups = []
        for task_id, task_logs in logs_by_task.items():
            # Task bilgilerini al
            from agents.global_task.models import GlobalTask
            global_task = db.query(GlobalTask).filter(GlobalTask.id == task_id).first()
            
            task_groups.append({
                "task_id": task_id,
                "task_type": global_task.task_type if global_task else None,
                "task_description": global_task.task_description if global_task else None,
                "task_status": global_task.status.value if global_task and hasattr(global_task.status, 'value') else str(global_task.status) if global_task else None,
                "logs": task_logs,
                "first_log_time": task_logs[0]["created_at"] if task_logs else None,
                "log_count": len(task_logs)
            })
        
        # Task gruplarını ilk log zamanına göre sırala (en eski en üstte)
        task_groups.sort(key=lambda x: x["first_log_time"] or "")
        
        # Task ID'si olmayan loglar için grup oluştur
        if logs_without_task:
            task_groups.append({
                "task_id": None,
                "task_type": None,
                "task_description": "Task ID Yok",
                "task_status": None,
                "logs": logs_without_task,
                "first_log_time": logs_without_task[0]["created_at"] if logs_without_task else None,
                "log_count": len(logs_without_task)
            })
        
        return JSONResponse({
            "status": "success",
            "task_groups": task_groups,
            "logs": [log for group in task_groups for log in group["logs"]],  # Backward compatibility
            "count": len(logs)
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "status": "error",
            "message": str(e)
        }, status_code=500)


@router.delete("/api/logs/{log_id}")
async def delete_log(log_id: int, db: Session = Depends(get_db)):
    """Tek bir log'u sil"""
    try:
        log = db.query(ReporterLog).filter(ReporterLog.id == log_id).first()
        if not log:
            return JSONResponse({
                "status": "error",
                "message": "Log bulunamadı"
            }, status_code=404)
        
        db.delete(log)
        db.commit()
        
        return JSONResponse({
            "status": "success",
            "message": "Log silindi"
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({
            "status": "error",
            "message": str(e)
        }, status_code=500)


@router.delete("/api/logs/clear-all")
async def clear_all_logs(db: Session = Depends(get_db)):
    """TÜM logları sil - Veritabanındaki tüm reporter_logs kayıtlarını siler"""
    try:
        # Tüm logları say
        total_count = db.query(ReporterLog).count()
        
        # Tüm logları sil
        deleted_count = db.query(ReporterLog).delete()
        db.commit()
        
        return JSONResponse({
            "status": "success",
            "message": f"Tüm loglar başarıyla silindi",
            "deleted_count": deleted_count,
            "total_count": total_count
        })
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "status": "error",
            "message": str(e)
        }, status_code=500)


@router.delete("/api/logs")
async def delete_logs(
    log_ids: List[int] = Body(...),
    db: Session = Depends(get_db)
):
    """Birden fazla log'u sil"""
    try:
        deleted_count = db.query(ReporterLog).filter(
            ReporterLog.id.in_(log_ids)
        ).delete(synchronize_session=False)
        
        db.commit()
        
        return JSONResponse({
            "status": "success",
            "message": f"{deleted_count} log silindi",
            "deleted_count": deleted_count
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({
            "status": "error",
            "message": str(e)
        }, status_code=500)


@router.post("/api/logs/add")
async def add_log(
    level: str = Body(...),
    source_agent: str = Body(...),
    message: str = Body(...),
    target_agent: Optional[str] = Body(None),
    details: Optional[dict] = Body(None),
    controller_task_id: Optional[int] = Body(None),
    dispatcher_task_id: Optional[int] = Body(None),
    link_fix_task_id: Optional[int] = Body(None),
    observer_task_id: Optional[int] = Body(None),
    db: Session = Depends(get_db)
):
    """Yeni log ekle (diğer agentlar kullanacak)"""
    try:
        log = ReporterLog(
            log_level=level.upper(),
            source_agent=source_agent.upper(),
            target_agent=target_agent.upper() if target_agent else None,
            message=message,
            details_json=details,
            controller_task_id=controller_task_id,
            dispatcher_task_id=dispatcher_task_id,
            link_fix_task_id=link_fix_task_id,
            observer_task_id=observer_task_id
        )
        
        db.add(log)
        db.commit()
        db.refresh(log)
        
        return JSONResponse({
            "status": "success",
            "log_id": log.id,
            "message": "Log eklendi"
        })
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "status": "error",
            "message": str(e)
        }, status_code=500)
