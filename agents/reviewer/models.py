# ============================================
# Reviewer Agent - Database Models
# ============================================

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, JSON, Enum as SQLEnum
from sqlalchemy.orm import relationship
import enum

from core.database import Base, Site, Page
# Mappers'ın zamanında yüklenebilmesi için Observer modellerini içe al
from agents.observer.models import ObserverReport


class QueueStatus(enum.Enum):
    """Kuyruk durumları"""
    PENDING = "PENDING"  # Beklemede
    IN_PROGRESS = "IN_PROGRESS"  # İşleniyor
    COMPLETED = "COMPLETED"  # Tamamlandı
    CANCELLED = "CANCELLED"  # İptal edildi
    SKIPPED = "SKIPPED"  # Atlandı


class PriorityScore(enum.Enum):
    """Öncelik skorları (yüksek sayı = yüksek öncelik)"""
    LINK_AUDIT = 5  # Link Denetimi - En yüksek öncelik
    H1_CHECK = 4  # H1 Denetimi
    FRESHNESS_CHECK = 3  # Freshness Kontrolü
    DUPLICATE_LINK_CHECK = 2  # Duplicate Kontrol
    SCHEMA_CHECK = 1  # Schema Kontrol - En düşük öncelik
    UNKNOWN = 0  # Bilinmeyen kural


class ReviewerQueue(Base):
    """
    Reviewer kuyruğu - Observer'dan gelen raporlar önceliklendirilmiş sırada
    """
    __tablename__ = "reviewer_queue"
    
    id = Column(Integer, primary_key=True, index=True)
    global_task_id = Column(Integer, ForeignKey("global_tasks.id"), nullable=True, index=True)  # Global task ID
    
    # Observer raporuna referans
    observer_report_id = Column(Integer, ForeignKey("observer_reports.id"), nullable=False)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    page_id = Column(Integer, ForeignKey("pages.id"), nullable=True)
    
    # Öncelik ve durum
    priority_score = Column(Integer, nullable=False, index=True)  # 1-5 arası öncelik skoru
    status = Column(SQLEnum(QueueStatus), default=QueueStatus.PENDING, index=True)
    
    # Kural bilgisi
    rule_name = Column(String(255), nullable=False)  # Observer'dan gelen kural adı
    severity = Column(String(50), nullable=False)  # ERROR, WARNING, INFO
    
    # Sayfa bilgileri
    page_url = Column(String(500), nullable=True)
    
    # Aksiyon planı
    action_plan = Column(Text, nullable=True)  # Ne yapılması gerektiği
    action_type = Column(String(100), nullable=True)  # FIX_LINK, ADD_H1, UPDATE_CONTENT, etc.
    
    # İşlem bilgileri
    assigned_to = Column(String(100), nullable=True)  # Kim işliyor (gelecekte kullanıcı sistemi için)
    notes = Column(Text, nullable=True)  # Notlar
    
    # Zaman bilgileri
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # İlişkiler
    observer_report = relationship("ObserverReport", backref="reviewer_queue_items")
    site = relationship("Site", backref="reviewer_queue_items")
    page = relationship("Page", backref="reviewer_queue_items")
    
    def __repr__(self):
        return f"<ReviewerQueue(id={self.id}, priority={self.priority_score}, status={self.status.value})>"


def get_priority_score(rule_name: str) -> int:
    """
    Kural adına göre öncelik skoru döndürür
    """
    rule_mapping = {
        "LINK_AUDIT": PriorityScore.LINK_AUDIT.value,
        "H1_CHECK": PriorityScore.H1_CHECK.value,
        "H1_COUNT": PriorityScore.H1_CHECK.value,  # Alternatif isim
        "FRESHNESS_CHECK": PriorityScore.FRESHNESS_CHECK.value,
        "DUPLICATE_LINK_CHECK": PriorityScore.DUPLICATE_LINK_CHECK.value,
        "SCHEMA_CHECK": PriorityScore.SCHEMA_CHECK.value,
        "SCHEMA_MARKUP": PriorityScore.SCHEMA_CHECK.value,  # Alternatif isim
    }
    
    return rule_mapping.get(rule_name, PriorityScore.UNKNOWN.value)


def get_action_plan(rule_name: str, severity: str, details: dict = None) -> tuple:
    """
    Kural ve severity'ye göre aksiyon planı ve tipi döndürür
    Returns: (action_plan, action_type)
    """
    action_plans = {
        "LINK_AUDIT": {
            "ERROR": ("Kırık veya yönlendiren linkleri düzelt. Link URL'lerini güncelleyin veya kaldırın.", "FIX_LINK"),
            "WARNING": ("Link durumunu kontrol edin ve gerekirse güncelleyin.", "CHECK_LINK"),
        },
        "H1_CHECK": {
            "ERROR": ("Sayfaya tam olarak 1 adet H1 etiketi ekleyin. Eksikse ekleyin, fazlaysa fazlaları kaldırın.", "FIX_H1"),
            "WARNING": ("H1 etiket sayısını kontrol edin.", "CHECK_H1"),
        },
        "H1_COUNT": {
            "ERROR": ("Sayfaya tam olarak 1 adet H1 etiketi ekleyin. Eksikse ekleyin, fazlaysa fazlaları kaldırın.", "FIX_H1"),
            "WARNING": ("H1 etiket sayısını kontrol edin.", "CHECK_H1"),
        },
        "FRESHNESS_CHECK": {
            "ERROR": ("İçeriği güncelleyin. Sayfa çok eski, yeni bilgiler ekleyin veya tarihi güncelleyin.", "UPDATE_CONTENT"),
            "WARNING": ("İçeriği gözden geçirin ve gerekirse güncelleyin.", "REVIEW_CONTENT"),
        },
        "DUPLICATE_LINK_CHECK": {
            "ERROR": ("Aynı sayfaya yönlendiren tekrarlayan linkleri kaldırın veya birleştirin.", "REMOVE_DUPLICATE_LINKS"),
            "WARNING": ("Tekrarlayan linkleri gözden geçirin.", "REVIEW_DUPLICATE_LINKS"),
        },
        "SCHEMA_CHECK": {
            "ERROR": ("Sayfaya uygun Schema Markup ekleyin (JSON-LD formatında).", "ADD_SCHEMA"),
            "WARNING": ("Schema Markup'ı kontrol edin ve gerekirse güncelleyin.", "CHECK_SCHEMA"),
        },
        "SCHEMA_MARKUP": {
            "ERROR": ("Sayfaya uygun Schema Markup ekleyin (JSON-LD formatında).", "ADD_SCHEMA"),
            "WARNING": ("Schema Markup'ı kontrol edin ve gerekirse güncelleyin.", "CHECK_SCHEMA"),
        },
    }
    
    rule_actions = action_plans.get(rule_name, {})
    action_info = rule_actions.get(severity, ("Durumu kontrol edin ve gerekli düzenlemeleri yapın.", "REVIEW"))
    
    return action_info


def init_reviewer_tables():
    """Reviewer tablolarını oluştur"""
    from core.database import engine, SessionLocal
    from sqlalchemy import text, inspect
    
    # Tabloları oluştur
    Base.metadata.create_all(bind=engine, tables=[
        ReviewerQueue.__table__
    ])
    
    # Migration: global_task_id kolonu yoksa ekle
    db = SessionLocal()
    try:
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('reviewer_queue')]
        
        if 'global_task_id' not in columns:
            print("🔄 reviewer_queue tablosuna global_task_id kolonu ekleniyor...")
            db.execute(text("ALTER TABLE reviewer_queue ADD COLUMN global_task_id INTEGER"))
            db.commit()
            print("✅ global_task_id kolonu eklendi (reviewer_queue)")
    except Exception as e:
        print(f"⚠️ Migration hatası (normal olabilir): {e}")
        db.rollback()
    finally:
        db.close()
    
    print("✅ Reviewer tabloları oluşturuldu.")


