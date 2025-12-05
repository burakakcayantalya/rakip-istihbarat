# ============================================
# Dispatcher Agent - Database Models
# ============================================

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, JSON, Enum as SQLEnum
from sqlalchemy.orm import relationship
import enum

from core.database import Base


class DispatcherTaskStatus(enum.Enum):
    """Dağıtıcı görev durumları"""
    PENDING = "PENDING"  # Beklemede
    ASSIGNED = "ASSIGNED"  # Agent'a atandı
    IN_PROGRESS = "IN_PROGRESS"  # Agent tarafından işleniyor
    COMPLETED = "COMPLETED"  # Tamamlandı
    FAILED = "FAILED"  # Başarısız
    CANCELLED = "CANCELLED"  # İptal edildi


class AgentType(enum.Enum):
    """Agent tipleri"""
    FIXER = "FIXER"  # Link Fixer Agent - Tüm link düzeltme görevleri (301, 404, 410, redirect, broken)
    AI_HELPER = "AI_HELPER"  # AI Helper Agent - Duplicate link analizi ve internal linking optimizasyonu
    UNKNOWN = "UNKNOWN"  # Bilinmeyen (desteklenmeyen)


class DispatcherTask(Base):
    """
    Dispatcher görevleri tablosu
    Görevleri alır ve uygun agent'a dağıtır
    """
    __tablename__ = "dispatcher_tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    global_task_id = Column(Integer, ForeignKey("global_tasks.id"), nullable=True, index=True)  # Global task ID
    
    # Görev bilgileri
    task_name = Column(String(255), nullable=False)  # Görev adı
    task_type = Column(String(100), nullable=False)  # Görev tipi (örn: "FIX_LINK", "ADD_H1")
    task_description = Column(Text, nullable=True)  # Görev açıklaması
    
    # Kaynak bilgileri (görevin nereden geldiği)
    source_type = Column(String(100), nullable=True)  # "REVIEWER_QUEUE", "MANUAL", "SCHEDULED"
    source_id = Column(Integer, nullable=True)  # Kaynak ID (örn: ReviewerQueue.id)
    
    # Site ve sayfa bilgileri
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    page_id = Column(Integer, ForeignKey("pages.id"), nullable=True)
    page_url = Column(String(500), nullable=True)
    
    # Agent atama
    assigned_agent = Column(SQLEnum(AgentType), nullable=True)  # Hangi agent'a atandı
    agent_task_id = Column(Integer, nullable=True)  # Agent'ın kendi görev ID'si
    
    # Görev durumu
    status = Column(SQLEnum(DispatcherTaskStatus), default=DispatcherTaskStatus.PENDING, index=True)
    priority = Column(Integer, default=0, index=True)  # Öncelik (0-10 arası)
    
    # Görev parametreleri (JSON)
    task_params = Column(JSON, nullable=True)  # Agent'a gönderilecek parametreler
    
    # Sonuçlar
    result = Column(JSON, nullable=True)  # Agent'tan gelen sonuç
    error_message = Column(Text, nullable=True)  # Hata mesajı
    
    # Notlar
    notes = Column(Text, nullable=True)
    
    # Zaman bilgileri
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    assigned_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # İlişkiler
    site = relationship("Site", backref="dispatcher_tasks")
    page = relationship("Page", backref="dispatcher_tasks")
    
    def __repr__(self):
        return f"<DispatcherTask(id={self.id}, type={self.task_type}, status={self.status.value}, agent={self.assigned_agent.value if self.assigned_agent else None})>"


class AgentRoutingRule(Base):
    """
    Agent yönlendirme kuralları
    Hangi görev tipinin hangi agent'a gideceğini belirler
    """
    __tablename__ = "agent_routing_rules"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Kural bilgileri
    task_type = Column(String(100), nullable=False, unique=True, index=True)  # Görev tipi
    agent_type = Column(SQLEnum(AgentType), nullable=False)  # Hangi agent'a gidecek
    
    # Kural durumu
    is_active = Column(Boolean, default=True)
    priority = Column(Integer, default=0)  # Kural önceliği (yüksek sayı = önce kontrol et)
    
    # Kural koşulları (JSON)
    conditions = Column(JSON, nullable=True)  # Ek koşullar (gelecekte kullanılabilir)
    
    # Meta bilgiler
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<AgentRoutingRule(id={self.id}, task_type={self.task_type}, agent={self.agent_type.value})>"


def get_agent_for_task(task_type: str, db=None) -> AgentType:
    """
    Görev tipine göre uygun agent'ı döndürür
    
    Args:
        task_type: Görev tipi (örn: "FIX_LINK", "ADD_H1")
        db: Database session (opsiyonel, routing rules için)
    
    Returns:
        AgentType enum değeri
    """
    # Önce database'deki routing rules'a bak
    if db:
        try:
            from sqlalchemy import desc
            rule = db.query(AgentRoutingRule).filter(
                AgentRoutingRule.task_type == task_type,
                AgentRoutingRule.is_active == True
            ).order_by(desc(AgentRoutingRule.priority)).first()
            
            if rule:
                try:
                    # Eski enum değerlerini kontrol et ve FIXER'a çevir
                    agent_type = rule.agent_type
                    if agent_type:
                        agent_value = agent_type.value if hasattr(agent_type, 'value') else str(agent_type)
                        # Eski değerler (OBSERVER, REVIEWER, ANALYZER) varsa FIXER'a çevir
                        if agent_value not in ['FIXER', 'AI_HELPER', 'UNKNOWN']:
                            # Eski değeri FIXER'a güncelle (link düzeltme görevleri için)
                            rule.agent_type = AgentType.FIXER
                            db.commit()
                            return AgentType.FIXER
                        return agent_type
                except (AttributeError, ValueError) as enum_error:
                    # Enum hatası varsa (eski değer), FIXER'a çevir
                    try:
                        rule.agent_type = AgentType.FIXER
                        db.commit()
                        return AgentType.FIXER
                    except:
                        pass
        except Exception as e:
            # Enum hatası varsa, eski değerleri temizle
            try:
                if db:
                    # Tüm eski routing rules'ları temizle
                    old_rules = db.query(AgentRoutingRule).all()
                    for old_rule in old_rules:
                        try:
                            # Önce enum değerini okumaya çalış
                            agent_value = old_rule.agent_type.value if hasattr(old_rule.agent_type, 'value') else str(old_rule.agent_type)
                            if agent_value not in ['FIXER', 'AI_HELPER', 'UNKNOWN']:
                                old_rule.agent_type = AgentType.FIXER
                        except (AttributeError, ValueError):
                            # Enum okuma hatası varsa direkt FIXER'a çevir
                            try:
                                old_rule.agent_type = AgentType.FIXER
                            except:
                                pass
                    db.commit()
            except:
                pass
    
    # Default routing
    # Observer, Reviewer, Analyzer kendi görevlerini kendileri yönetir
    default_routing = {
        # Link düzeltme görevleri -> Link Fixer
        "FIX_LINK": AgentType.FIXER,
        "FIX_301_LINK": AgentType.FIXER,
        "FIX_404_LINK": AgentType.FIXER,
        "FIX_410_LINK": AgentType.FIXER,
        "FIX_REDIRECT_LINK": AgentType.FIXER,
        "FIX_BROKEN_LINK": AgentType.FIXER,
        # Duplicate link görevleri -> AI Helper
        "ANALYZE_DUPLICATE_LINKS": AgentType.AI_HELPER,
        "FIX_DUPLICATE_LINKS": AgentType.AI_HELPER,
    }
    
    return default_routing.get(task_type, AgentType.UNKNOWN)


def init_dispatcher_tables():
    """Dispatcher tablolarını oluştur"""
    from core.database import engine
    from sqlalchemy import desc, text
    
    # Tabloları oluştur
    Base.metadata.create_all(bind=engine, tables=[
        DispatcherTask.__table__,
        AgentRoutingRule.__table__
    ])
    
    # Default routing rules ekle ve eski değerleri temizle
    from core.database import SessionLocal
    db = SessionLocal()
    try:
        inspector = inspect(engine)
        
        # Migration: global_task_id kolonu yoksa ekle
        try:
            columns = [col['name'] for col in inspector.get_columns('dispatcher_tasks')]
            if 'global_task_id' not in columns:
                print("🔄 dispatcher_tasks tablosuna global_task_id kolonu ekleniyor...")
                db.execute(text("ALTER TABLE dispatcher_tasks ADD COLUMN global_task_id INTEGER"))
                db.commit()
                print("✅ global_task_id kolonu eklendi (dispatcher_tasks)")
        except Exception as e:
            print(f"⚠️ dispatcher_tasks migration hatası: {e}")
            db.rollback()
        
        # Migration: global_task_id kolonu yoksa ekle (tekrar kontrol)
        try:
            columns = [col['name'] for col in inspector.get_columns('dispatcher_tasks')]
            if 'global_task_id' not in columns:
                print("🔄 dispatcher_tasks tablosuna global_task_id kolonu ekleniyor (ikinci deneme)...")
                db.execute(text("ALTER TABLE dispatcher_tasks ADD COLUMN global_task_id INTEGER"))
                db.commit()
                print("✅ global_task_id kolonu eklendi (dispatcher_tasks)")
        except Exception as e:
            print(f"⚠️ dispatcher_tasks migration hatası (ikinci deneme): {e}")
            db.rollback()
        # Önce eski enum değerlerini direkt SQL ile temizle (SQLAlchemy ORM kullanmadan)
        try:
            # DispatcherTask'lardaki eski enum değerlerini temizle
            db.execute(text("""
                UPDATE dispatcher_tasks 
                SET assigned_agent = CASE 
                    WHEN task_type LIKE '%DUPLICATE%' THEN 'AI_HELPER'
                    ELSE 'FIXER'
                END
                WHERE assigned_agent IN ('OBSERVER', 'REVIEWER', 'ANALYZER')
            """))
            
            # AgentRoutingRule'lardaki eski enum değerlerini temizle
            db.execute(text("""
                UPDATE agent_routing_rules 
                SET agent_type = 'FIXER' 
                WHERE agent_type IN ('OBSERVER', 'REVIEWER', 'ANALYZER')
            """))
            
            db.commit()
            print("✅ Eski enum değerleri temizlendi (SQL ile)")
        except Exception as cleanup_error:
            print(f"⚠️ SQL temizleme hatası: {cleanup_error}")
            db.rollback()
        
        # Eğer kurallar yoksa ekle
        existing_rules = db.query(AgentRoutingRule).count()
        if existing_rules == 0:
            default_rules = [
                AgentRoutingRule(
                    task_type="FIX_LINK",
                    agent_type=AgentType.FIXER,
                    is_active=True,
                    priority=10,
                    description="Kırık veya yönlendiren linkleri düzelt"
                ),
                AgentRoutingRule(
                    task_type="FIX_301_LINK",
                    agent_type=AgentType.FIXER,
                    is_active=True,
                    priority=10,
                    description="301 redirect linklerini düzelt"
                ),
                AgentRoutingRule(
                    task_type="FIX_404_LINK",
                    agent_type=AgentType.FIXER,
                    is_active=True,
                    priority=10,
                    description="404 hata veren linkleri düzelt"
                ),
                AgentRoutingRule(
                    task_type="FIX_410_LINK",
                    agent_type=AgentType.FIXER,
                    is_active=True,
                    priority=10,
                    description="410 hata veren linkleri düzelt"
                ),
                AgentRoutingRule(
                    task_type="FIX_REDIRECT_LINK",
                    agent_type=AgentType.FIXER,
                    is_active=True,
                    priority=10,
                    description="Redirect veren linkleri düzelt"
                ),
                AgentRoutingRule(
                    task_type="FIX_BROKEN_LINK",
                    agent_type=AgentType.FIXER,
                    is_active=True,
                    priority=10,
                    description="Kırık linkleri düzelt"
                ),
                AgentRoutingRule(
                    task_type="ANALYZE_DUPLICATE_LINKS",
                    agent_type=AgentType.AI_HELPER,
                    is_active=True,
                    priority=10,
                    description="Duplicate link analizi yap ve internal linking önerileri sun"
                ),
                AgentRoutingRule(
                    task_type="FIX_DUPLICATE_LINKS",
                    agent_type=AgentType.AI_HELPER,
                    is_active=True,
                    priority=10,
                    description="Duplicate linkleri düzelt ve internal linking optimizasyonu yap"
                ),
            ]
            
            for rule in default_rules:
                db.add(rule)
            db.commit()
            print("✅ Default routing rules eklendi.")
    except Exception as e:
        print(f"⚠️ Routing rules eklenirken hata: {e}")
        db.rollback()
    finally:
        db.close()
    
    print("✅ Dispatcher tabloları oluşturuldu.")

