# ============================================
# Site Tools - Veritabanı Modelleri
# ============================================

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, Float, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship

# Ana veritabanı engine'i kullan
from core.database import Base, engine


class PageAnalysis(Base):
    """
    Sayfa analiz sonuçları tablosu.
    Her sayfa için H1, Schema, Internal Link özeti.
    """
    __tablename__ = "page_analysis"
    
    id = Column(Integer, primary_key=True, index=True)
    page_id = Column(Integer, ForeignKey("pages.id"), nullable=False, unique=True)
    
    # H1 Analizi
    h1_status = Column(String(20), default="pending")  # ok, missing, duplicate, pending
    h1_count = Column(Integer, default=0)
    h1_contents = Column(JSON, nullable=True)  # ["H1 text 1", "H1 text 2"]
    
    # Schema Analizi
    schema_status = Column(String(20), default="pending")  # ok, missing, error, pending
    schema_types = Column(JSON, nullable=True)  # ["FAQ", "LocalBusiness", "Article"]
    schema_errors = Column(Text, nullable=True)
    
    # Internal Link Özet
    internal_links_total = Column(Integer, default=0)
    internal_links_ok = Column(Integer, default=0)  # 200
    internal_links_redirect = Column(Integer, default=0)  # 301/302
    internal_links_broken = Column(Integer, default=0)  # 404/500
    
    # Meta
    analyzed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<PageAnalysis(page_id={self.page_id}, h1={self.h1_status}, schema={self.schema_status})>"


class InternalLink(Base):
    """
    Internal link detayları tablosu.
    Her bulunan internal link için status ve redirect chain.
    """
    __tablename__ = "internal_links"
    
    id = Column(Integer, primary_key=True, index=True)
    source_page_id = Column(Integer, ForeignKey("pages.id"), nullable=False, index=True)
    
    # Link bilgileri
    target_url = Column(String(2000), nullable=False)
    anchor_text = Column(String(500), nullable=True)
    
    # Status
    status_code = Column(Integer, nullable=True)  # Redirect veren URL'in status code'u (301, 302, vs.)
    final_url = Column(String(2000), nullable=True)  # Redirect sonrası final URL
    final_status_code = Column(Integer, nullable=True)  # Final URL'in status code'u (genellikle 200)
    redirect_chain = Column(JSON, nullable=True)  # [{"url": "...", "status": 301}, ...]
    redirect_count = Column(Integer, default=0)
    
    # Flags
    is_broken = Column(Boolean, default=False)  # 404, 500 vs.
    is_redirect = Column(Boolean, default=False)  # 301, 302 vs.
    
    # Meta
    checked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<InternalLink(source={self.source_page_id}, target={self.target_url[:30]}, status={self.status_code})>"


def init_site_tools_tables():
    """Site Tools tablolarını oluştur"""
    Base.metadata.create_all(bind=engine, tables=[
        PageAnalysis.__table__,
        InternalLink.__table__
    ])
    print("✅ Site Tools tabloları oluşturuldu.")
