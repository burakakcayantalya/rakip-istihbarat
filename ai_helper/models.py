# ============================================
# AI Helper - Database Models
# ============================================

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Float, JSON
from sqlalchemy.orm import relationship, Session
from datetime import datetime
from core.database import Base


class AIHelperProject(Base):
    """AI Helper projesi (her site için bir proje)"""
    __tablename__ = "ai_helper_projects"
    
    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    project_name = Column(String(255), nullable=False)  # Örn: "HCT"
    ai_provider = Column(String(50), default="gemini")  # AI provider: gemini, deepseek
    ai_model = Column(String(50), default="gemini-flash-latest")  # AI model (provider'a göre değişir)
    status = Column(String(50), default="active")  # active, paused, completed
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    clusters = relationship("AIHelperCluster", back_populates="project", cascade="all, delete-orphan")
    opportunities = relationship("AIHelperOpportunity", back_populates="project", cascade="all, delete-orphan")
    batches = relationship("AIHelperBatch", back_populates="project", cascade="all, delete-orphan")
    logs = relationship("AIHelperLog", back_populates="project", cascade="all, delete-orphan")


class AIHelperCluster(Base):
    """Semantic kümeler (implant intentli, veneers intentli, vs.)"""
    __tablename__ = "ai_helper_clusters"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("ai_helper_projects.id"), nullable=False, index=True)
    cluster_name = Column(String(255), nullable=False)  # Örn: "implant", "veneers"
    urls_json = Column(JSON)  # Bu kümedeki URL'lerin listesi
    # Internal linking hedefleri
    authority_target_cluster_id = Column(Integer, ForeignKey("ai_helper_clusters.id"), nullable=True)  # Otorite Hedef
    thematic_target_cluster_id = Column(Integer, ForeignKey("ai_helper_clusters.id"), nullable=True)  # Tematik Hedef
    indirect_target_cluster_id = Column(Integer, ForeignKey("ai_helper_clusters.id"), nullable=True)  # Dolaylı Hedef
    mandatory_target_cluster_id = Column(Integer, ForeignKey("ai_helper_clusters.id"), nullable=True)  # Zorunlu Hedef
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    project = relationship("AIHelperProject", back_populates="clusters")
    opportunities = relationship("AIHelperOpportunity", back_populates="cluster")


class AIHelperOpportunity(Base):
    """Internal linking fırsatları (gap'ler)"""
    __tablename__ = "ai_helper_opportunities"
    
    id = Column(Integer, primary_key=True, index=True)
    internal_link_status = Column(String(50), nullable=True)  # OK, PENDING, MISSING - Internal link durumu
    project_id = Column(Integer, ForeignKey("ai_helper_projects.id"), nullable=False, index=True)
    cluster_id = Column(Integer, ForeignKey("ai_helper_clusters.id"), nullable=True, index=True)
    source_url = Column(String(500), nullable=False)  # Blogpost URL'i
    target_url = Column(String(500), nullable=False)  # Hub URL'i
    target_keyword = Column(String(255))  # Anchor text önerisi
    html_snippet = Column(Text)  # Elementor widget'e direkt koyulacak HTML kodu
    paragraph_index = Column(Integer)  # Paragraf sırası (0-based)
    original_paragraph = Column(Text)  # Orijinal paragraf metni
    status = Column(String(50), default="IN_POOL")  # IN_POOL, PROCESSING, READY_FOR_APPROVAL, PUBLISHED, REJECTED
    confidence_score = Column(Float, default=0.0)  # AI confidence score (0-100)
    batch_week = Column(String(20))  # Örn: "2026-W01"
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    project = relationship("AIHelperProject", back_populates="opportunities")
    cluster = relationship("AIHelperCluster", back_populates="opportunities")
    proposals = relationship("AIHelperProposal", back_populates="opportunity", cascade="all, delete-orphan")


class AIHelperBatch(Base):
    """Haftalık batch'ler"""
    __tablename__ = "ai_helper_batches"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("ai_helper_projects.id"), nullable=False, index=True)
    batch_week = Column(String(20), nullable=False)  # Örn: "2026-W01"
    status = Column(String(50), default="PROCESSING")  # PROCESSING, COMPLETED
    item_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    project = relationship("AIHelperProject", back_populates="batches")


class AIHelperProposal(Base):
    """AI'ın önerdiği değişiklikler (before/after)"""
    __tablename__ = "ai_helper_proposals"
    
    id = Column(Integer, primary_key=True, index=True)
    opportunity_id = Column(Integer, ForeignKey("ai_helper_opportunities.id"), nullable=False, index=True)
    original_snippet = Column(Text)  # Orijinal HTML paragraf
    proposed_snippet = Column(Text)  # AI'ın önerdiği HTML paragraf (link ile)
    wp_post_id = Column(Integer, nullable=True)  # WordPress post ID
    ai_confidence_score = Column(Float, default=0.0)  # AI'ın bu öneri için confidence score
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    opportunity = relationship("AIHelperOpportunity", back_populates="proposals")


class AIHelperLog(Base):
    """Log kayıtları"""
    __tablename__ = "ai_helper_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("ai_helper_projects.id"), nullable=False, index=True)
    log_level = Column(String(20), nullable=False)  # INFO, WARNING, ERROR, SUCCESS
    module = Column(String(50), nullable=False)  # STRATEGIST, SCHEDULER, EDITOR, WORDPRESS
    message = Column(Text, nullable=False)
    details_json = Column(JSON)  # Ek detaylar (JSON formatında)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    project = relationship("AIHelperProject", back_populates="logs")


def init_ai_helper_tables():
    """AI Helper tablolarını oluştur"""
    from core.database import engine, SessionLocal
    from sqlalchemy import text, inspect
    
    # Tabloları oluştur
    Base.metadata.create_all(bind=engine, tables=[
        AIHelperProject.__table__,
        AIHelperCluster.__table__,
        AIHelperOpportunity.__table__,
        AIHelperBatch.__table__,
        AIHelperProposal.__table__,
        AIHelperLog.__table__
    ])
    
    # Migration: ai_provider ve ai_model kolonları ekle
    db = SessionLocal()
    try:
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('ai_helper_projects')]
        
        if 'ai_provider' not in columns:
            print("🔄 Migration: ai_provider kolonu ekleniyor...")
            try:
                db.execute(text("ALTER TABLE ai_helper_projects ADD COLUMN ai_provider VARCHAR(50) DEFAULT 'gemini'"))
                db.commit()
                print("✅ Migration tamamlandı: ai_provider kolonu eklendi.")
            except Exception as e:
                print(f"⚠️ Migration hatası (kolon zaten var olabilir): {e}")
                db.rollback()
        
        if 'ai_model' not in columns:
            print("🔄 Migration: ai_model kolonu ekleniyor...")
            try:
                db.execute(text("ALTER TABLE ai_helper_projects ADD COLUMN ai_model VARCHAR(50) DEFAULT 'gemini-flash-latest'"))
                db.commit()
                print("✅ Migration tamamlandı: ai_model kolonu eklendi.")
            except Exception as e:
                print(f"⚠️ Migration hatası (kolon zaten var olabilir): {e}")
                db.rollback()
        
        # Eski OpenAI modellerini Gemini'ye çevir
        try:
            projects = db.query(AIHelperProject).filter(
                AIHelperProject.ai_model.in_(["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"])
            ).all()
            for project in projects:
                if not project.ai_provider or project.ai_provider not in ["gemini", "deepseek"]:
                    project.ai_provider = "gemini"
                    project.ai_model = "gemini-flash-latest"
            db.commit()
            if projects:
                print(f"✅ Migration: {len(projects)} proje Gemini'ye güncellendi.")
        except Exception as e:
            print(f"⚠️ Migration hatası: {e}")
            db.rollback()
        
        # Migration: html_snippet, paragraph_index, original_paragraph kolonları ekle
        try:
            opp_columns = [col['name'] for col in inspector.get_columns('ai_helper_opportunities')]
            
            if 'html_snippet' not in opp_columns:
                print("🔄 Migration: html_snippet kolonu ekleniyor...")
                db.execute(text("ALTER TABLE ai_helper_opportunities ADD COLUMN html_snippet TEXT"))
                db.commit()
            
            if 'paragraph_index' not in opp_columns:
                print("🔄 Migration: paragraph_index kolonu ekleniyor...")
                db.execute(text("ALTER TABLE ai_helper_opportunities ADD COLUMN paragraph_index INTEGER"))
                db.commit()
            
            if 'original_paragraph' not in opp_columns:
                print("🔄 Migration: original_paragraph kolonu ekleniyor...")
                db.execute(text("ALTER TABLE ai_helper_opportunities ADD COLUMN original_paragraph TEXT"))
                db.commit()
        except Exception as e:
            print(f"⚠️ Migration hatası (kolonlar zaten var olabilir): {e}")
            db.rollback()
        
        # Migration: Cluster target kolonları ekle
        try:
            cluster_columns = [col['name'] for col in inspector.get_columns('ai_helper_clusters')]
            
            if 'authority_target_cluster_id' not in cluster_columns:
                print("🔄 Migration: authority_target_cluster_id kolonu ekleniyor...")
                db.execute(text("ALTER TABLE ai_helper_clusters ADD COLUMN authority_target_cluster_id INTEGER"))
                db.commit()
            
            if 'thematic_target_cluster_id' not in cluster_columns:
                print("🔄 Migration: thematic_target_cluster_id kolonu ekleniyor...")
                db.execute(text("ALTER TABLE ai_helper_clusters ADD COLUMN thematic_target_cluster_id INTEGER"))
                db.commit()
            
            if 'indirect_target_cluster_id' not in cluster_columns:
                print("🔄 Migration: indirect_target_cluster_id kolonu ekleniyor...")
                db.execute(text("ALTER TABLE ai_helper_clusters ADD COLUMN indirect_target_cluster_id INTEGER"))
                db.commit()
            
            if 'mandatory_target_cluster_id' not in cluster_columns:
                print("🔄 Migration: mandatory_target_cluster_id kolonu ekleniyor...")
                db.execute(text("ALTER TABLE ai_helper_clusters ADD COLUMN mandatory_target_cluster_id INTEGER"))
                db.commit()
        except Exception as e:
            print(f"⚠️ Migration hatası (kolonlar zaten var olabilir): {e}")
            db.rollback()
        
        # Migration: Opportunity internal_link_status kolonu ekle
        try:
            opp_columns = [col['name'] for col in inspector.get_columns('ai_helper_opportunities')]
            if 'internal_link_status' not in opp_columns:
                print("🔄 Migration: internal_link_status kolonu ekleniyor...")
                db.execute(text("ALTER TABLE ai_helper_opportunities ADD COLUMN internal_link_status VARCHAR(50) DEFAULT NULL"))
                db.commit()
        except Exception as e:
            print(f"⚠️ Migration hatası (kolon zaten var olabilir): {e}")
            db.rollback()
    except Exception as e:
        print(f"⚠️ Migration kontrolü hatası: {e}")
    finally:
        db.close()


def add_log(project_id: int, level: str, module: str, message: str, details: dict = None, db: Session = None):
    """Log ekle"""
    if db is None:
        from core.database import SessionLocal
        db = SessionLocal()
        try:
            log = AIHelperLog(
                project_id=project_id,
                log_level=level.upper(),
                module=module.upper(),
                message=message,
                details_json=details or {}
            )
            db.add(log)
            db.commit()
        finally:
            db.close()
    else:
        log = AIHelperLog(
            project_id=project_id,
            log_level=level.upper(),
            module=module.upper(),
            message=message,
            details_json=details or {}
        )
        db.add(log)
        db.commit()

    
    print("✅ AI Helper tabloları hazır")

