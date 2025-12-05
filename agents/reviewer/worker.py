# ============================================
# Reviewer Agent - Worker Functions
# ============================================

from sqlalchemy.orm import Session
from datetime import datetime
from agents.observer.models import ObserverReport, ReportSeverity
from .models import (
    ReviewerQueue, QueueStatus, PriorityScore,
    get_priority_score, get_action_plan
)


def process_reports_to_queue(db: Session, site_id: int = None) -> int:
    """
    Observer'dan gelen raporları analiz edip kuyruğa ekler
    
    Args:
        db: Database session
        site_id: Belirli bir site için işle (None ise tüm siteler)
    
    Returns:
        Kuyruğa eklenen rapor sayısı
    """
    # Henüz kuyruğa eklenmemiş raporları al
    query = db.query(ObserverReport).filter(
        ~ObserverReport.id.in_(
            db.query(ReviewerQueue.observer_report_id)
        )
    )
    
    if site_id:
        query = query.filter(ObserverReport.site_id == site_id)
    
    # Sadece ERROR ve WARNING seviyesindeki raporları al
    reports = query.filter(
        ObserverReport.severity.in_([ReportSeverity.ERROR, ReportSeverity.WARNING])
    ).all()
    
    added_count = 0
    
    for report in reports:
        # Öncelik skorunu hesapla
        priority_score = get_priority_score(report.rule_name)

        # Öncelik skoru 0 ise (bilinmeyen kural) atla
        if priority_score == 0:
            continue

        # 🔥 DUPLICATE KONTROLÜ: Aynı sayfa + aynı kural + aynı severity için zaten bekleyen görev var mı?
        existing_queue_item = db.query(ReviewerQueue).filter(
            ReviewerQueue.page_url == report.page_url,
            ReviewerQueue.rule_name == report.rule_name,
            ReviewerQueue.severity == report.severity.value,
            ReviewerQueue.status.in_([QueueStatus.PENDING, QueueStatus.IN_PROGRESS])
        ).first()

        if existing_queue_item:
            # Bu görev zaten kuyrukta, tekrar ekleme
            print(f"⏭️ Reviewer: Duplicate görev atlandı - {report.rule_name} ({report.page_url}) [Mevcut Queue ID: {existing_queue_item.id}]")
            continue

        # Aksiyon planını oluştur
        action_plan, action_type = get_action_plan(
            report.rule_name,
            report.severity.value,
            report.details if report.details else {}
        )

        # 🔥 YENİ: Her kritik hata için Child GlobalTask oluştur
        child_global_task_id = None
        if report.global_task_id:  # Parent task varsa
            try:
                from agents.global_task.worker import get_global_task_by_id, create_child_task
                from agents.global_task.models import GlobalTaskStatus
                
                # Parent task'ı bul
                parent_task = get_global_task_by_id(db, report.global_task_id)
                if parent_task:
                    # Child task tipini belirle (action_type'a göre)
                    child_task_type = action_type if action_type else "FIX_ISSUE"
                    
                    # Task data hazırla (sadece bu hataya özel)
                    task_data = {
                        "target_url": report.page_url,
                        "issue": report.rule_name,
                        "severity": report.severity.value,
                        "details": report.details if report.details else {},
                        "observer_report_id": report.id
                    }
                    
                    # Child GlobalTask oluştur
                    child_task = create_child_task(
                        db=db,
                        parent_task=parent_task,
                        task_type=child_task_type,
                        site_id=report.site_id,
                        page_id=report.page_id,
                        page_url=report.page_url,
                        task_description=f"{report.rule_name} - {report.severity.value}: {report.page_url}",
                        task_data=task_data
                    )
                    child_global_task_id = child_task.id
                    print(f"✅ Child GlobalTask oluşturuldu: ID={child_task.id}, Parent={parent_task.id}, Type={child_task_type}")
            except Exception as e:
                print(f"⚠️ Child GlobalTask oluşturma hatası: {e}")
                import traceback
                traceback.print_exc()

        # Kuyruğa ekle (Child GlobalTask ID'sini kullan)
        queue_item = ReviewerQueue(
            global_task_id=child_global_task_id or report.global_task_id,  # Child task ID varsa onu kullan
            observer_report_id=report.id,
            site_id=report.site_id,
            page_id=report.page_id,
            priority_score=priority_score,
            status=QueueStatus.PENDING,
            rule_name=report.rule_name,
            severity=report.severity.value,
            page_url=report.page_url,
            action_plan=action_plan,
            action_type=action_type,
            created_at=datetime.utcnow()
        )

        db.add(queue_item)
        db.flush()  # ID'yi almak için flush
        
        # Child GlobalTask'a reviewer_queue_id'yi ekle
        if child_global_task_id:
            try:
                from agents.global_task.worker import update_global_task_agent_id
                update_global_task_agent_id(
                    db=db,
                    global_task_id=child_global_task_id,
                    agent_name="REVIEWER",
                    agent_task_id=queue_item.id
                )
            except Exception as e:
                print(f"⚠️ Child GlobalTask güncelleme hatası: {e}")
        
        added_count += 1
        print(f"✅ Reviewer: Yeni görev kuyruğa eklendi - {report.rule_name} ({report.page_url}) [GlobalTask ID: {report.global_task_id}]")
        
        # Reporter log ekle
        try:
            from agents.reporter import add_reporter_log
            add_reporter_log(
                db=db,
                level="INFO",
                source_agent="OBSERVER",
                target_agent="REVIEWER",
                message=f"Observer raporu kuyruğa eklendi: {report.rule_name}",
                details={
                    "observer_report_id": report.id,
                    "rule_name": report.rule_name,
                    "severity": report.severity.value,
                    "page_url": report.page_url,
                    "priority_score": priority_score,
                    "action_plan": action_plan,
                    "action_type": action_type
                },
                observer_task_id=report.task_id
            )
        except Exception as log_error:
            print(f"⚠️ Reporter log ekleme hatası: {log_error}")
    
    db.commit()
    
    # Eğer yeni görevler eklendiyse, Dispatcher'a bildir (ping)
    if added_count > 0:
        print(f"🔔 Reviewer: {added_count} yeni görev kuyruğa eklendi, Dispatcher'a bildiriliyor...")
        # Dispatcher otomatik olarak her 30 saniyede bir kontrol ediyor, burada sadece log
    
    return added_count


def get_queue_summary(db: Session, site_id: int = None) -> dict:
    """
    Kuyruk özeti istatistikleri
    
    Returns:
        {
            "total_pending": int,
            "total_in_progress": int,
            "total_completed": int,
            "by_priority": {1: count, 2: count, ...},
            "by_rule": {"LINK_AUDIT": count, ...}
        }
    """
    query = db.query(ReviewerQueue)
    
    if site_id:
        query = query.filter(ReviewerQueue.site_id == site_id)
    
    total_pending = query.filter(ReviewerQueue.status == QueueStatus.PENDING).count()
    total_in_progress = query.filter(ReviewerQueue.status == QueueStatus.IN_PROGRESS).count()
    total_completed = query.filter(ReviewerQueue.status == QueueStatus.COMPLETED).count()
    
    # Öncelik bazında
    by_priority = {}
    for priority in range(1, 6):
        by_priority[priority] = query.filter(
            ReviewerQueue.priority_score == priority,
            ReviewerQueue.status == QueueStatus.PENDING
        ).count()
    
    # Kural bazında
    by_rule = {}
    rules = ["LINK_AUDIT", "H1_CHECK", "FRESHNESS_CHECK", "DUPLICATE_LINK_CHECK", "SCHEMA_CHECK"]
    for rule in rules:
        by_rule[rule] = query.filter(
            ReviewerQueue.rule_name == rule,
            ReviewerQueue.status == QueueStatus.PENDING
        ).count()
    
    return {
        "total_pending": total_pending,
        "total_in_progress": total_in_progress,
        "total_completed": total_completed,
        "by_priority": by_priority,
        "by_rule": by_rule
    }


