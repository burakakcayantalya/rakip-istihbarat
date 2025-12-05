# ============================================
# Dispatcher Agent - Worker Functions
# ============================================

from sqlalchemy.orm import Session
from datetime import datetime
from .models import (
    DispatcherTask, DispatcherTaskStatus, AgentType,
    get_agent_for_task
)


def assign_task_to_agent(db: Session, task_id: int) -> dict:
    """
    Görevi uygun agent'a ata ve agent'ın görev sistemine ekle
    
    Args:
        db: Database session
        task_id: Dispatcher task ID
    
    Returns:
        {"status": "success", "agent_task_id": int, "agent": str}
    """
    task = db.query(DispatcherTask).filter(DispatcherTask.id == task_id).first()
    if not task:
        raise ValueError("Görev bulunamadı")
    
    if task.status != DispatcherTaskStatus.PENDING:
        raise ValueError("Sadece bekleyen görevler atanabilir")
    
    # Agent'a göre görev oluştur
    # Observer, Reviewer, Analyzer kendi görevlerini kendileri yönetir
    agent_task_id = None
    
    if task.assigned_agent == AgentType.FIXER:
        # Link Fixer agent'a görev oluştur
        agent_task_id = create_link_fixer_task(db, task)
    elif task.assigned_agent == AgentType.AI_HELPER:
        # AI Helper agent'a görev oluştur
        agent_task_id = create_ai_helper_task(db, task)
    else:
        raise ValueError(f"Desteklenmeyen agent tipi: {task.assigned_agent.value}")
    
    # Görev durumunu güncelle
    task.status = DispatcherTaskStatus.ASSIGNED
    task.assigned_at = datetime.utcnow()
    task.agent_task_id = agent_task_id
    db.commit()
    
    print(f"🎯 Dispatcher Task {task.id} -> {task.assigned_agent.value} agent'ına atandı (Agent Task ID: {agent_task_id})")
    
    # Reporter log ekle
    try:
        from agents.reporter import add_reporter_log
        add_reporter_log(
            db=db,
            level="INFO",
            source_agent="DISPATCHER",
            target_agent=task.assigned_agent.value,
            message=f"Görev atandı: {task.task_type} -> {task.assigned_agent.value}",
            details={
                "task_id": task.id,
                "task_type": task.task_type,
                "agent_task_id": agent_task_id,
                "page_url": task.page_url
            },
            dispatcher_task_id=task.id
        )
    except Exception as log_error:
        print(f"⚠️ Reporter log ekleme hatası: {log_error}")
    
    return {
        "status": "success",
        "message": f"Görev {task.assigned_agent.value} agent'ına atandı",
        "agent": task.assigned_agent.value,
        "agent_task_id": agent_task_id
    }


def create_link_fixer_task(db: Session, dispatcher_task: DispatcherTask) -> int:
    """
    Link Fixer agent için görev oluştur
    Eğer new_url yoksa veya old_url ile aynıysa, sitemap'ten alternatif URL bulur
    
    Returns:
        Link Fixer task ID
    """
    from agents.link_fixer.models import LinkFixTask, LinkFixTaskStatus
    from agents.link_fixer.sitemap_manager import find_alternative_url
    
    # Task params'dan bilgileri al
    task_params = dispatcher_task.task_params or {}
    page_url = task_params.get("page_url") or dispatcher_task.page_url
    old_url = task_params.get("old_url")
    new_url = task_params.get("new_url")
    
    # Eğer old_url yoksa, Observer report'tan tekrar almaya çalış
    if not old_url and task_params.get("observer_report_id"):
        from agents.observer.models import ObserverReport
        import json
        
        observer_report = db.query(ObserverReport).filter(
            ObserverReport.id == task_params.get("observer_report_id")
        ).first()
        
        if observer_report and observer_report.details:
            try:
                if isinstance(observer_report.details, str):
                    details = json.loads(observer_report.details)
                else:
                    details = observer_report.details
                
                # Link bilgilerini details'ten al - tüm olası field'ları kontrol et
                old_url = (
                    details.get("old_url") or 
                    details.get("redirecting_url") or 
                    details.get("url") or 
                    details.get("broken_url") or
                    details.get("link_url") or
                    details.get("href") or
                    details.get("source_url")
                )
                if not new_url:
                    new_url = (
                        details.get("new_url") or 
                        details.get("final_url") or 
                        details.get("target_url") or
                        details.get("redirect_url") or
                        details.get("destination_url")
                    )
                
                # Eğer hala old_url yoksa, message'dan çıkarmaya çalış
                if not old_url and observer_report.message:
                    import re
                    # "Kırık link: URL -> HTTP" formatından URL çıkar
                    url_patterns = [
                        r'Kırık link:\s*(https?://[^\s->]+)',  # "Kırık link: URL ->"
                        r'Redirect:\s*(https?://[^\s->]+)',     # "Redirect: URL ->"
                        r'(https?://[^\s<>"{}|\\^`\[\]]+)',    # Genel URL pattern
                    ]
                    for pattern in url_patterns:
                        match = re.search(pattern, observer_report.message)
                        if match:
                            old_url = match.group(1)
                            print(f"🔍 Message'dan URL çıkarıldı: {old_url}")
                            break
                
                print(f"🔍 Observer report'tan bilgiler alındı: old_url={old_url}, new_url={new_url}, details_keys={list(details.keys()) if details else []}")
            except Exception as e:
                print(f"⚠️ Observer report details parse hatası: {e}")
    
    # Eğer hala old_url yoksa, Reviewer item'dan almaya çalış
    if not old_url and dispatcher_task.source_type == "REVIEWER_QUEUE" and dispatcher_task.source_id:
        from agents.reviewer.models import ReviewerQueue
        
        reviewer_item = db.query(ReviewerQueue).filter(
            ReviewerQueue.id == dispatcher_task.source_id
        ).first()
        
        if reviewer_item and reviewer_item.observer_report_id:
            from agents.observer.models import ObserverReport
            import json
            
            observer_report = db.query(ObserverReport).filter(
                ObserverReport.id == reviewer_item.observer_report_id
            ).first()
            
            if observer_report and observer_report.details:
                try:
                    if isinstance(observer_report.details, str):
                        details = json.loads(observer_report.details)
                    else:
                        details = observer_report.details
                    
                    # Link bilgilerini details'ten al - tüm olası field'ları kontrol et
                    old_url = (
                        details.get("old_url") or 
                        details.get("redirecting_url") or 
                        details.get("url") or 
                        details.get("broken_url") or
                        details.get("link_url") or
                        details.get("href") or
                        details.get("source_url")
                    )
                    if not new_url:
                        new_url = (
                            details.get("new_url") or 
                            details.get("final_url") or 
                            details.get("target_url") or
                            details.get("redirect_url") or
                            details.get("destination_url")
                        )
                    
                    # Eğer hala old_url yoksa, message'dan çıkarmaya çalış
                    if not old_url and observer_report.message:
                        import re
                        # "Kırık link: URL -> HTTP" formatından URL çıkar
                        url_patterns = [
                            r'Kırık link:\s*(https?://[^\s->]+)',  # "Kırık link: URL ->"
                            r'Redirect:\s*(https?://[^\s->]+)',     # "Redirect: URL ->"
                            r'(https?://[^\s<>"{}|\\^`\[\]]+)',    # Genel URL pattern
                        ]
                        for pattern in url_patterns:
                            match = re.search(pattern, observer_report.message)
                            if match:
                                old_url = match.group(1)
                                print(f"🔍 Message'dan URL çıkarıldı: {old_url}")
                                break
                    
                    print(f"🔍 Reviewer item üzerinden Observer report'tan bilgiler alındı: old_url={old_url}, new_url={new_url}, details_keys={list(details.keys()) if details else []}")
                except Exception as e:
                    print(f"⚠️ Observer report details parse hatası: {e}")
    
    # Eğer hala old_url yoksa ve CONTROLLER_RETRY ise, Controller task'tan al
    if not old_url and dispatcher_task.source_type == "CONTROLLER_RETRY" and dispatcher_task.source_id:
        from agents.controller.models import ControllerTask
        import json
        
        controller_task = db.query(ControllerTask).filter(
            ControllerTask.id == dispatcher_task.source_id
        ).first()
        
        if controller_task:
            print(f"🔍 Controller retry: Controller task'tan bilgiler alınıyor (ControllerTask ID: {controller_task.id})")
            
            # Önce agent_report'tan al (Link Fixer'dan gelen bilgiler)
            if controller_task.agent_report:
                if isinstance(controller_task.agent_report, dict):
                    old_url = controller_task.agent_report.get("old_url")
                    new_url = controller_task.agent_report.get("new_url")
                    print(f"🔍 Controller retry: agent_report'tan alındı - old_url={old_url}, new_url={new_url}")
            
            # Eğer agent_report'ta yoksa, original_issue'dan al (Observer'dan gelen bilgiler)
            if not old_url and controller_task.original_issue:
                if isinstance(controller_task.original_issue, dict):
                    old_url = (
                        controller_task.original_issue.get("old_url") or
                        controller_task.original_issue.get("url") or
                        controller_task.original_issue.get("redirecting_url") or
                        controller_task.original_issue.get("broken_url") or
                        controller_task.original_issue.get("link_url") or
                        controller_task.original_issue.get("source_url")
                    )
                    new_url = (
                        controller_task.original_issue.get("new_url") or
                        controller_task.original_issue.get("final_url") or
                        controller_task.original_issue.get("target_url") or
                        controller_task.original_issue.get("redirect_url") or
                        controller_task.original_issue.get("destination_url")
                    )
                    print(f"🔍 Controller retry: original_issue'dan alındı - old_url={old_url}, new_url={new_url}")
            
            # Eğer hala yoksa, observer_report'tan al
            if not old_url and controller_task.observer_report:
                if isinstance(controller_task.observer_report, dict):
                    # Observer report'ta details içinde olabilir
                    error_reports = controller_task.observer_report.get("error_reports", [])
                    if error_reports and isinstance(error_reports, list) and len(error_reports) > 0:
                        # İlk error report'tan al
                        first_error = error_reports[0]
                        if isinstance(first_error, dict):
                            old_url = (
                                first_error.get("old_url") or
                                first_error.get("url") or
                                first_error.get("redirecting_url") or
                                first_error.get("broken_url")
                            )
                            new_url = (
                                first_error.get("new_url") or
                                first_error.get("final_url") or
                                first_error.get("target_url")
                            )
                            print(f"🔍 Controller retry: observer_report error_reports'tan alındı - old_url={old_url}, new_url={new_url}")
            
            # Eğer hala yoksa, Link Fixer task'tan al (orijinal görevden)
            if not old_url and controller_task.source_task_id:
                from agents.link_fixer.models import LinkFixTask
                original_link_task = db.query(LinkFixTask).filter(
                    LinkFixTask.id == controller_task.source_task_id
                ).first()
                
                if original_link_task:
                    old_url = original_link_task.old_url
                    new_url = original_link_task.new_url
                    print(f"🔍 Controller retry: Orijinal LinkFixTask'tan alındı - old_url={old_url}, new_url={new_url}")
    
    # Eğer hala page_url veya old_url yoksa, hata ver
    if not page_url:
        raise ValueError(f"Link düzeltme için page_url gerekli (DispatcherTask ID: {dispatcher_task.id})")
    
    if not old_url:
        # Görevi FAILED olarak işaretle
        dispatcher_task.status = DispatcherTaskStatus.FAILED
        dispatcher_task.error_message = f"Link düzeltme için old_url gerekli ancak bulunamadı. Task params: {task_params}"
        db.commit()
        
        # Reporter log ekle - detaylı bilgi ile
        try:
            from agents.reporter import add_reporter_log
            
            # Observer report bilgilerini topla
            observer_info = {}
            if task_params.get("observer_report_id"):
                from agents.observer.models import ObserverReport
                observer_report = db.query(ObserverReport).filter(
                    ObserverReport.id == task_params.get("observer_report_id")
                ).first()
                if observer_report:
                    observer_info = {
                        "observer_report_id": observer_report.id,
                        "rule_name": observer_report.rule_name,
                        "message": observer_report.message,
                        "details_keys": list(observer_report.details.keys()) if observer_report.details and isinstance(observer_report.details, dict) else [],
                        "details_sample": str(observer_report.details)[:500] if observer_report.details else None
                    }
            
            # Reviewer item bilgilerini topla
            reviewer_info = {}
            if dispatcher_task.source_type == "REVIEWER_QUEUE" and dispatcher_task.source_id:
                from agents.reviewer.models import ReviewerQueue
                reviewer_item = db.query(ReviewerQueue).filter(
                    ReviewerQueue.id == dispatcher_task.source_id
                ).first()
                if reviewer_item:
                    reviewer_info = {
                        "reviewer_item_id": reviewer_item.id,
                        "observer_report_id": reviewer_item.observer_report_id,
                        "rule_name": reviewer_item.rule_name,
                        "action_plan": reviewer_item.action_plan
                    }
            
            add_reporter_log(
                db=db,
                level="ERROR",
                source_agent="DISPATCHER",
                target_agent="FIXER",
                message=f"Link Fixer görevi oluşturulamadı: old_url bulunamadı (Task: {dispatcher_task.task_type})",
                details={
                    "dispatcher_task_id": dispatcher_task.id,
                    "task_type": dispatcher_task.task_type,
                    "page_url": page_url,
                    "task_params_keys": list(task_params.keys()) if task_params else [],
                    "task_params_sample": str(task_params)[:500] if task_params else None,
                    "source_type": dispatcher_task.source_type,
                    "source_id": dispatcher_task.source_id,
                    "observer_info": observer_info,
                    "reviewer_info": reviewer_info
                },
                dispatcher_task_id=dispatcher_task.id
            )
        except Exception as log_error:
            print(f"⚠️ Reporter log ekleme hatası: {log_error}")
            import traceback
            traceback.print_exc()
        
        raise ValueError(f"Link düzeltme için old_url gerekli ancak bulunamadı (DispatcherTask ID: {dispatcher_task.id}, Task Type: {dispatcher_task.task_type}, Source: {dispatcher_task.source_type})")
    
    # Eğer new_url yoksa veya old_url ile aynıysa, alternatif URL bul
    if not new_url or new_url == old_url:
        print(f"🔍 Alternatif URL aranıyor: {old_url}")
        alternative_url = find_alternative_url(old_url, dispatcher_task.site_id, db)
        
        if alternative_url and alternative_url != old_url:
            new_url = alternative_url
            print(f"✅ Alternatif URL bulundu: {old_url} -> {new_url}")
        else:
            # Alternatif bulunamadıysa, ana sayfaya yönlendir
            from core.database import Site
            site = db.query(Site).filter(Site.id == dispatcher_task.site_id).first()
            if site:
                domain = site.domain if not site.domain.startswith('http') else site.domain
                if not domain.startswith('http'):
                    domain = f"https://{domain}"
                new_url = domain
                print(f"⚠️ Alternatif URL bulunamadı, ana sayfaya yönlendiriliyor: {new_url}")
            else:
                raise ValueError("Site bulunamadı ve alternatif URL bulunamadı")
    
    # Link fix task oluştur
    link_fix_task = LinkFixTask(
        global_task_id=dispatcher_task.global_task_id,  # DispatcherTask'tan global_task_id'yi al
        site_id=dispatcher_task.site_id,
        page_id=dispatcher_task.page_id,
        page_url=page_url,
        old_url=old_url,
        new_url=new_url,
        status=LinkFixTaskStatus.PENDING
    )
    
    db.add(link_fix_task)
    db.flush()  # ID'yi almak için flush
    
    # GlobalTask'a link_fix_task_id'yi ekle
    if dispatcher_task.global_task_id:
        try:
            from agents.global_task.worker import update_global_task_agent_id
            update_global_task_agent_id(
                db=db,
                global_task_id=dispatcher_task.global_task_id,
                agent_name="FIXER",
                agent_task_id=link_fix_task.id
            )
        except Exception as e:
            print(f"⚠️ GlobalTask güncelleme hatası: {e}")
    
    db.commit()
    db.refresh(link_fix_task)
    
    print(f"✅ LinkFixTask oluşturuldu: ID={link_fix_task.id}, Page URL={page_url}, Old URL={old_url}, New URL={new_url}, Status={link_fix_task.status.value} [GlobalTask ID: {dispatcher_task.global_task_id}]")
    
    return link_fix_task.id


def create_ai_helper_task(db: Session, dispatcher_task: DispatcherTask) -> int:
    """
    AI Helper agent için görev oluştur
    Duplicate link analizi ve internal linking optimizasyonu için
    
    Returns:
        AI Helper task ID (opportunity ID veya log ID)
    """
    from agents.ai_helper.models import AIHelperProject, AIHelperOpportunity, add_log
    
    # Task params'dan bilgileri al
    task_params = dispatcher_task.task_params or {}
    page_url = task_params.get("page_url") or dispatcher_task.page_url
    duplicate_url = task_params.get("duplicate_url") or task_params.get("url")
    paragraph_indexes = task_params.get("paragraph_indexes", [])
    
    if not page_url:
        raise ValueError("AI Helper görevi için page_url gerekli")
    
    # Site için AI Helper projesi bul veya oluştur
    project = db.query(AIHelperProject).filter(
        AIHelperProject.site_id == dispatcher_task.site_id,
        AIHelperProject.status == "active"
    ).first()
    
    if not project:
        # Proje yoksa oluştur
        project = AIHelperProject(
            site_id=dispatcher_task.site_id,
            project_name=f"Site {dispatcher_task.site_id}",
            status="active"
        )
        db.add(project)
        db.commit()
        db.refresh(project)
    
    # Duplicate link için bir opportunity oluştur
    # Bu opportunity, AI Helper'ın analiz edeceği bir görev olacak
    opportunity = AIHelperOpportunity(
        project_id=project.id,
        source_url=page_url,
        target_url=duplicate_url or page_url,  # Duplicate link URL'i
        status="IN_POOL",
        confidence_score=100.0,  # Duplicate link tespiti %100 doğru
        internal_link_status="MISSING",  # Duplicate link problemi var
        html_snippet=None,  # AI Helper analiz edecek
        original_paragraph=task_params.get("message", "Duplicate link tespit edildi"),
        paragraph_index=paragraph_indexes[0] if paragraph_indexes else None
    )
    
    db.add(opportunity)
    db.commit()
    db.refresh(opportunity)
    
    # Log ekle
    add_log(
        project.id,
        "INFO",
        "DISPATCHER",
        f"Duplicate link görevi alındı: {page_url}",
        {
            "dispatcher_task_id": dispatcher_task.id,
            "page_url": page_url,
            "duplicate_url": duplicate_url,
            "opportunity_id": opportunity.id
        },
        db
    )
    
    return opportunity.id


def create_task_from_reviewer_item(db: Session, reviewer_item) -> DispatcherTask:
    """
    Reviewer queue item'ından Dispatcher task oluştur
    Child GlobalTask ID'sini kullanır (eğer varsa)
    """
    """
    Reviewer queue öğesinden Dispatcher task oluştur
    - Link düzeltme görevleri (301, 404, 410, redirect, broken) -> Link Fixer
    - Duplicate link görevleri -> AI Helper
    
    Args:
        db: Database session
        reviewer_item: ReviewerQueue öğesi
    
    Returns:
        Oluşturulan DispatcherTask veya None (eğer desteklenmeyen görev tipiyse)
    """
    # Önce eski enum değerlerini temizle
    try:
        from .models import AgentRoutingRule
        old_rules = db.query(AgentRoutingRule).all()
        for old_rule in old_rules:
            try:
                agent_value = old_rule.agent_type.value if hasattr(old_rule.agent_type, 'value') else str(old_rule.agent_type)
                if agent_value not in ['FIXER', 'AI_HELPER', 'UNKNOWN']:
                    old_rule.agent_type = AgentType.FIXER
            except (AttributeError, ValueError):
                # Enum hatası varsa FIXER'a çevir
                try:
                    old_rule.agent_type = AgentType.FIXER
                except:
                    pass
        db.commit()
    except Exception as cleanup_error:
        db.rollback()
        # Temizleme hatası önemli değil, devam et
    
    # Action type'a göre task type belirle
    action_type = reviewer_item.action_type or ""
    rule_name = reviewer_item.rule_name or ""
    
    print(f"🔍 create_task_from_reviewer_item: Action Type='{action_type}', Rule Name='{rule_name}'")
    
    # Link düzeltme görevleri -> Link Fixer
    link_fix_task_types = {
        "FIX_LINK": "FIX_LINK",
        "FIX_301_LINK": "FIX_301_LINK",
        "FIX_404_LINK": "FIX_404_LINK",
        "FIX_410_LINK": "FIX_410_LINK",
        "FIX_REDIRECT_LINK": "FIX_REDIRECT_LINK",
        "FIX_BROKEN_LINK": "FIX_BROKEN_LINK",
        "CHECK_LINK": "FIX_LINK",  # CHECK_LINK de FIX_LINK olarak işlenecek (kontrol + düzeltme)
    }
    
    # Duplicate link görevleri -> AI Helper
    duplicate_link_task_types = {
        "REMOVE_DUPLICATE_LINKS": "ANALYZE_DUPLICATE_LINKS",
        "REVIEW_DUPLICATE_LINKS": "ANALYZE_DUPLICATE_LINKS",
    }
    
    # Önce duplicate link kontrolü yap
    if rule_name == "DUPLICATE_LINK_CHECK" or action_type in duplicate_link_task_types:
        task_type = duplicate_link_task_types.get(action_type, "ANALYZE_DUPLICATE_LINKS")
        print(f"  → Duplicate link görevi tespit edildi: task_type={task_type}")
        try:
            assigned_agent = get_agent_for_task(task_type, db)
        except (AttributeError, ValueError) as e:
            # Enum hatası varsa default olarak AI_HELPER kullan
            assigned_agent = AgentType.AI_HELPER
            print(f"  → Enum hatası, default AI_HELPER kullanılıyor: {e}")
        
        if assigned_agent != AgentType.AI_HELPER:
            print(f"  → Agent AI_HELPER değil, None döndürülüyor: {assigned_agent}")
            return None
    else:
        # Link düzeltme görevleri
        task_type = link_fix_task_types.get(action_type)
        
        # Eğer link düzeltme görevi değilse, Dispatcher'a gönderme
        if not task_type:
            print(f"  → Link düzeltme görevi değil veya action_type eşleşmedi: action_type='{action_type}', task_type={task_type}")
            print(f"  → Mevcut link_fix_task_types: {list(link_fix_task_types.keys())}")
            return None
        
        print(f"  → Link düzeltme görevi tespit edildi: task_type={task_type}")
        try:
            assigned_agent = get_agent_for_task(task_type, db)
        except (AttributeError, ValueError) as e:
            # Enum hatası varsa default olarak FIXER kullan
            assigned_agent = AgentType.FIXER
            print(f"  → Enum hatası, default FIXER kullanılıyor: {e}")
        
        if assigned_agent != AgentType.FIXER:
            print(f"  → Agent FIXER değil, None döndürülüyor: {assigned_agent}")
            return None
    
    print(f"  → Görev oluşturulacak: task_type={task_type}, assigned_agent={assigned_agent}")
    
    # Observer report'tan bilgileri al
    old_url = None
    new_url = None
    duplicate_url = None
    paragraph_indexes = []
    
    report_message = None
    if reviewer_item.observer_report_id:
        from agents.observer.models import ObserverReport
        report = db.query(ObserverReport).filter(
            ObserverReport.id == reviewer_item.observer_report_id
        ).first()
        
        if report and report.details:
            import json
            if isinstance(report.details, str):
                try:
                    details = json.loads(report.details)
                except:
                    details = {}
            else:
                details = report.details
            
            # Link bilgilerini details'ten al
            if assigned_agent == AgentType.FIXER:
                # Link düzeltme için - tüm olası alanları kontrol et
                # Observer report'ta "url" field'ı var, bu old_url olarak kullanılmalı
                # CHECK_LINK görevleri için de url field'ı old_url olarak kullanılır
                old_url = (
                    details.get("old_url") or 
                    details.get("url") or  # Observer report'ta bu field var (CHECK_LINK için önemli!)
                    details.get("redirecting_url") or 
                    details.get("broken_url") or
                    details.get("source_url") or
                    details.get("link_url") or
                    details.get("href")
                )
                new_url = (
                    details.get("new_url") or 
                    details.get("final_url") or  # Observer report'ta bu field var (redirect için)
                    details.get("target_url") or
                    details.get("redirect_url") or
                    details.get("destination_url")
                )
                
                # CHECK_LINK görevleri için: Eğer redirect varsa, final_url'i new_url olarak kullan
                if action_type == "CHECK_LINK" and not new_url:
                    if details.get("is_redirect") and details.get("final_url"):
                        new_url = details.get("final_url")
                        print(f"🔍 CHECK_LINK: Redirect tespit edildi, final_url kullanılıyor: {new_url}")
                
                # Eğer hala old_url yoksa, message'dan çıkarmaya çalış
                if not old_url and report.message:
                    import re
                    # "Kırık link: URL -> HTTP" veya "Redirect link: URL -> FINAL_URL" formatından URL çıkar
                    url_patterns = [
                        r'Kırık link:\s*(https?://[^\s->]+)',      # "Kırık link: URL ->"
                        r'Redirect link:\s*(https?://[^\s->]+)',  # "Redirect link: URL ->"
                        r'(https?://[^\s<>"{}|\\^`\[\]]+)',       # Genel URL pattern
                    ]
                    for pattern in url_patterns:
                        match = re.search(pattern, report.message)
                        if match:
                            old_url = match.group(1)
                            print(f"🔍 Observer report message'dan URL çıkarıldı: {old_url}")
                            break
                
                print(f"🔍 create_task_from_reviewer_item: old_url={old_url}, new_url={new_url}, action_type={action_type}, details_keys={list(details.keys()) if details else []}")
            elif assigned_agent == AgentType.AI_HELPER:
                # Duplicate link için
                duplicate_url = details.get("url")
                paragraph_indexes = details.get("paragraph_indexes", [])
                paragraph_count = details.get("paragraph_count", 0)
            
            # Rapor mesajını al
            report_message = report.message
            
            # Eğer old_url hala yoksa, mesajdan URL çıkarmaya çalış
            if assigned_agent == AgentType.FIXER and not old_url and report_message:
                import re
                # URL pattern'leri dene
                url_patterns = [
                    r'https?://[^\s<>"{}|\\^`\[\]]+',  # Standart URL
                    r'www\.[^\s<>"{}|\\^`\[\]]+',     # www ile başlayan
                ]
                for pattern in url_patterns:
                    matches = re.findall(pattern, report_message)
                    if matches:
                        old_url = matches[0]
                        if not old_url.startswith('http'):
                            old_url = f"https://{old_url}"
                        print(f"🔍 Mesajdan URL çıkarıldı: {old_url}")
                        break
    
    # Dispatcher task oluştur
    task_params = {
        "reviewer_item_id": reviewer_item.id,
        "observer_report_id": reviewer_item.observer_report_id,
        "rule_name": reviewer_item.rule_name,
        "severity": reviewer_item.severity,
    }
    
    if assigned_agent == AgentType.FIXER:
        task_params.update({
            "old_url": old_url,
            "new_url": new_url,
        })
    elif assigned_agent == AgentType.AI_HELPER:
        task_params.update({
            "duplicate_url": duplicate_url,
            "paragraph_indexes": paragraph_indexes,
            "message": report_message or reviewer_item.action_plan or f"Duplicate link tespit edildi: {duplicate_url}",
        })
    
    task = DispatcherTask(
        global_task_id=reviewer_item.global_task_id,  # ReviewerQueue'dan global_task_id'yi al
        task_name=f"{reviewer_item.rule_name} - {reviewer_item.severity}",
        task_type=task_type,
        task_description=reviewer_item.action_plan,
        site_id=reviewer_item.site_id,
        page_id=reviewer_item.page_id,
        page_url=reviewer_item.page_url,
        priority=reviewer_item.priority_score,  # Reviewer'dan gelen öncelik
        source_type="REVIEWER_QUEUE",
        source_id=reviewer_item.id,
        assigned_agent=assigned_agent,
        status=DispatcherTaskStatus.PENDING,
        task_params=task_params,
        created_at=datetime.utcnow()
    )
    
    db.add(task)
    db.flush()  # ID'yi almak için flush
    
    # GlobalTask'a dispatcher_task_id'yi ekle
    if reviewer_item.global_task_id:
        try:
            from agents.global_task.worker import update_global_task_agent_id
            update_global_task_agent_id(
                db=db,
                global_task_id=reviewer_item.global_task_id,
                agent_name="DISPATCHER",
                agent_task_id=task.id
            )
        except Exception as e:
            print(f"⚠️ GlobalTask güncelleme hatası: {e}")
    
    # Reporter log ekle
    try:
        from agents.reporter import add_reporter_log
        add_reporter_log(
            db=db,
            level="INFO",
            source_agent="REVIEWER",
            target_agent=assigned_agent.value if assigned_agent else "UNKNOWN",
            message=f"Görev Dispatcher'a gönderildi: {task_type}",
            details={
                "reviewer_item_id": reviewer_item.id,
                "dispatcher_task_id": task.id,
                "task_type": task_type,
                "assigned_agent": assigned_agent.value if assigned_agent else None,
                "priority": reviewer_item.priority_score,
                "rule_name": reviewer_item.rule_name
            },
            dispatcher_task_id=task.id
        )
    except Exception as log_error:
        print(f"⚠️ Reporter log ekleme hatası: {log_error}")
    
    return task

