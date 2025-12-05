# ============================================
# Controller Agent - Worker Functions
# ============================================
# Tamamlanan görevleri doğrular

from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional, Dict, Any
import json
import asyncio
import threading

from .models import (
    ControllerTask, VerificationStatus, ControllerStats
)
from core.database import SessionLocal


def receive_completion_notification(
    db: Session,
    source_agent: str,
    source_task_id: int,
    site_id: int,
    page_id: Optional[int],
    page_url: str,
    task_type: str,
    task_description: str,
    agent_report: dict,
    dispatcher_task_id: Optional[int] = None,
    original_issue: Optional[dict] = None,
    global_task_id: Optional[int] = None
) -> ControllerTask:
    """
    Agent'tan tamamlanma bildirimi al

    Args:
        source_agent: Hangi agent'tan geldi (FIXER, AI_HELPER)
        source_task_id: Agent'ın task ID'si
        site_id: Site ID
        page_id: Page ID
        page_url: Sayfa URL'i
        task_type: Görev tipi
        task_description: Görev açıklaması
        agent_report: Agent'ın raporladığı sonuç
        dispatcher_task_id: Dispatcher task ID (opsiyonel)
        original_issue: Orijinal sorun (Observer'dan gelen)

    Returns:
        ControllerTask
    """
    # Zaten kayıt var mı kontrol et
    existing_task = db.query(ControllerTask).filter(
        ControllerTask.source_agent == source_agent,
        ControllerTask.source_task_id == source_task_id
    ).first()

    if existing_task:
        print(f"⚠️ Controller: Bu görev zaten kayıtlı (ID: {existing_task.id})")
        return existing_task

    # GlobalTask ID'yi bul (eğer verilmemişse, source_task_id'den al)
    if not global_task_id and source_agent == "FIXER":
        from agents.link_fixer.models import LinkFixTask
        link_fix_task = db.query(LinkFixTask).filter(LinkFixTask.id == source_task_id).first()
        if link_fix_task:
            global_task_id = link_fix_task.global_task_id
    elif not global_task_id and dispatcher_task_id:
        from agents.dispatcher.models import DispatcherTask
        dispatcher_task = db.query(DispatcherTask).filter(DispatcherTask.id == dispatcher_task_id).first()
        if dispatcher_task:
            global_task_id = dispatcher_task.global_task_id

    # Yeni Controller task oluştur
    controller_task = ControllerTask(
        global_task_id=global_task_id,  # GlobalTask ID'yi ekle
        source_agent=source_agent,
        source_task_id=source_task_id,
        dispatcher_task_id=dispatcher_task_id,
        site_id=site_id,
        page_id=page_id,
        page_url=page_url,
        task_type=task_type,
        task_description=task_description,
        original_issue=original_issue,
        agent_report=agent_report,
        agent_completion_time=datetime.utcnow(),
        status=VerificationStatus.PENDING,
        task_history=[]
    )

    # Görev hikayesine ekle
    controller_task.add_to_history(
        "TASK_CREATED",
        f"{source_agent} agent'ından tamamlanma bildirimi alındı",
        {
            "source_task_id": source_task_id,
            "task_type": task_type,
            "page_url": page_url
        }
    )

    controller_task.add_to_history(
        "AGENT_COMPLETION",
        f"{source_agent} görevi tamamladı",
        agent_report
    )

    db.add(controller_task)
    db.flush()  # ID'yi almak için flush
    
    # GlobalTask'a controller_task_id'yi ekle
    if global_task_id:
        try:
            from agents.global_task.worker import update_global_task_agent_id
            update_global_task_agent_id(
                db=db,
                global_task_id=global_task_id,
                agent_name="CONTROLLER",
                agent_task_id=controller_task.id
            )
        except Exception as e:
            print(f"⚠️ GlobalTask güncelleme hatası: {e}")
    
    db.commit()
    db.refresh(controller_task)

    print(f"✅ Controller: Yeni doğrulama görevi oluşturuldu (ID: {controller_task.id}) [GlobalTask ID: {global_task_id}]")
    
    # Reporter log ekle
    try:
        from agents.reporter import add_reporter_log
        add_reporter_log(
            db=db,
            level="INFO",
            source_agent=source_agent,
            target_agent="CONTROLLER",
            message=f"Görev tamamlandı bildirimi alındı: {task_type}",
            details={
                "controller_task_id": controller_task.id,
                "task_type": task_type,
                "page_url": page_url,
                "source_task_id": source_task_id,
                "agent_report_status": agent_report.get("status") if agent_report else None,
                "already_fixed": agent_report.get("already_fixed", False) if agent_report else False
            },
            controller_task_id=controller_task.id,
            global_task_id=global_task_id
        )
    except Exception as log_error:
        print(f"⚠️ Reporter log ekleme hatası: {log_error}")

    # Observer'a doğrulama görevi gönder (5 dakika gecikme ile - WordPress cache için)
    # Background thread'de 5 dakika bekleyip sonra doğrulama gönder
    schedule_verification_with_delay(db, controller_task.id, delay_seconds=300)  # 5 dakika = 300 saniye

    return controller_task


def schedule_verification_with_delay(db: Session, controller_task_id: int, delay_seconds: int = 300):
    """
    Doğrulama görevini belirli bir gecikme ile planla
    WordPress cache ve diğer gecikmeler için bekleme süresi
    
    Args:
        db: Database session
        controller_task_id: Controller task ID
        delay_seconds: Gecikme süresi (saniye) - varsayılan 5 dakika (300 saniye)
    """
    def delayed_verification():
        """Background thread'de çalışacak gecikmeli doğrulama"""
        import time
        import asyncio
        
        print(f"⏳ Controller: Doğrulama {delay_seconds} saniye ({(delay_seconds/60):.1f} dakika) sonra başlatılacak (Task ID: {controller_task_id})")
        
        # Gecikme süresini bekle
        time.sleep(delay_seconds)
        
        print(f"✅ Controller: Gecikme tamamlandı, doğrulama başlatılıyor (Task ID: {controller_task_id})")
        
        # Yeni database session oluştur (thread-safe)
        db_session = SessionLocal()
        try:
            # Controller task'ı kontrol et (hala PENDING durumunda mı?)
            controller_task = db_session.query(ControllerTask).filter(
                ControllerTask.id == controller_task_id
            ).first()
            
            if not controller_task:
                print(f"⚠️ Controller: Task bulunamadı (ID: {controller_task_id})")
                return
            
            if controller_task.status != VerificationStatus.PENDING:
                print(f"⚠️ Controller: Task zaten işlenmiş (ID: {controller_task_id}, Status: {controller_task.status.value})")
                return
            
            # Reporter log ekle (gecikme tamamlandı)
            try:
                from agents.reporter import add_reporter_log
                add_reporter_log(
                    db=db_session,
                    level="INFO",
                    source_agent="CONTROLLER",
                    target_agent="OBSERVER",
                    message=f"Gecikme tamamlandı, doğrulama başlatılıyor: {controller_task.task_type}",
                    details={
                        "controller_task_id": controller_task.id,
                        "task_type": controller_task.task_type,
                        "delay_seconds": delay_seconds,
                        "page_url": controller_task.page_url
                    },
                    controller_task_id=controller_task.id,
                    global_task_id=controller_task.global_task_id
                )
            except Exception as log_error:
                print(f"⚠️ Reporter log ekleme hatası: {log_error}")
            
            # Doğrulama görevini başlat
            result = verify_task_completion(db_session, controller_task_id)
            print(f"✅ Controller: Gecikmeli doğrulama başlatıldı (Task ID: {controller_task_id})")
            
        except Exception as e:
            print(f"❌ Controller: Gecikmeli doğrulama hatası (Task ID: {controller_task_id}): {e}")
            import traceback
            traceback.print_exc()
        finally:
            db_session.close()
    
    # Background thread'de çalıştır
    thread = threading.Thread(target=delayed_verification, daemon=True)
    thread.start()
    print(f"🔄 Controller: Gecikmeli doğrulama thread'i başlatıldı (Task ID: {controller_task_id}, Gecikme: {delay_seconds}s)")


def verify_task_completion(db: Session, controller_task_id: int) -> Dict[str, Any]:
    """
    Görevin tamamlanıp tamamlanmadığını Observer'a göndererek kontrol et

    Args:
        controller_task_id: Controller task ID

    Returns:
        {"status": str, "is_verified": bool, "message": str, "observer_task_id": int}
    """
    controller_task = db.query(ControllerTask).filter(
        ControllerTask.id == controller_task_id
    ).first()

    if not controller_task:
        return {
            "status": "error",
            "message": "Controller task bulunamadı"
        }

    # Durumu VERIFYING olarak güncelle
    controller_task.status = VerificationStatus.VERIFYING
    controller_task.verification_started_at = datetime.utcnow()

    controller_task.add_to_history(
        "VERIFICATION_STARTED",
        "Observer'a doğrulama için gönderiliyor",
        {"page_url": controller_task.page_url}
    )

    db.commit()

    print(f"🔍 Controller: Görev doğrulanıyor (ID: {controller_task.id})")

    # Observer'a görev oluştur
    from agents.observer.models import ObserverTask, TaskType

    # Görev tipine göre Observer task tipi belirle
    task_type_mapping = {
        "FIX_LINK": TaskType.LINK_AUDIT,
        "FIX_301_LINK": TaskType.LINK_AUDIT,
        "FIX_404_LINK": TaskType.LINK_AUDIT,
        "FIX_410_LINK": TaskType.LINK_AUDIT,
        "FIX_REDIRECT_LINK": TaskType.LINK_AUDIT,
        "FIX_BROKEN_LINK": TaskType.LINK_AUDIT,
        "ANALYZE_DUPLICATE_LINKS": TaskType.DUPLICATE_LINK_CHECK,
        "FIX_DUPLICATE_LINKS": TaskType.DUPLICATE_LINK_CHECK,
    }

    observer_task_type = task_type_mapping.get(
        controller_task.task_type,
        TaskType.FULL_AUDIT  # Default
    )

    # already_fixed bilgisini kontrol et (Link Fixer'dan gelen)
    already_fixed = False
    if controller_task.agent_report and isinstance(controller_task.agent_report, dict):
        already_fixed = controller_task.agent_report.get("already_fixed", False)
    
    # Observer task description'ına already_fixed bilgisini ekle
    description = f"🎯 Controller Doğrulaması: {controller_task.page_url}\n"
    description += f"📋 Görev: {controller_task.task_type}\n"
    description += f"🔗 Eski URL: {controller_task.agent_report.get('old_url', 'N/A') if controller_task.agent_report else 'N/A'}\n"
    description += f"✅ Yeni URL: {controller_task.agent_report.get('new_url', 'N/A') if controller_task.agent_report else 'N/A'}\n"
    if already_fixed:
        description += f"⚠️ Link Fixer: Link zaten değiştirilmiş (manuel değişiklik veya önceki işlem)\n"
        description += f"🔍 Observer: Lütfen sayfayı kontrol edin - new_url mevcut mu, old_url yok mu?\n"
    description += f"⚡ SADECE BU SAYFA KONTROL EDİLECEK!"

    # Observer task oluştur (sadece bu sayfa için - SPESİFİK HEDEF)
    observer_task = ObserverTask(
        global_task_id=controller_task.global_task_id,  # ControllerTask'tan global_task_id'yi al
        site_id=controller_task.site_id,
        task_type=observer_task_type,
        description=description,
        total_items=1,
        processed_items=0,
        progress_percentage=0
    )

    db.add(observer_task)
    db.flush()  # ID'yi almak için flush
    
    # GlobalTask'a observer_task_id'yi ekle (verification için)
    if controller_task.global_task_id:
        try:
            from agents.global_task.worker import update_global_task_agent_id
            update_global_task_agent_id(
                db=db,
                global_task_id=controller_task.global_task_id,
                agent_name="OBSERVER",
                agent_task_id=observer_task.id
            )
        except Exception as e:
            print(f"⚠️ GlobalTask güncelleme hatası: {e}")
    
    db.commit()
    db.refresh(observer_task)

    # Controller task'a observer_task_id'yi kaydet
    controller_task.observer_task_id = observer_task.id

    controller_task.add_to_history(
        "OBSERVER_TASK_CREATED",
        f"Observer task oluşturuldu (ID: {observer_task.id})",
        {
            "observer_task_id": observer_task.id,
            "task_type": observer_task_type.value
        }
    )

    db.commit()

    print(f"✅ Controller: Observer task oluşturuldu (ID: {observer_task.id})")
    
    # Reporter log ekle
    try:
        from agents.reporter import add_reporter_log
        add_reporter_log(
            db=db,
            level="INFO",
            source_agent="CONTROLLER",
            target_agent="OBSERVER",
            message=f"Doğrulama görevi gönderildi: {controller_task.task_type}",
            details={
                "controller_task_id": controller_task.id,
                "observer_task_id": observer_task.id,
                "task_type": observer_task_type.value,
                "page_url": controller_task.page_url
            },
            controller_task_id=controller_task.id,
            observer_task_id=observer_task.id
        )
    except Exception as log_error:
        print(f"⚠️ Reporter log ekleme hatası: {log_error}")

    # Observer task'ı arka planda çalıştır
    import asyncio
    from agents.observer.worker import run_observer_task

    # Async task'ı background'da çalıştır
    try:
        # Eğer mevcut event loop varsa kullan
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Loop zaten çalışıyorsa, create_task kullan
            asyncio.create_task(run_observer_task(observer_task.id))
            print(f"🔄 Controller: Observer task arka planda başlatıldı (ID: {observer_task.id})")
        else:
            # Loop çalışmıyorsa, run_until_complete kullan
            loop.run_until_complete(run_observer_task(observer_task.id))
    except RuntimeError:
        # Event loop yoksa, yeni bir loop oluştur
        asyncio.run(run_observer_task(observer_task.id))

    return {
        "status": "verifying",
        "message": "Observer'a doğrulama için gönderildi",
        "observer_task_id": observer_task.id,
        "controller_task_id": controller_task.id
    }


def process_observer_verification_result(
    db: Session,
    controller_task_id: int,
    observer_task_id: int
) -> Dict[str, Any]:
    """
    Observer'dan gelen doğrulama sonucunu işle

    Args:
        controller_task_id: Controller task ID
        observer_task_id: Observer task ID

    Returns:
        {"status": str, "is_verified": bool, "action": str}
    """
    controller_task = db.query(ControllerTask).filter(
        ControllerTask.id == controller_task_id
    ).first()

    if not controller_task:
        return {"status": "error", "message": "Controller task bulunamadı"}

    # Observer task'ı kontrol et
    from agents.observer.models import ObserverTask, ObserverReport, TaskStatus

    observer_task = db.query(ObserverTask).filter(
        ObserverTask.id == observer_task_id
    ).first()

    if not observer_task:
        return {"status": "error", "message": "Observer task bulunamadı"}

    # Observer task tamamlandı mı?
    if observer_task.status != TaskStatus.COMPLETED:
        return {
            "status": "pending",
            "message": "Observer task henüz tamamlanmadı",
            "observer_status": observer_task.status.value
        }

    # Observer'dan gelen raporları kontrol et
    observer_reports = db.query(ObserverReport).filter(
        ObserverReport.task_id == observer_task_id
    ).all()

    # Eğer rapor yoksa veya sadece INFO seviyesindeyse -> BAŞARILI
    has_errors = False
    error_reports = []

    for report in observer_reports:
        if report.severity.value in ["ERROR", "WARNING"]:
            has_errors = True
            error_reports.append({
                "rule_name": report.rule_name,
                "severity": report.severity.value,
                "message": report.message,
                "details": report.details
            })

    # Doğrulama sonucunu kaydet
    controller_task.observer_report = {
        "observer_task_id": observer_task_id,
        "reports_count": len(observer_reports),
        "errors_count": len(error_reports),
        "error_reports": error_reports
    }
    controller_task.observer_verification_time = datetime.utcnow()
    controller_task.verification_completed_at = datetime.utcnow()

    if not has_errors:
        # BAŞARILI - Görev doğrulandı
        controller_task.status = VerificationStatus.VERIFIED_SUCCESS
        controller_task.is_verified = True
        controller_task.verification_notes = "Observer doğrulaması başarılı. Sorun bulunamadı."

        controller_task.add_to_history(
            "VERIFICATION_SUCCESS",
            "Görev başarıyla doğrulandı",
            {
                "reports_count": len(observer_reports),
                "verification_time": datetime.utcnow().isoformat()
            }
        )

        print(f"✅ Controller: Görev BAŞARILI olarak doğrulandı (ID: {controller_task.id})")
        
        # Reporter log ekle
        try:
            from agents.reporter import add_reporter_log
            add_reporter_log(
                db=db,
                level="SUCCESS",
                source_agent="OBSERVER",
                target_agent="CONTROLLER",
                message=f"Doğrulama başarılı: {controller_task.task_type}",
                details={
                    "controller_task_id": controller_task.id,
                    "observer_task_id": observer_task_id,
                    "reports_count": len(observer_reports),
                    "is_verified": True
                },
                controller_task_id=controller_task.id,
                observer_task_id=observer_task_id
            )
        except Exception as log_error:
            print(f"⚠️ Reporter log ekleme hatası: {log_error}")

        # İstatistikleri güncelle
        update_controller_stats(db, "success", controller_task.source_agent)

        return {
            "status": "verified_success",
            "is_verified": True,
            "action": "completed",
            "message": "Görev başarıyla tamamlanmış ve doğrulanmış"
        }

    else:
        # BAŞARISIZ - Görev tamamlanmamış
        controller_task.status = VerificationStatus.VERIFIED_FAILED
        controller_task.is_verified = False
        controller_task.verification_notes = f"{len(error_reports)} sorun bulundu. Görev tekrar atanacak."
        controller_task.retry_count += 1

        controller_task.add_to_history(
            "VERIFICATION_FAILED",
            f"Görev tamamlanmamış. {len(error_reports)} sorun bulundu.",
            {
                "errors_count": len(error_reports),
                "error_reports": error_reports,
                "retry_count": controller_task.retry_count
            }
        )

        print(f"⚠️ Controller: Görev BAŞARISIZ - Tekrar atanacak (ID: {controller_task.id}, Retry: {controller_task.retry_count})")
        
        # Reporter log ekle
        try:
            from agents.reporter import add_reporter_log
            add_reporter_log(
                db=db,
                level="ERROR",
                source_agent="OBSERVER",
                target_agent="CONTROLLER",
                message=f"Doğrulama başarısız: {controller_task.task_type} - {len(error_reports)} hata bulundu",
                details={
                    "controller_task_id": controller_task.id,
                    "observer_task_id": observer_task_id,
                    "reports_count": len(observer_reports),
                    "errors_count": len(error_reports),
                    "error_reports": error_reports,
                    "is_verified": False,
                    "retry_count": controller_task.retry_count
                },
                controller_task_id=controller_task.id,
                observer_task_id=observer_task_id
            )
        except Exception as log_error:
            print(f"⚠️ Reporter log ekleme hatası: {log_error}")

        # İstatistikleri güncelle
        update_controller_stats(db, "failed", controller_task.source_agent)

        # Görev tekrar Dispatcher'a gönderilecek
        retry_task_to_dispatcher(db, controller_task)

        return {
            "status": "verified_failed",
            "is_verified": False,
            "action": "retry_assigned",
            "message": f"Görev tamamlanmamış. {len(error_reports)} sorun bulundu. Tekrar atandı.",
            "retry_count": controller_task.retry_count
        }


def retry_task_to_dispatcher(db: Session, controller_task: ControllerTask):
    """
    Tamamlanmamış görevi Dispatcher'a tekrar gönder

    Args:
        controller_task: Controller task
    """
    from agents.dispatcher.models import DispatcherTask, DispatcherTaskStatus, AgentType

    # old_url ve new_url bilgilerini topla (retry için kritik!)
    old_url = None
    new_url = None
    
    # Önce agent_report'tan al (Link Fixer'dan gelen bilgiler)
    if controller_task.agent_report:
        if isinstance(controller_task.agent_report, dict):
            old_url = controller_task.agent_report.get("old_url")
            new_url = controller_task.agent_report.get("new_url")
    
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
    
    # Task params oluştur - old_url ve new_url'i mutlaka ekle
    task_params = {
        "retry_count": controller_task.retry_count,
        "original_controller_task_id": controller_task.id,
        "previous_error_reports": controller_task.observer_report.get("error_reports", []) if controller_task.observer_report and isinstance(controller_task.observer_report, dict) else []
    }
    
    # old_url ve new_url'i ekle (eğer varsa)
    if old_url:
        task_params["old_url"] = old_url
    if new_url:
        task_params["new_url"] = new_url
    if controller_task.page_url:
        task_params["page_url"] = controller_task.page_url
    
    print(f"🔄 Controller Retry: old_url={old_url}, new_url={new_url}, task_type={controller_task.task_type}")

    # Yeni Dispatcher task oluştur (RETRY olarak işaretle)
    retry_task = DispatcherTask(
        global_task_id=controller_task.global_task_id,  # Aynı global task ID'yi kullan
        task_name=f"[RETRY #{controller_task.retry_count}] {controller_task.task_description}",
        task_type=controller_task.task_type,
        task_description=f"[TEKRAR DENEME] {controller_task.task_description}\n\nRetry Count: {controller_task.retry_count}",
        site_id=controller_task.site_id,
        page_id=controller_task.page_id,
        page_url=controller_task.page_url,
        priority=10,  # Yüksek öncelik
        source_type="CONTROLLER_RETRY",
        source_id=controller_task.id,
        assigned_agent=AgentType.FIXER if "LINK" in controller_task.task_type else AgentType.AI_HELPER,
        status=DispatcherTaskStatus.PENDING,
        task_params=task_params,
        created_at=datetime.utcnow()
    )

    db.add(retry_task)
    db.commit()
    db.refresh(retry_task)
    
    # Reporter log ekle
    try:
        from agents.reporter import add_reporter_log
        add_reporter_log(
            db=db,
            level="WARNING",
            source_agent="CONTROLLER",
            target_agent="DISPATCHER",
            message=f"Retry görevi gönderildi: {controller_task.task_type} (Retry #{controller_task.retry_count})",
            details={
                "controller_task_id": controller_task.id,
                "dispatcher_task_id": retry_task.id,
                "task_type": controller_task.task_type,
                "retry_count": controller_task.retry_count,
                "page_url": controller_task.page_url,
                "assigned_agent": retry_task.assigned_agent.value if retry_task.assigned_agent else None
            },
            controller_task_id=controller_task.id,
            dispatcher_task_id=retry_task.id
        )
    except Exception as log_error:
        print(f"⚠️ Reporter log ekleme hatası: {log_error}")

    # Controller task'ı güncelle
    controller_task.status = VerificationStatus.RETRY_ASSIGNED
    controller_task.retry_notes = f"Görev tekrar Dispatcher'a gönderildi (Retry #{controller_task.retry_count})"

    controller_task.add_to_history(
        "RETRY_ASSIGNED",
        f"Görev tekrar Dispatcher'a gönderildi (Retry #{controller_task.retry_count})",
        {
            "retry_task_id": retry_task.id,
            "retry_count": controller_task.retry_count
        }
    )

    db.commit()
    db.refresh(retry_task)

    print(f"🔄 Controller: Görev tekrar Dispatcher'a gönderildi (Retry Task ID: {retry_task.id}, Retry #{controller_task.retry_count})")

    # İstatistikleri güncelle
    update_controller_stats(db, "retry", controller_task.source_agent)


def update_controller_stats(db: Session, result_type: str, agent_type: str):
    """
    Controller istatistiklerini güncelle

    Args:
        result_type: "success", "failed", "retry"
        agent_type: "FIXER", "AI_HELPER"
    """
    from sqlalchemy import func

    # Bugünkü istatistik kaydını bul veya oluştur
    today = datetime.utcnow().date()
    stats = db.query(ControllerStats).filter(
        func.date(ControllerStats.date) == today,
        ControllerStats.period_type == "daily"
    ).first()

    if not stats:
        stats = ControllerStats(
            date=datetime.utcnow(),
            period_type="daily",
            total_verifications=0,
            verified_success=0,
            verified_failed=0,
            retry_assigned=0,
            verification_errors=0,
            fixer_success=0,
            fixer_failed=0,
            ai_helper_success=0,
            ai_helper_failed=0,
            success_rate=0
        )
        db.add(stats)

    # İstatistikleri güncelle (None kontrolü ile)
    stats.total_verifications = (stats.total_verifications or 0) + 1

    if result_type == "success":
        stats.verified_success = (stats.verified_success or 0) + 1
        if agent_type == "FIXER":
            stats.fixer_success = (stats.fixer_success or 0) + 1
        elif agent_type == "AI_HELPER":
            stats.ai_helper_success = (stats.ai_helper_success or 0) + 1
    elif result_type == "failed":
        stats.verified_failed = (stats.verified_failed or 0) + 1
        if agent_type == "FIXER":
            stats.fixer_failed = (stats.fixer_failed or 0) + 1
        elif agent_type == "AI_HELPER":
            stats.ai_helper_failed = (stats.ai_helper_failed or 0) + 1
    elif result_type == "retry":
        stats.retry_assigned = (stats.retry_assigned or 0) + 1

    # Başarı oranını hesapla (None kontrolü ile)
    total = (stats.verified_success or 0) + (stats.verified_failed or 0)
    if total > 0:
        stats.success_rate = int(((stats.verified_success or 0) / total) * 100)

    db.commit()


def auto_verify_pending_tasks(batch_size: int = 10) -> Dict[str, Any]:
    """
    Bekleyen Controller görevlerini otomatik olarak doğrula

    Args:
        batch_size: Her seferde işlenecek görev sayısı

    Returns:
        {"processed": int, "verified": int, "failed": int, "errors": int}
    """
    db = SessionLocal()
    try:
        # PENDING durumundaki görevleri al
        pending_tasks = db.query(ControllerTask).filter(
            ControllerTask.status == VerificationStatus.PENDING
        ).order_by(
            ControllerTask.created_at.asc()
        ).limit(batch_size).all()

        if not pending_tasks:
            return {
                "processed": 0,
                "verified": 0,
                "failed": 0,
                "errors": 0
            }

        print(f"🔍 Controller: {len(pending_tasks)} bekleyen görev doğrulanacak...")

        verified_count = 0
        error_count = 0

        for task in pending_tasks:
            try:
                # Doğrulama başlat
                result = verify_task_completion(db, task.id)
                if result.get("status") == "verifying":
                    verified_count += 1
                    print(f"✅ Görev doğrulamaya gönderildi: {task.id}")
            except Exception as e:
                print(f"⚠️ Görev doğrulama hatası (task_id={task.id}): {e}")
                error_count += 1

                # Hata durumunu kaydet
                task.status = VerificationStatus.VERIFICATION_ERROR
                task.verification_notes = f"Doğrulama hatası: {str(e)}"
                task.add_to_history("VERIFICATION_ERROR", str(e), {})
                db.commit()

        return {
            "processed": len(pending_tasks),
            "verified": verified_count,
            "failed": 0,
            "errors": error_count
        }

    except Exception as e:
        print(f"❌ Otomatik doğrulama hatası: {e}")
        import traceback
        traceback.print_exc()
        return {
            "processed": 0,
            "verified": 0,
            "failed": 0,
            "errors": 1
        }
    finally:
        db.close()


def check_observer_verifications() -> Dict[str, Any]:
    """
    Observer'a gönderilmiş doğrulamaları kontrol et ve sonuçları işle

    Returns:
        {"processed": int, "success": int, "failed": int}
    """
    db = SessionLocal()
    try:
        # VERIFYING durumundaki görevleri al
        verifying_tasks = db.query(ControllerTask).filter(
            ControllerTask.status == VerificationStatus.VERIFYING
        ).all()

        if not verifying_tasks:
            return {
                "processed": 0,
                "success": 0,
                "failed": 0
            }

        print(f"🔍 Controller: {len(verifying_tasks)} doğrulama sonucu kontrol ediliyor...")

        success_count = 0
        failed_count = 0

        for task in verifying_tasks:
            try:
                result = process_observer_verification_result(
                    db,
                    task.id,
                    task.observer_task_id
                )

                if result.get("status") == "verified_success":
                    success_count += 1
                    print(f"✅ Görev doğrulandı (başarılı): {task.id}")
                elif result.get("status") == "verified_failed":
                    failed_count += 1
                    print(f"⚠️ Görev doğrulandı (başarısız - tekrar atandı): {task.id}")
            except Exception as e:
                print(f"⚠️ Doğrulama sonucu işleme hatası (task_id={task.id}): {e}")

        return {
            "processed": len(verifying_tasks),
            "success": success_count,
            "failed": failed_count
        }

    except Exception as e:
        print(f"❌ Observer doğrulama kontrolü hatası: {e}")
        import traceback
        traceback.print_exc()
        return {
            "processed": 0,
            "success": 0,
            "failed": 0
        }
    finally:
        db.close()
