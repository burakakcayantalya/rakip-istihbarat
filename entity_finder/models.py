# ============================================
# Entity Finder - Database Models
# ============================================

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from core.database import Base


class EntityFinder(Base):
    """Entity bulma araması"""
    __tablename__ = "entity_finders"
    
    id = Column(Integer, primary_key=True, index=True)
    keyword = Column(String(255), nullable=False, index=True)  # Örn: "dentistry"
    wikipedia_url = Column(String(500))  # Ana Wikipedia sayfası URL'i
    status = Column(String(50), default="pending")  # pending, processing, completed, error
    total_links_found = Column(Integer, default=0)  # Bulunan toplam internal link sayısı
    total_entities_found = Column(Integer, default=0)  # Bulunan toplam entity sayısı
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    found_entities = relationship("FoundEntity", back_populates="finder", cascade="all, delete-orphan")
    categories = relationship("EntityCategory", back_populates="finder", cascade="all, delete-orphan")


class FoundEntity(Base):
    """Bulunan entity"""
    __tablename__ = "found_entities"
    
    id = Column(Integer, primary_key=True, index=True)
    finder_id = Column(Integer, ForeignKey("entity_finders.id"), nullable=False, index=True)
    entity_name = Column(String(255), nullable=False, index=True)
    wikipedia_url = Column(String(500))
    wikipedia_summary = Column(Text)
    category = Column(String(100), index=True)  # Örn: "cosmetic_dentistry", "restorative_dentistry"
    relevance_score = Column(Integer, default=0)  # 0-100 arası ilgili olma skoru
    is_related = Column(Boolean, default=True)  # Anahtar kelime ile ilgili mi?
    source_section = Column(String(255))  # Hangi Wikipedia başlığından bulundu (örn: "Medical Uses", "Procedure")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    finder = relationship("EntityFinder", back_populates="found_entities")


class EntityCategory(Base):
    """Entity kategorileri"""
    __tablename__ = "entity_categories"
    
    id = Column(Integer, primary_key=True, index=True)
    finder_id = Column(Integer, ForeignKey("entity_finders.id"), nullable=False, index=True)
    category_name = Column(String(100), nullable=False, index=True)  # Örn: "cosmetic_dentistry"
    category_display_name = Column(String(200))  # Örn: "Cosmetic Dentistry"
    entity_count = Column(Integer, default=0)  # Bu kategorideki entity sayısı
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    finder = relationship("EntityFinder", back_populates="categories")


def init_entity_finder_tables():
    """Entity Finder tablolarını oluştur"""
    from core.database import engine, SessionLocal
    from sqlalchemy import text
    
    # Tabloları oluştur
    Base.metadata.create_all(bind=engine, tables=[
        EntityFinder.__table__,
        FoundEntity.__table__,
        EntityCategory.__table__
    ])
    
    # Migration kontrolü
    db = SessionLocal()
    try:
        # Kolon kontrolü için PRAGMA kullan
        result = db.execute(text("PRAGMA table_info(entity_finders)"))
        columns = [row[1] for row in result]
        
        # Eksik kolonları ekle
        if "wikipedia_url" not in columns:
            db.execute(text("ALTER TABLE entity_finders ADD COLUMN wikipedia_url VARCHAR(500)"))
            db.commit()
        if "total_links_found" not in columns:
            db.execute(text("ALTER TABLE entity_finders ADD COLUMN total_links_found INTEGER DEFAULT 0"))
            db.commit()
        if "total_entities_found" not in columns:
            db.execute(text("ALTER TABLE entity_finders ADD COLUMN total_entities_found INTEGER DEFAULT 0"))
            db.commit()
        if "completed_at" not in columns:
            db.execute(text("ALTER TABLE entity_finders ADD COLUMN completed_at DATETIME"))
            db.commit()
        
        # FoundEntity tablosu için migration
        try:
            result_entities = db.execute(text("PRAGMA table_info(found_entities)"))
            entity_columns = [row[1] for row in result_entities]
            if "source_section" not in entity_columns:
                db.execute(text("ALTER TABLE found_entities ADD COLUMN source_section VARCHAR(255)"))
                db.commit()
                print("✅ source_section kolonu eklendi")
            else:
                print("✅ source_section kolonu zaten mevcut")
        except Exception as e:
            print(f"⚠️ source_section migration hatası: {e}")
            db.rollback()
        
        print("✅ Entity Finder tabloları hazır")
    except Exception as e:
        print(f"⚠️ Entity Finder migration hatası: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

