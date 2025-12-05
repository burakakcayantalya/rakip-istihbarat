# ============================================
# Link Fixer Agent - Database Models
# ============================================

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, JSON, Enum as SQLEnum
from sqlalchemy.orm import relationship
import enum

from core.database import Base


class LinkFixTaskStatus(enum.Enum):
    """Link düzeltme görev durumları"""
    PENDING = "PENDING"  # Beklemede
    IN_PROGRESS = "IN_PROGRESS"  # İşleniyor
    COMPLETED = "COMPLETED"  # Tamamlandı
    FAILED = "FAILED"  # Başarısız
    CANCELLED = "CANCELLED"  # İptal edildi


class LinkFixTask(Base):
    """
    Link düzeltme görevleri tablosu
    """
    __tablename__ = "link_fix_tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    global_task_id = Column(Integer, ForeignKey("global_tasks.id"), nullable=True, index=True)  # Global task ID
    
    # Görev bilgileri
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    page_id = Column(Integer, ForeignKey("pages.id"), nullable=True)
    page_url = Column(String(500), nullable=False)
    
    # Link bilgileri
    old_url = Column(String(500), nullable=False)  # Eski URL (redirect olan)
    new_url = Column(String(500), nullable=False)  # Yeni URL (final URL)
    link_id = Column(Integer, nullable=True)  # InternalLink ID (eğer varsa)
    
    # Görev durumu
    status = Column(SQLEnum(LinkFixTaskStatus), default=LinkFixTaskStatus.PENDING, index=True)
    
    # WordPress bilgileri
    wp_post_id = Column(Integer, nullable=True)  # WordPress post/page ID
    wp_post_type = Column(String(50), nullable=True)  # 'post' veya 'page'
    
    # Sonuçlar
    result = Column(JSON, nullable=True)  # Düzeltme sonucu
    error_message = Column(Text, nullable=True)  # Hata mesajı
    logs = Column(Text, nullable=True)  # Detaylı loglar
    
    # Zaman bilgileri
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # İlişkiler
    site = relationship("Site", backref="link_fix_tasks")
    page = relationship("Page", backref="link_fix_tasks")
    
    def __repr__(self):
        return f"<LinkFixTask(id={self.id}, status={self.status.value}, old_url={self.old_url[:30]}...)>"


def init_link_fixer_tables():
    """Link Fixer tablolarını oluştur"""
    from core.database import engine, SessionLocal
    from sqlalchemy import text, inspect
    
    # Tabloları oluştur
    Base.metadata.create_all(bind=engine, tables=[
        LinkFixTask.__table__
    ])
    
    # Migration: global_task_id kolonu yoksa ekle
    db = SessionLocal()
    try:
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('link_fix_tasks')]
        
        if 'global_task_id' not in columns:
            print("🔄 link_fix_tasks tablosuna global_task_id kolonu ekleniyor...")
            db.execute(text("ALTER TABLE link_fix_tasks ADD COLUMN global_task_id INTEGER"))
            db.commit()
            print("✅ global_task_id kolonu eklendi (link_fix_tasks)")
    except Exception as e:
        print(f"⚠️ Migration hatası (normal olabilir): {e}")
        db.rollback()
    finally:
        db.close()
    
    print("✅ Link Fixer tabloları oluşturuldu.")





