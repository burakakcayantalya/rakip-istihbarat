# ============================================
# Entity Analyzer - Veritabanı Modelleri
# ============================================

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum as SQLEnum, Boolean
from sqlalchemy.orm import relationship
import enum

from core.database import Base


class MatchType(enum.Enum):
    """Entity eşleşme tipleri"""
    EXACT = "EXACT"  # Tam eşleşme
    PARTIAL = "PARTIAL"  # Yarım eşleşme
    LOW = "LOW"  # Düşük eşleşme


class EntitySearch(Base):
    """Entity arama kayıtları"""
    __tablename__ = "entity_searches"
    
    id = Column(Integer, primary_key=True, index=True)
    search_term = Column(String(255), nullable=False, index=True)  # Kullanıcının aradığı kelime
    status = Column(String(50), default="pending")  # pending, processing, completed, error, cancelled
    cancelled = Column(Boolean, default=False)  # İptal edildi mi?
    is_cleaned = Column(Boolean, default=False)  # Temizlik yapıldı mı?
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # İlişkiler
    results = relationship("EntityResult", back_populates="search", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<EntitySearch(id={self.id}, term='{self.search_term}', status='{self.status}')>"


class EntityResult(Base):
    """Entity analiz sonuçları"""
    __tablename__ = "entity_results"
    
    id = Column(Integer, primary_key=True, index=True)
    search_id = Column(Integer, ForeignKey("entity_searches.id"), nullable=False)
    
    # Kaynak bilgisi
    source_type = Column(String(50), nullable=False)  # "competitor" veya "google"
    source_site_id = Column(Integer, nullable=True)  # Rakip site ID (competitor için)
    source_url = Column(String(500), nullable=False)  # URL
    is_ai_match = Column(Boolean, default=False)  # Gemini AI ile bulunan entity mi?
    
    # Meta bilgileri
    meta_title = Column(Text, nullable=True)
    meta_description = Column(Text, nullable=True)
    
    # Entity bilgileri
    entity_name = Column(String(255), nullable=False)  # Wikipedia'dan gelen entity adı
    entity_url = Column(String(500), nullable=True)  # Wikipedia URL
    match_type = Column(SQLEnum(MatchType), nullable=False)  # Eşleşme tipi
    match_score = Column(Integer, default=0)  # Eşleşme skoru (0-100)
    
    # Ekstra bilgiler
    matched_words = Column(Text, nullable=True)  # Eşleşen kelimeler (JSON string)
    wikipedia_summary = Column(Text, nullable=True)  # Wikipedia özeti
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # İlişkiler
    search = relationship("EntitySearch", back_populates="results")
    
    def __repr__(self):
        return f"<EntityResult(id={self.id}, entity='{self.entity_name}', match='{self.match_type.value}')>"


class EntitySearchLog(Base):
    """Entity arama log kayıtları"""
    __tablename__ = "entity_search_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    search_id = Column(Integer, ForeignKey("entity_searches.id"), nullable=False)
    level = Column(String(20), nullable=False)  # info, warning, error, success
    message = Column(Text, nullable=False)
    details = Column(Text, nullable=True)  # Ekstra detaylar (JSON string)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # İlişkiler
    search = relationship("EntitySearch")
    
    def __repr__(self):
        return f"<EntitySearchLog(id={self.id}, level='{self.level}', message='{self.message[:50]}...')>"


def init_entity_tables():
    """Entity tablolarını oluştur"""
    from core.database import engine
    Base.metadata.create_all(bind=engine, tables=[EntitySearch.__table__, EntityResult.__table__, EntitySearchLog.__table__])
    
    # Migration: entity_searches ve entity_results tablolarını güncelle (eğer kolonlar yoksa)
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            # entity_searches tablosu için
            result = conn.execute(text("PRAGMA table_info(entity_searches)"))
            columns = [row[1] for row in result]
            if 'status' not in columns:
                conn.execute(text("ALTER TABLE entity_searches ADD COLUMN status VARCHAR(50) DEFAULT 'pending'"))
                conn.commit()
                print("✅ Entity Analyzer: status kolonu eklendi")
            if 'cancelled' not in columns:
                conn.execute(text("ALTER TABLE entity_searches ADD COLUMN cancelled BOOLEAN DEFAULT 0"))
                conn.commit()
                print("✅ Entity Analyzer: cancelled kolonu eklendi")
            if 'is_cleaned' not in columns:
                conn.execute(text("ALTER TABLE entity_searches ADD COLUMN is_cleaned BOOLEAN DEFAULT 0"))
                conn.commit()
                print("✅ Entity Analyzer: is_cleaned kolonu eklendi")

            # entity_results tablosu için
            result = conn.execute(text("PRAGMA table_info(entity_results)"))
            result_columns = [row[1] for row in result]
            if 'is_ai_match' not in result_columns:
                conn.execute(text("ALTER TABLE entity_results ADD COLUMN is_ai_match BOOLEAN DEFAULT 0"))
                conn.commit()
                print("✅ Entity Analyzer: entity_results.is_ai_match kolonu eklendi")
    except Exception as e:
        print(f"⚠️ Entity Analyzer migration hatası (normal olabilir): {e}")

