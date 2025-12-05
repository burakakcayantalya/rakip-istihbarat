# ============================================
# Rakip İçerik İstihbarat Sistemi V2
# Scoring - Değişiklik Puanlama Sistemi
# ============================================

from dataclasses import dataclass
from typing import List, Dict
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func

from core.database import Site, Page, Log, ActionType


@dataclass
class ScoreConfig:
    """Puanlama konfigürasyonu"""
    new_content_score: int = 1  # Yeni içerik puanı
    update_score: int = 1  # Güncelleme puanı
    min_change_threshold: float = 5.0  # Minimum değişim yüzdesi (bunun altı puanlanmaz)
    significant_change_threshold: float = 30.0  # Önemli değişim yüzdesi (bonus puan)
    significant_change_bonus: int = 1  # Önemli değişim bonus puanı


class ScoringEngine:
    """
    Puanlama motoru.
    Sitelerin içerik aktivitelerini puanlar.
    """
    
    def __init__(self, config: ScoreConfig = None):
        self.config = config or ScoreConfig()
    
    def calculate_log_score(self, log: Log) -> int:
        """
        Tek bir log için puan hesapla.
        
        Args:
            log: Log kaydı
        
        Returns:
            Hesaplanan puan
        """
        score = 0
        
        if log.action_type == ActionType.NEW:
            score = self.config.new_content_score
        
        elif log.action_type == ActionType.UPDATE:
            # Değişim yüzdesi eşiğinin altındaysa puan verme
            if log.change_percentage < self.config.min_change_threshold:
                return 0
            
            score = self.config.update_score
            
            # Önemli değişim bonusu
            if log.change_percentage >= self.config.significant_change_threshold:
                score += self.config.significant_change_bonus
        
        return score
    
    def get_site_score(
        self, 
        db: Session, 
        site_id: int, 
        days: int = 30
    ) -> Dict:
        """
        Belirli bir süre içinde sitenin toplam puanını hesapla.
        SITEMAP LASTMOD TARİHİNE GÖRE çalışır.
        
        Args:
            db: Veritabanı session
            site_id: Site ID
            days: Kaç günlük veri
        
        Returns:
            Puan detayları
        """
        since = datetime.utcnow() - timedelta(days=days)
        
        # Site'in sayfalarını bul
        pages = db.query(Page).filter(Page.site_id == site_id).all()
        
        total_score = 0
        new_count = 0
        update_count = 0
        
        # Her sayfa için sitemap_lastmod tarihine bak
        for page in pages:
            if not page.sitemap_lastmod:
                continue
            
            # lastmod tarihini normalize et
            lastmod = page.sitemap_lastmod
            if lastmod.tzinfo:
                lastmod = lastmod.replace(tzinfo=None)
            
            # Belirtilen süre içinde mi?
            if lastmod >= since:
                # first_seen_at ile karşılaştır (sadece tarih karşılaştırması)
                first_seen = page.first_seen_at
                if first_seen:
                    if first_seen.tzinfo:
                        first_seen = first_seen.replace(tzinfo=None)
                    first_seen_date = first_seen.date()
                    lastmod_date = lastmod.date()
                    
                    # Eğer first_seen_at ile lastmod aynı günse yeni içerik
                    if first_seen_date == lastmod_date:
                        new_count += 1
                        total_score += self.config.new_content_score
                    else:
                        # Farklı günlerdeyse güncelleme
                        update_count += 1
                        total_score += self.config.update_score
                else:
                    # first_seen_at yoksa güncelleme say
                    update_count += 1
                    total_score += self.config.update_score
        
        return {
            "site_id": site_id,
            "total_score": total_score,
            "new_content_count": new_count,
            "update_count": update_count,
            "period_days": days
        }
    
    def get_all_sites_ranking(
        self, 
        db: Session, 
        days: int = 30
    ) -> List[Dict]:
        """
        Tüm sitelerin puan sıralamasını al.
        
        Args:
            db: Veritabanı session
            days: Kaç günlük veri
        
        Returns:
            Sıralanmış site listesi
        """
        sites = db.query(Site).filter(Site.is_active == True).all()
        
        rankings = []
        for site in sites:
            score_data = self.get_site_score(db, site.id, days)
            score_data["site_name"] = site.name
            score_data["site_domain"] = site.domain
            score_data["is_competitor"] = site.is_competitor
            rankings.append(score_data)
        
        # Toplam puana göre sırala
        rankings.sort(key=lambda x: x["total_score"], reverse=True)
        
        # Sıra numarası ekle
        for i, r in enumerate(rankings, 1):
            r["rank"] = i
        
        return rankings
    
    def get_activity_summary(
        self, 
        db: Session, 
        days: int = 7
    ) -> Dict:
        """
        Genel aktivite özeti.
        SITEMAP LASTMOD TARİHİNE GÖRE çalışır.
        
        Args:
            db: Veritabanı session
            days: Kaç günlük veri
        
        Returns:
            Aktivite özeti
        """
        since = datetime.utcnow() - timedelta(days=days)
        
        # Tüm sayfaları al
        all_pages = db.query(Page).all()
        
        new_count = 0
        update_count = 0
        
        # Her sayfa için sitemap_lastmod tarihine bak
        for page in all_pages:
            if not page.sitemap_lastmod:
                continue
            
            # lastmod tarihini normalize et
            lastmod = page.sitemap_lastmod
            if lastmod.tzinfo:
                lastmod = lastmod.replace(tzinfo=None)
            
            # Belirtilen süre içinde mi?
            if lastmod >= since:
                # first_seen_at ile karşılaştır (sadece tarih karşılaştırması)
                first_seen = page.first_seen_at
                if first_seen:
                    if first_seen.tzinfo:
                        first_seen = first_seen.replace(tzinfo=None)
                    first_seen_date = first_seen.date()
                    lastmod_date = lastmod.date()
                    
                    # Eğer first_seen_at ile lastmod aynı günse yeni içerik
                    if first_seen_date == lastmod_date:
                        new_count += 1
                    else:
                        # Farklı günlerdeyse güncelleme
                        update_count += 1
                else:
                    # first_seen_at yoksa güncelleme say
                    update_count += 1
        
        # Aktif site sayısı
        active_sites = db.query(func.count(Site.id)).filter(
            Site.is_active == True
        ).scalar()
        
        # Toplam takip edilen sayfa
        total_pages = db.query(func.count(Page.id)).scalar()
        
        # En aktif rakip
        rankings = self.get_all_sites_ranking(db, days)
        competitor_rankings = [r for r in rankings if r.get("is_competitor", False)]
        most_active_competitor = competitor_rankings[0] if competitor_rankings else None
        
        return {
            "period_days": days,
            "new_content_count": new_count,
            "update_count": update_count,
            "total_activity": new_count + update_count,
            "active_sites": active_sites or 0,
            "total_pages_tracked": total_pages or 0,
            "most_active_competitor": most_active_competitor
        }


# Global scoring engine
scoring_engine = ScoringEngine()
