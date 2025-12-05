# ============================================
# Rakip İçerik İstihbarat Sistemi V2
# Yapılandırma Yönetimi
# ============================================

import os
from pathlib import Path
from dotenv import load_dotenv
from typing import Optional

# .env dosyasını yükle
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Settings:
    """
    Uygulama ayarları.
    Öncelik sırası:
    1. Veritabanındaki değer (runtime'da güncellenen)
    2. Environment variable
    3. Varsayılan değer
    """
    
    # Uygulama
    APP_NAME: str = os.getenv("APP_NAME", "Rakip İstihbarat Sistemi")
    APP_VERSION: str = os.getenv("APP_VERSION", "2.0.0")
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-this-secret-key")
    
    # Sunucu
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    
    # Veritabanı
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./database.db")
    DATABASE_PATH: Path = BASE_DIR / "database.db"
    
    # API Keys (varsayılan değerler - veritabanından override edilebilir)
    RAPIDAPI_KEY: str = os.getenv("RAPIDAPI_KEY", "")
    RAPIDAPI_HOST: str = os.getenv("RAPIDAPI_HOST", "google-search116.p.rapidapi.com")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

    # Deepseek AI (RapidAPI)
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_HOST: str = os.getenv("DEEPSEEK_HOST", "deepseek-all-in-one.p.rapidapi.com")
    
    # OpenAI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    
    # Tarama Ayarları
    SCAN_INTERVAL_HOURS: int = int(os.getenv("SCAN_INTERVAL_HOURS", "6"))
    CHANGE_THRESHOLD_PERCENT: float = float(os.getenv("CHANGE_THRESHOLD_PERCENT", "5"))
    MAX_CONCURRENT_SCANS: int = int(os.getenv("MAX_CONCURRENT_SCANS", "3"))
    REQUEST_DELAY_SECONDS: float = float(os.getenv("REQUEST_DELAY_SECONDS", "2"))
    
    # Yollar
    TEMPLATES_DIR: Path = BASE_DIR / "templates"
    STATIC_DIR: Path = BASE_DIR / "static"


# Global settings instance
settings = Settings()


class DynamicSettings:
    """
    Veritabanından okunan dinamik ayarlar.
    UI üzerinden güncellenebilir.
    """
    
    _cache: dict = {}
    _db = None
    
    @classmethod
    def set_db(cls, db):
        """Veritabanı bağlantısını ayarla"""
        cls._db = db
    
    @classmethod
    async def get(cls, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Ayar değerini al.
        Önce veritabanına bak, yoksa .env'den al.
        """
        # Cache'de varsa döndür
        if key in cls._cache:
            return cls._cache[key]
        
        # Veritabanından okumayı dene
        if cls._db:
            try:
                from core.database import get_setting
                value = await get_setting(cls._db, key)
                if value is not None:
                    cls._cache[key] = value
                    return value
            except Exception:
                pass
        
        # .env'den varsayılan değeri al
        env_value = getattr(settings, key, None) or os.getenv(key, default)
        return env_value
    
    @classmethod
    async def set(cls, key: str, value: str) -> bool:
        """
        Ayar değerini veritabanına kaydet.
        """
        if cls._db:
            try:
                from core.database import set_setting
                await set_setting(cls._db, key, value)
                cls._cache[key] = value
                return True
            except Exception:
                return False
        return False
    
    @classmethod
    def clear_cache(cls):
        """Cache'i temizle"""
        cls._cache = {}


# Ayar anahtarları sabitleri
class SettingKeys:
    """Ayar anahtarları sabitleri"""
    RAPIDAPI_KEY = "RAPIDAPI_KEY"
    RAPIDAPI_HOST = "RAPIDAPI_HOST"
    GEMINI_API_KEY = "GEMINI_API_KEY"
    GEMINI_MODEL = "GEMINI_MODEL"
    DEEPSEEK_API_KEY = "DEEPSEEK_API_KEY"
    DEEPSEEK_HOST = "DEEPSEEK_HOST"
    OPENAI_API_KEY = "OPENAI_API_KEY"
    SCAN_INTERVAL_HOURS = "SCAN_INTERVAL_HOURS"
    CHANGE_THRESHOLD_PERCENT = "CHANGE_THRESHOLD_PERCENT"
    MAX_CONCURRENT_SCANS = "MAX_CONCURRENT_SCANS"
    REQUEST_DELAY_SECONDS = "REQUEST_DELAY_SECONDS"
