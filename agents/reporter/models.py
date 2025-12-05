# ============================================
# Reporter Agent - Models
# ============================================

from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from core.database import Base


class ReporterLog(Base):
    """Reporter Agent - Agentlar arası haberleşme ve hata logları"""
    __tablename__ = "reporter_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Log bilgileri
    log_level = Column(String(20), nullable=False, index=True)  # INFO, WARNING, ERROR, SUCCESS, DEBUG
    source_agent = Column(String(50), nullable=False, index=True)  # CONTROLLER, DISPATCHER, FIXER, AI_HELPER, OBSERVER, REVIEWER
    target_agent = Column(String(50), nullable=True, index=True)  # Hedef agent (varsa)
    
    # Mesaj ve detaylar
    message = Column(Text, nullable=False)
    details_json = Column(JSON, nullable=True)  # Ek detaylar (JSON formatında)
    
    # İlişkili görevler (opsiyonel)
    global_task_id = Column(Integer, ForeignKey("global_tasks.id"), nullable=True, index=True)  # Global task ID
    controller_task_id = Column(Integer, ForeignKey("controller_tasks.id"), nullable=True, index=True)
    dispatcher_task_id = Column(Integer, ForeignKey("dispatcher_tasks.id"), nullable=True, index=True)
    link_fix_task_id = Column(Integer, ForeignKey("link_fix_tasks.id"), nullable=True, index=True)
    observer_task_id = Column(Integer, ForeignKey("observer_tasks.id"), nullable=True, index=True)
    
    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    def __repr__(self):
        return f"<ReporterLog(id={self.id}, level={self.log_level}, source={self.source_agent}, message='{self.message[:50]}...')>"


def init_reporter_tables():
    """Reporter tablolarını oluştur"""
    from core.database import engine, SessionLocal
    from sqlalchemy import text, inspect
    
    ReporterLog.__table__.create(bind=engine, checkfirst=True)
    
    # Migration: global_task_id kolonu ekle
    db = SessionLocal()
    try:
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('reporter_logs')]
        if 'global_task_id' not in columns:
            print("🔄 reporter_logs tablosuna global_task_id kolonu ekleniyor...")
            db.execute(text("ALTER TABLE reporter_logs ADD COLUMN global_task_id INTEGER"))
            db.commit()
            print("✅ global_task_id kolonu eklendi (reporter_logs)")
    except Exception as e:
        print(f"⚠️ reporter_logs migration hatası: {e}")
        db.rollback()
    finally:
        db.close()
    
    print("✅ Reporter tabloları oluşturuldu/kontrol edildi")

