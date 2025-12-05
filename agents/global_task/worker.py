# ============================================
# Global Task Worker - Global task oluşturma ve yönetimi
# ============================================

from datetime import datetime
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any
from .models import GlobalTask, GlobalTaskStatus


def create_global_task(
    db: Session,
    task_type: str,
    site_id: int,
    page_id: Optional[int] = None,
    page_url: Optional[str] = None,
    task_description: Optional[str] = None,
    observer_task_id: Optional[int] = None,
    parent_id: Optional[int] = None,
    root_scan_id: Optional[int] = None,
    task_data: Optional[Dict[str, Any]] = None
) -> GlobalTask:
    """
    Yeni bir GlobalTask oluştur
    
    Args:
        db: Database session
        task_type: Görev tipi (AUDIT_SCAN, LINK_FIX, FULL_AUDIT, etc.)
        site_id: Site ID
        page_id: Page ID (opsiyonel)
        page_url: Page URL (opsiyonel)
        task_description: Görev açıklaması (opsiyonel)
        observer_task_id: Observer task ID (eğer Observer'dan başlıyorsa)
        parent_id: Parent task ID (eğer child task ise)
        root_scan_id: Root scan ID (en üstteki tarama ID'si)
        task_data: Task'a özel veri (JSON formatında)
    
    Returns:
        GlobalTask instance
    """
    global_task = GlobalTask(
        task_type=task_type,
        task_description=task_description,
        site_id=site_id,
        page_id=page_id,
        page_url=page_url,
        status=GlobalTaskStatus.PENDING,
        observer_task_id=observer_task_id,
        parent_id=parent_id,
        root_scan_id=root_scan_id,
        result=task_data,  # task_data'yı result'a kaydet
        created_at=datetime.utcnow()
    )
    
    db.add(global_task)
    db.commit()
    db.refresh(global_task)
    
    return global_task


def create_parent_audit_task(
    db: Session,
    site_id: int,
    task_description: Optional[str] = None,
    observer_task_id: Optional[int] = None
) -> GlobalTask:
    """
    Parent Audit Task oluştur (Tarama/Denetim için)
    
    Args:
        db: Database session
        site_id: Site ID
        task_description: Görev açıklaması
        observer_task_id: Observer task ID
    
    Returns:
        GlobalTask instance (Parent)
    """
    return create_global_task(
        db=db,
        task_type="AUDIT_SCAN",  # Parent task'lar her zaman AUDIT_SCAN
        site_id=site_id,
        task_description=task_description or "AUDIT_SCAN görevi",
        observer_task_id=observer_task_id,
        parent_id=None,  # Parent task'ın parent'ı yok
        root_scan_id=None  # Parent task kendi root'u
    )


def create_child_task(
    db: Session,
    parent_task: GlobalTask,
    task_type: str,
    site_id: int,
    page_id: Optional[int] = None,
    page_url: Optional[str] = None,
    task_description: Optional[str] = None,
    task_data: Optional[Dict[str, Any]] = None
) -> GlobalTask:
    """
    Child Task oluştur (Her hata için ayrı)
    
    Args:
        db: Database session
        parent_task: Parent GlobalTask
        task_type: Görev tipi (LINK_FIX, etc.)
        site_id: Site ID
        page_id: Page ID (opsiyonel)
        page_url: Page URL (opsiyonel)
        task_description: Görev açıklaması
        task_data: Task'a özel veri (target_url, issue, etc.)
    
    Returns:
        GlobalTask instance (Child)
    """
    # root_scan_id'yi belirle (parent'ın root'u varsa onu kullan, yoksa parent'ın kendisi root)
    root_scan_id = parent_task.root_scan_id if parent_task.root_scan_id else parent_task.id
    
    child_task = create_global_task(
        db=db,
        task_type=task_type,
        site_id=site_id,
        page_id=page_id,
        page_url=page_url,
        task_description=task_description,
        parent_id=parent_task.id,
        root_scan_id=root_scan_id,
        task_data=task_data
    )
    
    return child_task


def update_global_task_agent_id(
    db: Session,
    global_task_id: int,
    agent_name: str,
    agent_task_id: int
) -> bool:
    """
    GlobalTask'a agent task ID'sini ekle
    
    Args:
        db: Database session
        global_task_id: Global task ID
        agent_name: Agent adı (OBSERVER, REVIEWER, DISPATCHER, FIXER, CONTROLLER)
        agent_task_id: Agent'ın task ID'si
    
    Returns:
        True if successful
    """
    global_task = db.query(GlobalTask).filter(GlobalTask.id == global_task_id).first()
    if not global_task:
        return False
    
    if agent_name == "OBSERVER":
        global_task.observer_task_id = agent_task_id
    elif agent_name == "REVIEWER":
        global_task.reviewer_queue_id = agent_task_id
    elif agent_name == "DISPATCHER":
        global_task.dispatcher_task_id = agent_task_id
    elif agent_name == "FIXER":
        global_task.link_fix_task_id = agent_task_id
    elif agent_name == "CONTROLLER":
        global_task.controller_task_id = agent_task_id
    
    db.commit()
    return True


def update_global_task_status(
    db: Session,
    global_task_id: int,
    status: GlobalTaskStatus,
    result: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None
) -> bool:
    """
    GlobalTask durumunu güncelle
    
    Args:
        db: Database session
        global_task_id: Global task ID
        status: Yeni durum
        result: Sonuç (opsiyonel)
        error_message: Hata mesajı (opsiyonel)
    
    Returns:
        True if successful
    """
    global_task = db.query(GlobalTask).filter(GlobalTask.id == global_task_id).first()
    if not global_task:
        return False
    
    global_task.status = status
    
    if status == GlobalTaskStatus.IN_PROGRESS and not global_task.started_at:
        global_task.started_at = datetime.utcnow()
    elif status in [GlobalTaskStatus.COMPLETED, GlobalTaskStatus.FAILED, GlobalTaskStatus.CANCELLED]:
        global_task.completed_at = datetime.utcnow()
    
    if result:
        global_task.result = result
    if error_message:
        global_task.error_message = error_message
    
    db.commit()
    return True


def get_global_task_by_id(db: Session, global_task_id: int) -> Optional[GlobalTask]:
    """GlobalTask'ı ID'ye göre al"""
    return db.query(GlobalTask).filter(GlobalTask.id == global_task_id).first()


def get_global_task_by_agent_id(
    db: Session,
    agent_name: str,
    agent_task_id: int
) -> Optional[GlobalTask]:
    """
    Agent task ID'sine göre GlobalTask'ı bul
    
    Args:
        db: Database session
        agent_name: Agent adı (OBSERVER, REVIEWER, DISPATCHER, FIXER, CONTROLLER)
        agent_task_id: Agent'ın task ID'si
    
    Returns:
        GlobalTask instance veya None
    """
    if agent_name == "OBSERVER":
        return db.query(GlobalTask).filter(GlobalTask.observer_task_id == agent_task_id).first()
    elif agent_name == "REVIEWER":
        return db.query(GlobalTask).filter(GlobalTask.reviewer_queue_id == agent_task_id).first()
    elif agent_name == "DISPATCHER":
        return db.query(GlobalTask).filter(GlobalTask.dispatcher_task_id == agent_task_id).first()
    elif agent_name == "FIXER":
        return db.query(GlobalTask).filter(GlobalTask.link_fix_task_id == agent_task_id).first()
    elif agent_name == "CONTROLLER":
        return db.query(GlobalTask).filter(GlobalTask.controller_task_id == agent_task_id).first()
    
    return None

