# ============================================
# Global Task - Tüm agent işlemlerini takip eden merkezi task sistemi
# ============================================

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON, Enum as SQLEnum
from sqlalchemy.orm import relationship
import enum

from core.database import Base


class GlobalTaskStatus(enum.Enum):
    """Global task durumları"""
    PENDING = "PENDING"  # Beklemede
    IN_PROGRESS = "IN_PROGRESS"  # İşleniyor
    COMPLETED = "COMPLETED"  # Tamamlandı
    FAILED = "FAILED"  # Başarısız
    CANCELLED = "CANCELLED"  # İptal edildi


class GlobalTask(Base):
    """
    Global Task - Tüm agent işlemlerini takip eden merkezi task sistemi
    Parent-Child hiyerarşisi ile çalışır:
    - Parent Task: Tarama/Denetim işlemleri (AUDIT_SCAN)
    - Child Task: Her hata için ayrı düzeltme işlemi (LINK_FIX, etc.)
    """
    __tablename__ = "global_tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Parent-Child ilişkisi
    parent_id = Column(Integer, ForeignKey("global_tasks.id"), nullable=True, index=True)  # Parent task ID
    root_scan_id = Column(Integer, ForeignKey("global_tasks.id"), nullable=True, index=True)  # En üstteki tarama ID'si
    
    # Task bilgileri
    task_type = Column(String(100), nullable=False)  # Görev tipi (AUDIT_SCAN, LINK_FIX, FULL_AUDIT, etc.)
    task_description = Column(Text, nullable=True)  # Görev açıklaması
    
    # Site ve sayfa bilgileri
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    page_id = Column(Integer, ForeignKey("pages.id"), nullable=True)
    page_url = Column(String(500), nullable=True)
    
    # Durum
    status = Column(SQLEnum(GlobalTaskStatus), default=GlobalTaskStatus.PENDING, index=True)
    
    # Agent işlem ID'leri (hangi agent'ın hangi task'ı ile ilişkili)
    observer_task_id = Column(Integer, nullable=True, index=True)
    observer_report_id = Column(Integer, nullable=True, index=True)
    reviewer_queue_id = Column(Integer, nullable=True, index=True)
    dispatcher_task_id = Column(Integer, nullable=True, index=True)
    link_fix_task_id = Column(Integer, nullable=True, index=True)
    controller_task_id = Column(Integer, nullable=True, index=True)
    
    # Sonuç
    result = Column(JSON, nullable=True)  # Final sonuç
    error_message = Column(Text, nullable=True)  # Hata mesajı
    
    # Zaman bilgileri
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # İlişkiler
    site = relationship("Site", backref="global_tasks")
    page = relationship("Page", backref="global_tasks")
    parent = relationship(
        "GlobalTask", 
        remote_side=[id], 
        foreign_keys=[parent_id],  # parent_id kolonunu kullan
        backref="children"
    )  # Self-referencing relationship
    
    def __repr__(self):
        parent_info = f", parent={self.parent_id}" if self.parent_id else ""
        return f"<GlobalTask(id={self.id}, type={self.task_type}, status={self.status.value}{parent_info})>"


def init_global_task_tables():
    """Global Task tablolarını oluştur ve migration yap"""
    from core.database import engine, SessionLocal
    from sqlalchemy import text, inspect
    
    # Tabloları oluştur
    Base.metadata.create_all(bind=engine, tables=[
        GlobalTask.__table__
    ])
    
    # Migration: parent_id ve root_scan_id kolonları yoksa ekle
    db = SessionLocal()
    try:
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('global_tasks')]
        
        if 'parent_id' not in columns:
            print("🔄 global_tasks tablosuna parent_id kolonu ekleniyor...")
            db.execute(text("ALTER TABLE global_tasks ADD COLUMN parent_id INTEGER"))
            db.commit()
            print("✅ parent_id kolonu eklendi")
        
        if 'root_scan_id' not in columns:
            print("🔄 global_tasks tablosuna root_scan_id kolonu ekleniyor...")
            db.execute(text("ALTER TABLE global_tasks ADD COLUMN root_scan_id INTEGER"))
            db.commit()
            print("✅ root_scan_id kolonu eklendi")
    except Exception as e:
        print(f"⚠️ Migration hatası (normal olabilir): {e}")
        db.rollback()
    finally:
        db.close()
    
    print("✅ Global Task tabloları oluşturuldu.")

