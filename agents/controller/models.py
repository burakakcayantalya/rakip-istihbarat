# ============================================
# Controller Agent - Database Models
# ============================================
# Tamamlanan görevleri kontrol eder ve doğrular
# Observer'a gönderir, sonucu değerlendirir ve işaretler

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, JSON, Enum as SQLEnum
from sqlalchemy.orm import relationship
import enum

from core.database import Base


class VerificationStatus(enum.Enum):
    """Doğrulama durumları"""
    PENDING = "PENDING"  # Beklemede - Agent'tan bildirim alındı
    VERIFYING = "VERIFYING"  # Doğrulanıyor - Observer'a gönderildi
    VERIFIED_SUCCESS = "VERIFIED_SUCCESS"  # Doğrulandı - Görev başarıyla tamamlanmış
    VERIFIED_FAILED = "VERIFIED_FAILED"  # Doğrulandı - Görev tamamlanmamış
    VERIFICATION_ERROR = "VERIFICATION_ERROR"  # Doğrulama hatası
    RETRY_ASSIGNED = "RETRY_ASSIGNED"  # Tekrar atandı


class ControllerTask(Base):
    """
    Controller görevleri tablosu
    Agent'lardan gelen tamamlanma bildirimlerini alır ve doğrular
    """
    __tablename__ = "controller_tasks"

    id = Column(Integer, primary_key=True, index=True)
    global_task_id = Column(Integer, ForeignKey("global_tasks.id"), nullable=True, index=True)  # Global task ID

    # Kaynak görev bilgileri
    source_agent = Column(String(100), nullable=False)  # Hangi agent'tan geldi (FIXER, AI_HELPER)
    source_task_id = Column(Integer, nullable=False)  # Agent'ın task ID'si
    dispatcher_task_id = Column(Integer, ForeignKey("dispatcher_tasks.id"), nullable=True)  # Dispatcher task ID

    # Site ve sayfa bilgileri
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    page_id = Column(Integer, ForeignKey("pages.id"), nullable=True)
    page_url = Column(String(500), nullable=False)

    # Görev detayları
    task_description = Column(Text, nullable=True)  # Görevin açıklaması
    task_type = Column(String(100), nullable=False)  # Görev tipi (FIX_LINK, etc.)
    original_issue = Column(JSON, nullable=True)  # Orijinal sorun (Observer'dan gelen)

    # Agent'tan gelen bilgi
    agent_report = Column(JSON, nullable=True)  # Agent'ın raporladığı sonuç
    agent_completion_time = Column(DateTime, nullable=True)  # Agent'ın tamamlama zamanı

    # Doğrulama durumu
    status = Column(SQLEnum(VerificationStatus), default=VerificationStatus.PENDING, index=True)

    # Observer doğrulama bilgileri
    observer_task_id = Column(Integer, nullable=True)  # Observer'a gönderilen task ID
    observer_report = Column(JSON, nullable=True)  # Observer'dan gelen doğrulama raporu
    observer_verification_time = Column(DateTime, nullable=True)  # Observer'ın doğrulama zamanı

    # Tekrar deneme bilgileri
    retry_count = Column(Integer, default=0)  # Kaç kez tekrar denendi
    retry_notes = Column(Text, nullable=True)  # Tekrar deneme notları

    # Sonuç
    is_verified = Column(Boolean, default=False)  # Doğrulandı mı?
    verification_notes = Column(Text, nullable=True)  # Doğrulama notları

    # Görev hikayesi (log)
    task_history = Column(JSON, nullable=True, default=list)  # Görevin baştan sona tüm geçmişi

    # Zaman bilgileri
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    verification_started_at = Column(DateTime, nullable=True)
    verification_completed_at = Column(DateTime, nullable=True)

    # İlişkiler
    site = relationship("Site", backref="controller_tasks")
    page = relationship("Page", backref="controller_tasks")

    def __repr__(self):
        return f"<ControllerTask(id={self.id}, source_agent={self.source_agent}, status={self.status.value})>"

    def add_to_history(self, event_type: str, message: str, data: dict = None):
        """Görev hikayesine olay ekle"""
        if self.task_history is None:
            self.task_history = []

        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type,
            "message": message,
            "data": data or {}
        }

        # JSON olarak saklanmış listeyi Python listesine çevir
        if isinstance(self.task_history, str):
            import json
            try:
                self.task_history = json.loads(self.task_history)
            except:
                self.task_history = []

        self.task_history.append(event)


class ControllerStats(Base):
    """
    Controller istatistikleri tablosu
    Günlük/haftalık/aylık başarı oranları
    """
    __tablename__ = "controller_stats"

    id = Column(Integer, primary_key=True, index=True)

    # Tarih bilgisi
    date = Column(DateTime, default=datetime.utcnow, index=True)
    period_type = Column(String(50), default="daily")  # daily, weekly, monthly

    # İstatistikler
    total_verifications = Column(Integer, default=0)  # Toplam doğrulama
    verified_success = Column(Integer, default=0)  # Başarılı doğrulamalar
    verified_failed = Column(Integer, default=0)  # Başarısız doğrulamalar
    retry_assigned = Column(Integer, default=0)  # Tekrar atanan görevler
    verification_errors = Column(Integer, default=0)  # Doğrulama hataları

    # Başarı oranı (%)
    success_rate = Column(Integer, default=0)  # Başarı yüzdesi

    # Agent bazında istatistikler
    fixer_success = Column(Integer, default=0)
    fixer_failed = Column(Integer, default=0)
    ai_helper_success = Column(Integer, default=0)
    ai_helper_failed = Column(Integer, default=0)

    def __repr__(self):
        return f"<ControllerStats(date={self.date}, success_rate={self.success_rate}%)>"


def init_controller_tables():
    """Controller tablolarını oluştur"""
    from core.database import engine, SessionLocal
    from sqlalchemy import text, inspect

    # Tabloları oluştur
    Base.metadata.create_all(bind=engine, tables=[
        ControllerTask.__table__,
        ControllerStats.__table__
    ])
    
    # Migration: global_task_id kolonu yoksa ekle
    db = SessionLocal()
    try:
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('controller_tasks')]
        
        if 'global_task_id' not in columns:
            print("🔄 controller_tasks tablosuna global_task_id kolonu ekleniyor...")
            db.execute(text("ALTER TABLE controller_tasks ADD COLUMN global_task_id INTEGER"))
            db.commit()
            print("✅ global_task_id kolonu eklendi (controller_tasks)")
    except Exception as e:
        print(f"⚠️ Migration hatası (normal olabilir): {e}")
        db.rollback()
    finally:
        db.close()

    print("✅ Controller tabloları oluşturuldu.")
