# ============================================
# Dispatcher Agent - Automatic Task Processor
# ============================================
# Otomatik olarak Reviewer queue'dan görevleri alır ve agent'lara dağıtır
# Her 30 saniyede bir çalışır, 10'lu paket halinde işler

from sqlalchemy.orm import Session
from datetime import datetime
from core.database import SessionLocal
from .models import DispatcherTask, DispatcherTaskStatus, AgentType
from .worker import create_task_from_reviewer_item, assign_task_to_agent
from agents.reviewer.models import ReviewerQueue, QueueStatus


def process_reviewer_queue_batch(batch_size: int = None) -> dict:
    """
    Reviewer queue'dan görevleri al ve Dispatcher'a ekle
    İlk 10 görevi anında al ve ata, geri kalanını kuyruğa ekle
    
    Args:
        batch_size: Artık kullanılmıyor (geriye uyumluluk için tutuldu)
    
    Returns:
        {"processed": int, "created": int, "assigned": int, "queued": int, "errors": int}
    """
    db = SessionLocal()
    try:
        # Önce veritabanındaki eski enum değerlerini direkt SQL ile temizle
        try:
            from sqlalchemy import text
            # DispatcherTask'lardaki eski enum değerlerini temizle
            db.execute(text("""
                UPDATE dispatcher_tasks 
                SET assigned_agent = 'FIXER' 
                WHERE assigned_agent IN ('OBSERVER', 'REVIEWER', 'ANALYZER')
            """))
            # AgentRoutingRule'lardaki eski enum değerlerini temizle
            db.execute(text("""
                UPDATE agent_routing_rules 
                SET agent_type = 'FIXER' 
                WHERE agent_type IN ('OBSERVER', 'REVIEWER', 'ANALYZER')
            """))
            db.commit()
        except Exception as cleanup_error:
            print(f"⚠️ SQL temizleme hatası (önemsiz): {cleanup_error}")
            db.rollback()
        
        # Bekleyen reviewer queue öğelerini öncelik sırasına göre al
        all_queue_items = db.query(ReviewerQueue).filter(
            ReviewerQueue.status == QueueStatus.PENDING
        ).order_by(
            ReviewerQueue.priority_score.desc(),  # Yüksek öncelik önce
            ReviewerQueue.created_at.asc()  # Eski görevler önce
        ).all()
        
        if not all_queue_items:
            return {
                "processed": 0,
                "created": 0,
                "assigned": 0,
                "queued": 0,
                "errors": 0
            }
        
        print(f"📋 Dispatcher: Reviewer queue'dan {len(all_queue_items)} görev bulundu")
        
        # İlk 10 görevi anında işle ve ata
        immediate_items = all_queue_items[:10]
        queued_items = all_queue_items[10:] if len(all_queue_items) > 10 else []
        
        print(f"🚀 Dispatcher: İlk 10 görev anında işlenecek, {len(queued_items)} görev kuyruğa eklenecek")
        
        created_count = 0
        assigned_count = 0
        queued_count = 0
        error_count = 0
        
        # İlk 10 görevi işle ve ata
        for item in immediate_items:
            try:
                # Zaten dispatcher task'ı var mı kontrol et (SQL ile, enum hatası olmaması için)
                try:
                    from sqlalchemy import text
                    existing_count = db.execute(text("""
                        SELECT COUNT(*) FROM dispatcher_tasks 
                        WHERE source_type = 'REVIEWER_QUEUE' AND source_id = :source_id
                    """), {"source_id": item.id}).scalar()
                    
                    if existing_count > 0:
                        # Zaten DispatcherTask var, ama LinkFixTask oluşturulmuş mu kontrol et
                        existing_dispatcher_task = db.query(DispatcherTask).filter(
                            DispatcherTask.source_type == "REVIEWER_QUEUE",
                            DispatcherTask.source_id == item.id
                        ).first()
                        
                        if existing_dispatcher_task:
                            # Eğer görev atanmışsa ve agent_task_id varsa, LinkFixTask oluşturulmuş demektir
                            if existing_dispatcher_task.status == DispatcherTaskStatus.ASSIGNED and existing_dispatcher_task.agent_task_id:
                                print(f"⏭️ Reviewer item {item.id} zaten işlenmiş: DispatcherTask ID={existing_dispatcher_task.id}, Agent Task ID={existing_dispatcher_task.agent_task_id}")
                                continue
                            elif existing_dispatcher_task.status == DispatcherTaskStatus.PENDING:
                                # Görev oluşturulmuş ama atanmamış, şimdi ata
                                print(f"🔄 Reviewer item {item.id} için DispatcherTask var ama atanmamış, şimdi atanıyor: DispatcherTask ID={existing_dispatcher_task.id}")
                                try:
                                    from .worker import assign_task_to_agent
                                    result = assign_task_to_agent(db, existing_dispatcher_task.id)
                                    assigned_count += 1
                                    db.commit()
                                    print(f"✅ Görev atandı: DispatcherTask ID {existing_dispatcher_task.id} -> Agent Task ID: {result.get('agent_task_id')}")
                                except Exception as assign_error:
                                    print(f"⚠️ Görev atama hatası (dispatcher_task_id={existing_dispatcher_task.id}): {assign_error}")
                                    import traceback
                                    traceback.print_exc()
                                    error_count += 1
                                    db.rollback()
                                continue
                        else:
                            # existing_count > 0 ama task bulunamadı, devam et
                            pass
                except Exception as check_error:
                    # Kontrol hatası varsa devam et
                    print(f"⚠️ Mevcut görev kontrolü hatası (item_id={item.id}): {check_error}")
                    pass
                
                # Dispatcher task oluştur ve anında ata
                try:
                    print(f"🔍 Reviewer item işleniyor: ID={item.id}, Action Type={item.action_type}, Rule Name={item.rule_name}")
                    task = create_task_from_reviewer_item(db, item)
                    if task:
                        created_count += 1
                        db.commit()
                        print(f"✅ DispatcherTask oluşturuldu: ID={task.id}, Agent={task.assigned_agent.value if task.assigned_agent else 'None'}, Task Type={task.task_type}")
                        
                        # Anında agent'a ata
                        try:
                            from .worker import assign_task_to_agent
                            result = assign_task_to_agent(db, task.id)
                            assigned_count += 1
                            db.commit()
                            print(f"✅ Görev anında atandı: Task ID {task.id} -> {task.assigned_agent.value if task.assigned_agent else 'None'}")
                        except Exception as assign_error:
                            print(f"⚠️ Görev atama hatası (task_id={task.id}): {assign_error}")
                            import traceback
                            traceback.print_exc()
                            error_count += 1
                            db.rollback()
                    else:
                        # Görev oluşturulamadı (desteklenmeyen tip)
                        print(f"⚠️ Görev oluşturulamadı (item_id={item.id}): Action Type='{item.action_type}', Rule Name='{item.rule_name}' - Desteklenmeyen tip veya None döndü")
                except (AttributeError, ValueError) as enum_error:
                    # Enum hatası varsa (eski değerler), bu item'ı atla
                    print(f"⚠️ Enum hatası (item_id={item.id}): {enum_error}")
                    error_count += 1
                    db.rollback()
                    continue
                    
            except Exception as item_error:
                print(f"⚠️ Reviewer item işleme hatası (item_id={item.id}): {item_error}")
                import traceback
                traceback.print_exc()
                error_count += 1
                db.rollback()
                continue
        
        # Geri kalan görevleri kuyruğa ekle (DispatcherTask oluştur ama atama yapma)
        for item in queued_items:
            try:
                # Zaten dispatcher task'ı var mı kontrol et
                try:
                    from sqlalchemy import text
                    existing_count = db.execute(text("""
                        SELECT COUNT(*) FROM dispatcher_tasks 
                        WHERE source_type = 'REVIEWER_QUEUE' AND source_id = :source_id
                    """), {"source_id": item.id}).scalar()
                    
                    if existing_count > 0:
                        continue
                except Exception as check_error:
                    pass
                
                # Dispatcher task oluştur (atama yapma, sonra auto_assign_pending_tasks yapacak)
                try:
                    task = create_task_from_reviewer_item(db, item)
                    if task:
                        queued_count += 1
                        db.commit()
                        print(f"📥 Görev kuyruğa eklendi: Task ID {task.id}")
                    else:
                        pass
                except Exception as task_error:
                    print(f"⚠️ Kuyruk görevi oluşturma hatası (item_id={item.id}): {task_error}")
                    error_count += 1
                    db.rollback()
                    continue
                    
            except Exception as item_error:
                print(f"⚠️ Kuyruk item işleme hatası (item_id={item.id}): {item_error}")
                error_count += 1
                db.rollback()
                continue
        
        return {
            "processed": len(all_queue_items),
            "created": created_count + queued_count,
            "assigned": assigned_count,
            "queued": queued_count,
            "errors": error_count
        }
    
    except Exception as e:
        print(f"❌ Reviewer queue batch işleme hatası: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return {
            "processed": 0,
            "created": 0,
            "assigned": 0,
            "errors": 1
        }
    finally:
        db.close()


def auto_assign_pending_tasks_batch(batch_size: int = 10) -> dict:
    """
    Bekleyen Dispatcher görevlerinden 10 tanesini öncelik sırasına göre agent'lara ata
    10 görev bittiğinde yeni 10 görev alınır
    
    Args:
        batch_size: Her seferde işlenecek görev sayısı (default: 10)
    
    Returns:
        {"processed": int, "assigned": int, "errors": int}
    """
    db = SessionLocal()
    try:
        # Önce eski enum değerlerini temizle
        try:
            from sqlalchemy import text
            db.execute(text("""
                UPDATE dispatcher_tasks 
                SET assigned_agent = 'FIXER' 
                WHERE assigned_agent IN ('OBSERVER', 'REVIEWER', 'ANALYZER')
            """))
            db.commit()
        except Exception as cleanup_error:
            db.rollback()
        
        # Bekleyen görevleri öncelik sırasına göre al (10'ar 10'ar)
        pending_tasks = db.query(DispatcherTask).filter(
            DispatcherTask.status == DispatcherTaskStatus.PENDING,
            DispatcherTask.assigned_agent.in_([AgentType.FIXER, AgentType.AI_HELPER])  # Sadece geçerli agent'lar
        ).order_by(
            DispatcherTask.priority.desc(),  # Yüksek öncelik önce
            DispatcherTask.created_at.asc()  # Eski görevler önce
        ).limit(batch_size).all()  # 10'ar 10'ar al
        
        if not pending_tasks:
            return {
                "processed": 0,
                "assigned": 0,
                "errors": 0
            }
        
        print(f"📋 Dispatcher: {len(pending_tasks)} bekleyen görev bulundu, öncelik sırasına göre agent'lara atanıyor...")
        
        assigned_count = 0
        error_count = 0
        
        for task in pending_tasks:
            try:
                # Agent kontrolü
                if not task.assigned_agent:
                    print(f"⚠️ Görev atlanıyor (task_id={task.id}): assigned_agent None")
                    error_count += 1
                    continue
                
                # Görevi agent'a ata
                result = assign_task_to_agent(db, task.id)
                assigned_count += 1
                db.commit()
                print(f"✅ Görev atandı: Task ID {task.id} -> {task.assigned_agent.value} (Agent Task ID: {result.get('agent_task_id')})")
            except Exception as assign_error:
                import traceback
                error_trace = traceback.format_exc()
                print(f"⚠️ Görev atama hatası (task_id={task.id}, agent={task.assigned_agent.value if task.assigned_agent else 'None'}): {assign_error}")
                print(error_trace)
                
                # Görevi yeniden yükle ve durumunu kontrol et
                db.refresh(task)
                
                # Eğer görev FAILED olarak işaretlenmemişse, manuel olarak işaretle
                if task.status != DispatcherTaskStatus.FAILED:
                    task.status = DispatcherTaskStatus.FAILED
                    task.error_message = str(assign_error)
                    db.commit()
                    print(f"❌ Görev FAILED olarak işaretlendi: Task ID {task.id}")
                else:
                    # Zaten FAILED ise rollback yapma
                    db.rollback()
                
                error_count += 1
                continue
        
        return {
            "processed": len(pending_tasks),
            "assigned": assigned_count,
            "errors": error_count
        }
    
    except Exception as e:
        print(f"❌ Otomatik görev atama hatası: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return {
            "processed": 0,
            "assigned": 0,
            "errors": 1
        }
    finally:
        db.close()


async def dispatcher_auto_processor():
    """
    Dispatcher otomatik işlemci (async wrapper)
    Reviewer queue'dan görevleri alır ve agent'lara dağıtır
    Her çalıştırmada:
    1. Reviewer queue'dan 10 görev al ve Dispatcher'a ekle
    2. Bekleyen Dispatcher görevlerinden 10 tanesini agent'lara ata
    """
    import asyncio
    try:
        # Sync fonksiyonları thread pool'da çalıştır (blocking DB işlemleri için)
        loop = asyncio.get_event_loop()
        
        # 1. Reviewer queue'dan TÜM bekleyen görevleri al (öncelik sırasına göre)
        queue_result = await loop.run_in_executor(None, process_reviewer_queue_batch)
        
        # 2. Bekleyen görevlerden 10 tanesini öncelik sırasına göre ata
        assign_result = await loop.run_in_executor(None, auto_assign_pending_tasks_batch, 10)
        
        # Sonuçları logla
        if queue_result.get("created", 0) > 0 or assign_result.get("assigned", 0) > 0:
            print(f"✅ Dispatcher: {queue_result.get('created', 0)} görev oluşturuldu, {assign_result.get('assigned', 0)} görev atandı")
        
        return {
            "queue_processed": queue_result,
            "tasks_assigned": assign_result
        }
    
    except Exception as e:
        print(f"❌ Dispatcher otomatik işlemci hatası: {e}")
        import traceback
        traceback.print_exc()
        return {
            "queue_processed": {"errors": 1},
            "tasks_assigned": {"errors": 1}
        }

