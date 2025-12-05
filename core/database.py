# ============================================
# Rakip İçerik İstihbarat Sistemi V2
# Veritabanı Modelleri ve Yönetimi
# ============================================

from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Boolean, 
    Float, DateTime, ForeignKey, Enum as SQLEnum
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.pool import StaticPool
import enum

from config import settings

# ============================================
# DATABASE SETUP
# ============================================

# SQLite için özel ayarlar (async uyumluluğu için)
engine = create_engine(
    f"sqlite:///{settings.DATABASE_PATH}",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=settings.DEBUG
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ============================================
# ENUMS
# ============================================

class ActionType(enum.Enum):
    """Log aksiyon tipleri"""
    NEW = "NEW"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


class ScanStatus(enum.Enum):
    """Tarama durumları"""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# ============================================
# MODELS
# ============================================

class Site(Base):
    """
    Takip edilen siteler tablosu.
    Hem rakip siteleri hem de kendi sitelerimizi tutar.
    """
    __tablename__ = "sites"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)  # Site adı (örn: "Rakip A")
    domain = Column(String(255), nullable=False, unique=True)  # örn: "rakip-a.com"
    sitemap_url = Column(String(500), nullable=True)  # Sitemap adresi
    is_competitor = Column(Boolean, default=True)  # Rakip mi yoksa bizim sitemiz mi?
    is_active = Column(Boolean, default=True)  # Aktif takipte mi?
    
    # WordPress bilgileri (sadece kendi sitelerimiz için)
    # SSH bilgileri
    wp_ssh_host = Column(String(255), nullable=True)  # SSH host (örn: example.com)
    wp_ssh_user = Column(String(100), nullable=True)  # SSH user
    wp_ssh_port = Column(Integer, default=22)  # SSH port
    wp_path = Column(String(500), nullable=True)  # WordPress root path (örn: /var/www/html)
    wp_cli_path = Column(String(100), default="wp")  # WP CLI path (default: wp)
    # REST API bilgileri (SSH yoksa)
    wp_api_url = Column(String(500), nullable=True)  # WordPress site URL (örn: https://example.com)
    wp_api_username = Column(String(100), nullable=True)  # WordPress kullanıcı adı
    wp_api_password = Column(String(500), nullable=True)  # WordPress Application Password
    
    # Meta bilgiler
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_scan_at = Column(DateTime, nullable=True)  # Son tarama zamanı
    
    # İlişkiler
    pages = relationship("Page", back_populates="site", cascade="all, delete-orphan")
    scan_jobs = relationship("ScanJob", back_populates="site", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Site(id={self.id}, name='{self.name}', domain='{self.domain}')>"


class Page(Base):
    """
    Takip edilen sayfalar tablosu.
    Her sitenin altındaki URL'leri tutar.
    """
    __tablename__ = "pages"
    
    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    url = Column(String(2000), nullable=False, index=True)  # Tam URL
    title = Column(String(500), nullable=True)  # Sayfa başlığı
    
    # İçerik takibi
    content_hash = Column(String(64), nullable=True)  # MD5 hash - hızlı karşılaştırma için
    last_content_text = Column(Text, nullable=True)  # Son içeriğin tam metni - diff için
    word_count = Column(Integer, default=0)  # Kelime sayısı
    
    # Meta bilgiler
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_checked_at = Column(DateTime, nullable=True)
    last_changed_at = Column(DateTime, nullable=True)
    sitemap_lastmod = Column(DateTime, nullable=True)  # Sitemap'teki son değişiklik tarihi (GMT)
    check_count = Column(Integer, default=0)  # Kaç kez kontrol edildi
    
    # İlişkiler
    site = relationship("Site", back_populates="pages")
    logs = relationship("Log", back_populates="page", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Page(id={self.id}, url='{self.url[:50]}...')>"


class Log(Base):
    """
    Değişiklik logları tablosu.
    Her yeni içerik veya güncelleme kaydedilir.
    """
    __tablename__ = "logs"
    
    id = Column(Integer, primary_key=True, index=True)
    page_id = Column(Integer, ForeignKey("pages.id"), nullable=False)
    action_type = Column(SQLEnum(ActionType), nullable=False)  # NEW veya UPDATE
    
    # Diff bilgileri
    diff_html = Column(Text, nullable=True)  # HTML formatında fark raporu
    old_content_preview = Column(Text, nullable=True)  # Eski içerik özeti (ilk 500 karakter)
    new_content_preview = Column(Text, nullable=True)  # Yeni içerik özeti (ilk 500 karakter)
    
    # Metrikler
    change_percentage = Column(Float, default=0.0)  # Değişim yüzdesi
    words_added = Column(Integer, default=0)  # Eklenen kelime sayısı
    words_removed = Column(Integer, default=0)  # Silinen kelime sayısı
    
    # Puanlama
    score = Column(Integer, default=0)  # Bu değişikliğin puanı
    
    # Meta
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # İlişkiler
    page = relationship("Page", back_populates="logs")
    
    def __repr__(self):
        return f"<Log(id={self.id}, action={self.action_type.value}, page_id={self.page_id})>"


class ScanJob(Base):
    """
    Tarama işleri tablosu.
    Arka planda çalışan tarama görevlerini takip eder.
    """
    __tablename__ = "scan_jobs"
    
    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    status = Column(SQLEnum(ScanStatus), default=ScanStatus.PENDING)
    
    # İlerleme
    total_pages = Column(Integer, default=0)  # Toplam sayfa sayısı
    scanned_pages = Column(Integer, default=0)  # Taranan sayfa sayısı
    new_pages_found = Column(Integer, default=0)  # Bulunan yeni sayfa
    updated_pages_found = Column(Integer, default=0)  # Güncellenen sayfa
    
    # Hata bilgisi
    error_message = Column(Text, nullable=True)
    
    # Zaman bilgileri
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    
    # İlişkiler
    site = relationship("Site", back_populates="scan_jobs")
    
    @property
    def progress_percent(self) -> float:
        """Tarama ilerleme yüzdesi"""
        if self.total_pages == 0:
            return 0.0
        return (self.scanned_pages / self.total_pages) * 100
    
    def __repr__(self):
        return f"<ScanJob(id={self.id}, site_id={self.site_id}, status={self.status.value})>"


class Setting(Base):
    """
    Dinamik ayarlar tablosu.
    UI üzerinden güncellenen ayarları tutar.
    """
    __tablename__ = "settings"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=True)
    description = Column(String(500), nullable=True)
    is_secret = Column(Boolean, default=False)  # API key gibi hassas veriler
    
    # Meta
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<Setting(key='{self.key}')>"


# ============================================
# DATABASE HELPERS
# ============================================

def init_db():
    """Veritabanı tablolarını oluştur"""
    Base.metadata.create_all(bind=engine)
    print("✅ Veritabanı tabloları oluşturuldu.")
    
    # Migration: sitemap_lastmod kolonunu ekle (eğer yoksa)
    db = SessionLocal()
    try:
        # SQLite'da kolon var mı kontrol et
        from sqlalchemy import inspect, text
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('pages')]
        
        if 'sitemap_lastmod' not in columns:
            print("🔄 Migration: sitemap_lastmod kolonu ekleniyor...")
            try:
                db.execute(text("ALTER TABLE pages ADD COLUMN sitemap_lastmod DATETIME"))
                db.commit()
                print("✅ Migration tamamlandı: sitemap_lastmod kolonu eklendi.")
            except Exception as e:
                print(f"⚠️ Migration hatası (kolon zaten var olabilir): {e}")
                db.rollback()
        
        # Migration: WordPress bilgileri kolonlarını ekle
        try:
            site_columns = [col['name'] for col in inspector.get_columns('sites')]
            wp_columns_to_add = {
                'wp_ssh_host': 'VARCHAR(255)',
                'wp_ssh_user': 'VARCHAR(100)',
                'wp_ssh_port': 'INTEGER DEFAULT 22',
                'wp_path': 'VARCHAR(500)',
                'wp_cli_path': 'VARCHAR(100) DEFAULT "wp"',
                'wp_api_url': 'VARCHAR(500)',
                'wp_api_username': 'VARCHAR(100)',
                'wp_api_password': 'VARCHAR(500)'
            }
            
            for col_name, col_type in wp_columns_to_add.items():
                if col_name not in site_columns:
                    print(f"🔄 Migration: {col_name} kolonu ekleniyor...")
                    try:
                        db.execute(text(f"ALTER TABLE sites ADD COLUMN {col_name} {col_type}"))
                        db.commit()
                        print(f"✅ Migration tamamlandı: {col_name} kolonu eklendi.")
                    except Exception as e:
                        print(f"⚠️ Migration hatası ({col_name} zaten var olabilir): {e}")
                        db.rollback()
        except Exception as e:
            print(f"⚠️ WordPress kolon migration hatası: {e}")
            db.rollback()
        
        # Migration: InternalLink final_status_code kolonunu ekle
        try:
            internal_link_columns = [col['name'] for col in inspector.get_columns('internal_links')]
            if 'final_status_code' not in internal_link_columns:
                print("🔄 Migration: final_status_code kolonu ekleniyor...")
                try:
                    db.execute(text("ALTER TABLE internal_links ADD COLUMN final_status_code INTEGER"))
                    db.commit()
                    print("✅ Migration tamamlandı: final_status_code kolonu eklendi.")
                except Exception as e:
                    print(f"⚠️ Migration hatası (final_status_code zaten var olabilir): {e}")
                    db.rollback()
        except Exception as e:
            print(f"⚠️ InternalLink migration hatası: {e}")
            db.rollback()
            
            for col_name, col_type in wp_columns_to_add.items():
                if col_name not in site_columns:
                    print(f"🔄 Migration: {col_name} kolonu ekleniyor...")
                    try:
                        db.execute(text(f"ALTER TABLE sites ADD COLUMN {col_name} {col_type}"))
                        db.commit()
                        print(f"✅ Migration tamamlandı: {col_name} kolonu eklendi.")
                    except Exception as e:
                        print(f"⚠️ Migration hatası ({col_name} zaten var olabilir): {e}")
                        db.rollback()
        except Exception as e:
            print(f"⚠️ WordPress kolon migration hatası: {e}")
            db.rollback()
        
        # Varsayılan ayarları ekle
        _init_default_settings(db)
        db.commit()
    except Exception as e:
        print(f"⚠️ Veritabanı başlatma hatası: {e}")
        db.rollback()
    finally:
        db.close()


def _init_default_settings(db):
    """Varsayılan ayarları veritabanına ekle"""
    default_settings = [
        ("RAPIDAPI_KEY", settings.RAPIDAPI_KEY, "Google Search API Key", True),
        ("RAPIDAPI_HOST", settings.RAPIDAPI_HOST, "RapidAPI Host", False),
        ("GEMINI_API_KEY", settings.GEMINI_API_KEY, "Gemini AI API Key", True),
        ("GEMINI_MODEL", settings.GEMINI_MODEL, "Gemini Model Adı", False),
        ("SCAN_INTERVAL_HOURS", str(settings.SCAN_INTERVAL_HOURS), "Tarama Sıklığı (Saat)", False),
        ("CHANGE_THRESHOLD_PERCENT", str(settings.CHANGE_THRESHOLD_PERCENT), "Değişim Eşiği (%)", False),
        ("MAX_CONCURRENT_SCANS", str(settings.MAX_CONCURRENT_SCANS), "Max Eşzamanlı Tarama", False),
        ("REQUEST_DELAY_SECONDS", str(settings.REQUEST_DELAY_SECONDS), "İstek Arası Bekleme (sn)", False),
        ("FRESHNESS_THRESHOLD_DAYS", "45", "Freshness Eşiği (Gün)", False),
    ]
    
    for key, value, desc, is_secret in default_settings:
        existing = db.query(Setting).filter(Setting.key == key).first()
        if not existing:
            setting = Setting(key=key, value=value, description=desc, is_secret=is_secret)
            db.add(setting)
    
    print("✅ Varsayılan ayarlar eklendi.")


def get_db():
    """Veritabanı oturumu al (dependency injection için)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================
# SETTING HELPERS
# ============================================

def get_setting(db, key: str) -> Optional[str]:
    """Ayar değerini veritabanından al"""
    setting = db.query(Setting).filter(Setting.key == key).first()
    return setting.value if setting else None


def set_setting(db, key: str, value: str) -> bool:
    """Ayar değerini veritabanına kaydet"""
    setting = db.query(Setting).filter(Setting.key == key).first()
    if setting:
        setting.value = value
        setting.updated_at = datetime.utcnow()
    else:
        setting = Setting(key=key, value=value)
        db.add(setting)
    db.commit()
    return True


def get_all_settings(db) -> List[Setting]:
    """Tüm ayarları al"""
    return db.query(Setting).all()
