# ============================================
# Observer Agent - Database Models
# ============================================

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, JSON, Enum as SQLEnum
from sqlalchemy.orm import relationship
import enum

from core.database import Base


class TaskStatus(enum.Enum):
    """Görev durumları"""
    PENDING = "PENDING"  # Beklemede
    RUNNING = "RUNNING"  # Çalışıyor
    COMPLETED = "COMPLETED"  # Tamamlandı
    FAILED = "FAILED"  # Başarısız
    CANCELLED = "CANCELLED"  # İptal edildi


class TaskType(enum.Enum):
    """Görev tipleri"""
    FULL_AUDIT = "FULL_AUDIT"  # Tam denetim
    FRESHNESS_CHECK = "FRESHNESS_CHECK"  # Freshness kontrolü
    LINK_AUDIT = "LINK_AUDIT"  # Link denetimi
    SCHEMA_CHECK = "SCHEMA_CHECK"  # Schema kontrolü
    H1_CHECK = "H1_CHECK"  # H1 kontrolü
    DUPLICATE_LINK_CHECK = "DUPLICATE_LINK_CHECK"  # Duplicate link kontrolü
    NEW_CONTENT_CHECK = "NEW_CONTENT_CHECK"  # Yeni içerik kontrolü


class ReportSeverity(enum.Enum):
    """Rapor önem seviyeleri"""
    ERROR = "ERROR"  # Hata
    WARNING = "WARNING"  # Uyarı
    INFO = "INFO"  # Bilgi


class ObserverTask(Base):
    """
    Observer görevleri tablosu
    """
    __tablename__ = "observer_tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    global_task_id = Column(Integer, ForeignKey("global_tasks.id"), nullable=True, index=True)  # Global task ID
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    task_type = Column(SQLEnum(TaskType), nullable=False)
    status = Column(SQLEnum(TaskStatus), default=TaskStatus.PENDING)
    
    # İlerleme bilgileri
    total_items = Column(Integer, default=0)  # Toplam işlenecek öğe sayısı
    processed_items = Column(Integer, default=0)  # İşlenen öğe sayısı
    progress_percentage = Column(Integer, default=0)  # İlerleme yüzdesi
    
    # Görev detayları
    description = Column(Text, nullable=True)  # Görev açıklaması
    current_item = Column(String(500), nullable=True)  # Şu an işlenen öğe
    
    # Sonuçlar
    reports_count = Column(Integer, default=0)  # Oluşturulan rapor sayısı
    errors_count = Column(Integer, default=0)  # Hata sayısı
    error_log = Column(Text, nullable=True)  # Hata logları (detaylı)
    
    # Zaman bilgileri
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # İlişkiler
    site = relationship("Site", backref="observer_tasks")
    reports = relationship("ObserverReport", back_populates="task", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<ObserverTask(id={self.id}, type={self.task_type.value}, status={self.status.value})>"


class ObserverReport(Base):
    """
    Observer raporları tablosu
    """
    __tablename__ = "observer_reports"
    
    id = Column(Integer, primary_key=True, index=True)
    global_task_id = Column(Integer, ForeignKey("global_tasks.id"), nullable=True, index=True)  # Global task ID
    task_id = Column(Integer, ForeignKey("observer_tasks.id"), nullable=False)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    page_id = Column(Integer, ForeignKey("pages.id"), nullable=True)  # Sayfa ID (varsa)
    
    # Rapor detayları
    rule_name = Column(String(255), nullable=False)  # Kural adı (örn: "H1_COUNT", "SCHEMA_MARKUP")
    severity = Column(SQLEnum(ReportSeverity), nullable=False)
    message = Column(Text, nullable=False)  # Rapor mesajı
    details = Column(JSON, nullable=True)  # Ek detaylar (JSON formatında)
    
    # Sayfa bilgileri (eğer page_id yoksa)
    page_url = Column(String(500), nullable=True)  # Sayfa URL'i
    
    # Zaman bilgisi
    found_at = Column(DateTime, default=datetime.utcnow)
    
    # İlişkiler
    task = relationship("ObserverTask", back_populates="reports")
    site = relationship("Site", backref="observer_reports")
    page = relationship("Page", backref="observer_reports")
    
    def __repr__(self):
        return f"<ObserverReport(id={self.id}, rule={self.rule_name}, severity={self.severity.value})>"


class ObserverRule(Base):
    """
    Observer kuralları tablosu (dinamik kural yönetimi için)
    """
    __tablename__ = "observer_rules"
    
    id = Column(Integer, primary_key=True, index=True)
    rule_name = Column(String(255), unique=True, nullable=False)  # Kural adı
    rule_type = Column(String(100), nullable=False)  # Kural tipi
    is_active = Column(Boolean, default=True)  # Aktif mi?
    priority = Column(Integer, default=0)  # Öncelik (yüksek sayı = yüksek öncelik)
    
    # Kural konfigürasyonu (JSON)
    config = Column(JSON, nullable=True)  # Kural ayarları
    
    # Meta bilgiler
    description = Column(Text, nullable=True)  # Kural açıklaması
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<ObserverRule(id={self.id}, name={self.rule_name}, active={self.is_active})>"


def init_observer_tables():
    """Observer tablolarını oluştur ve migration yap"""
    from core.database import engine, SessionLocal
    from sqlalchemy import text, inspect
    
    # Tabloları oluştur
    Base.metadata.create_all(bind=engine, tables=[
        ObserverTask.__table__,
        ObserverReport.__table__,
        ObserverRule.__table__
    ])
    
    # Migration: error_log kolonu yoksa ekle
    db = SessionLocal()
    try:
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('observer_tasks')]
        
        if 'error_log' not in columns:
            print("🔄 observer_tasks tablosuna error_log kolonu ekleniyor...")
            db.execute(text("ALTER TABLE observer_tasks ADD COLUMN error_log TEXT"))
            db.commit()
            print("✅ error_log kolonu eklendi")
        
        # Migration: global_task_id kolonu yoksa ekle
        if 'global_task_id' not in columns:
            print("🔄 observer_tasks tablosuna global_task_id kolonu ekleniyor...")
            try:
                db.execute(text("ALTER TABLE observer_tasks ADD COLUMN global_task_id INTEGER"))
                db.commit()
                print("✅ global_task_id kolonu eklendi (observer_tasks)")
            except Exception as e:
                print(f"⚠️ global_task_id ekleme hatası: {e}")
                db.rollback()
        
        # Migration: observer_reports tablosuna global_task_id ekle
        try:
            report_columns = [col['name'] for col in inspector.get_columns('observer_reports')]
            if 'global_task_id' not in report_columns:
                print("🔄 observer_reports tablosuna global_task_id kolonu ekleniyor...")
                db.execute(text("ALTER TABLE observer_reports ADD COLUMN global_task_id INTEGER"))
                db.commit()
                print("✅ global_task_id kolonu eklendi (observer_reports)")
        except Exception as e:
            print(f"⚠️ observer_reports migration hatası: {e}")
            db.rollback()
    except Exception as e:
        print(f"⚠️ Migration hatası (normal olabilir): {e}")
        db.rollback()
    finally:
        db.close()

