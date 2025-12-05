# Reporter Agent - Tüm görevlerin hikayesini gösterir

from .models import ReporterLog, init_reporter_tables
from .router import router

__all__ = ["ReporterLog", "init_reporter_tables", "router"]


def add_reporter_log(
    db,
    level: str,
    source_agent: str,
    message: str,
    target_agent: str = None,
    details: dict = None,
    global_task_id: int = None,
    controller_task_id: int = None,
    dispatcher_task_id: int = None,
    link_fix_task_id: int = None,
    observer_task_id: int = None
):
    """
    Reporter log ekleme helper fonksiyonu
    Diğer agentlar bu fonksiyonu kullanarak log ekleyebilir
    
    Args:
        db: Database session
        level: Log seviyesi (DEBUG, INFO, WARNING, ERROR, SUCCESS)
        source_agent: Kaynak agent (CONTROLLER, DISPATCHER, FIXER, AI_HELPER, OBSERVER, REVIEWER)
        message: Log mesajı
        target_agent: Hedef agent (opsiyonel)
        details: Ek detaylar (dict)
        controller_task_id: İlişkili Controller task ID (opsiyonel)
        dispatcher_task_id: İlişkili Dispatcher task ID (opsiyonel)
        link_fix_task_id: İlişkili Link Fix task ID (opsiyonel)
        observer_task_id: İlişkili Observer task ID (opsiyonel)
    """
    try:
        log = ReporterLog(
            log_level=level.upper(),
            source_agent=source_agent.upper(),
            target_agent=target_agent.upper() if target_agent else None,
            message=message,
            details_json=details,
            global_task_id=global_task_id,
            controller_task_id=controller_task_id,
            dispatcher_task_id=dispatcher_task_id,
            link_fix_task_id=link_fix_task_id,
            observer_task_id=observer_task_id
        )
        
        db.add(log)
        db.commit()
        return log
    except Exception as e:
        db.rollback()
        print(f"⚠️ Reporter log ekleme hatası: {e}")
        return None
