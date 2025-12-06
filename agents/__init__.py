# ============================================
# Agents - Shared Utilities
# ============================================

from fastapi import Request
from sqlalchemy.orm import Session
from typing import Optional
from core.database import Site, get_setting, set_setting


def get_selected_agent_site_id(request: Request, db: Session = None) -> Optional[int]:
    """
    Tüm agent'lar için ortak seçilen site ID'sini al (Database öncelikli, cookie fallback)
    """
    # Önce database'den al (kalıcı çözüm)
    if db:
        try:
            site_id_str = get_setting(db, "AGENT_SELECTED_SITE_ID")
            if site_id_str:
                try:
                    site_id = int(site_id_str)
                    if site_id > 0:
                        # Site'in hala var olduğunu kontrol et
                        site = db.query(Site).filter(
                            Site.id == site_id,
                            Site.is_competitor == False,  # Sadece bizim sitelerimiz
                            Site.is_active == True
                        ).first()
                        if site:
                            return site_id
                except (ValueError, TypeError):
                    pass
        except Exception:
            pass
    
    # Database'de yoksa cookie'den al (fallback)
    selected_site_id = request.cookies.get("agents_selected_site_id")
    if selected_site_id:
        try:
            site_id = int(selected_site_id)
            if site_id > 0:
                return site_id
        except (ValueError, TypeError):
            pass
    
    return None


def save_selected_agent_site(db: Session, site_id: int) -> bool:
    """Seçilen site'i database'e kaydet (kalıcı) - Tüm agent'lar için ortak"""
    try:
        set_setting(db, "AGENT_SELECTED_SITE_ID", str(site_id))
        return True
    except Exception as e:
        print(f"⚠️ Agent site seçimi kaydedilemedi: {e}")
        return False
