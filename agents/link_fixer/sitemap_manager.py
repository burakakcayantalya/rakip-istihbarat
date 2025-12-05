# ============================================
# Link Fixer Agent - Sitemap Manager
# ============================================
# Her gün sitemap'i kontrol edip URL'leri günceller
# Link Fixer görev oluştururken alternatif URL bulmak için kullanılır

from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional, List
from urllib.parse import urlparse
import difflib

from core.database import Site, Page
from core.scraper import scraper


async def update_sitemap_urls(site_id: int, db: Session) -> dict:
    """
    Site'in sitemap'ini kontrol et ve URL'leri güncelle
    
    Args:
        site_id: Site ID
        db: Database session
    
    Returns:
        {"updated": int, "total": int, "errors": List[str]}
    """
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        return {"updated": 0, "total": 0, "errors": ["Site bulunamadı"]}
    
    errors = []
    
    # Sitemap URL'ini bul
    sitemap_url = site.sitemap_url
    if not sitemap_url:
        sitemaps = await scraper.find_sitemap(site.domain)
        if sitemaps:
            sitemap_url = sitemaps[0]
            site.sitemap_url = sitemap_url
            db.commit()
        else:
            errors.append("Sitemap bulunamadı")
            return {"updated": 0, "total": 0, "errors": errors}
    
    if not sitemap_url:
        errors.append("Sitemap URL yok")
        return {"updated": 0, "total": 0, "errors": errors}
    
    # Sitemap'i parse et
    try:
        sitemap_result = await scraper.parse_sitemap(sitemap_url)
        sitemap_urls = sitemap_result.urls
        
        if not sitemap_urls:
            errors.append("Sitemap'te URL bulunamadı")
            return {"updated": 0, "total": 0, "errors": errors}
        
        # Mevcut sayfaları al
        existing_pages = db.query(Page).filter(Page.site_id == site_id).all()
        existing_urls = {page.url: page for page in existing_pages}
        
        updated_count = 0
        
        # Sitemap'teki URL'leri güncelle veya ekle
        for sitemap_url_obj in sitemap_urls:
            url = sitemap_url_obj.url
            lastmod = sitemap_url_obj.lastmod
            
            if url in existing_urls:
                # Mevcut sayfayı güncelle
                page = existing_urls[url]
                if lastmod:
                    lastmod_naive = lastmod.replace(tzinfo=None) if lastmod.tzinfo else lastmod
                    page.sitemap_lastmod = lastmod_naive
                updated_count += 1
            else:
                # Yeni sayfa ekle (sadece URL ve sitemap_lastmod ile)
                try:
                    page = Page(
                        site_id=site_id,
                        url=url,
                        sitemap_lastmod=lastmod.replace(tzinfo=None) if lastmod and lastmod.tzinfo else lastmod if lastmod else None,
                        created_at=datetime.utcnow()
                    )
                    db.add(page)
                    updated_count += 1
                except Exception as e:
                    errors.append(f"Sayfa eklenemedi ({url}): {str(e)}")
        
        db.commit()
        
        return {
            "updated": updated_count,
            "total": len(sitemap_urls),
            "errors": errors
        }
    
    except Exception as e:
        errors.append(f"Sitemap parse hatası: {str(e)}")
        return {"updated": 0, "total": 0, "errors": errors}


def find_alternative_url(old_url: str, site_id: int, db: Session) -> Optional[str]:
    """
    Eski URL için alternatif URL bul
    
    Strateji:
    1. Eğer old_url sitemap'te varsa, old_url'i döndür (zaten geçerli)
    2. Eğer yoksa, benzer URL'leri bul (path matching)
    3. En benzer URL'i döndür
    
    Args:
        old_url: Eski URL (HTTP 410 veya 404 veren)
        site_id: Site ID
        db: Database session
    
    Returns:
        Alternatif URL veya None
    """
    # Site'i al
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        return None
    
    # Sitemap'teki tüm URL'leri al
    sitemap_pages = db.query(Page).filter(
        Page.site_id == site_id,
        Page.url.isnot(None)
    ).all()
    
    if not sitemap_pages:
        return None
    
    sitemap_urls = [page.url for page in sitemap_pages]
    
    # 1. Eğer old_url sitemap'te varsa, old_url'i döndür
    if old_url in sitemap_urls:
        return old_url
    
    # 2. URL'yi parse et
    parsed_old = urlparse(old_url)
    old_path = parsed_old.path.rstrip('/')
    old_path_parts = [p for p in old_path.split('/') if p]
    
    if not old_path_parts:
        return None
    
    # 3. Benzer URL'leri bul
    candidates = []
    
    for sitemap_url in sitemap_urls:
        parsed_sitemap = urlparse(sitemap_url)
        sitemap_path = parsed_sitemap.path.rstrip('/')
        sitemap_path_parts = [p for p in sitemap_path.split('/') if p]
        
        if not sitemap_path_parts:
            continue
        
        # Path benzerliği hesapla
        similarity = difflib.SequenceMatcher(None, old_path_parts, sitemap_path_parts).ratio()
        
        # Son segment benzerliği (ör: "cosmetic-dentistry-turkey" -> "dental-treatments")
        last_part_similarity = 0
        if old_path_parts and sitemap_path_parts:
            last_old = old_path_parts[-1].lower()
            last_sitemap = sitemap_path_parts[-1].lower()
            last_part_similarity = difflib.SequenceMatcher(None, last_old, last_sitemap).ratio()
        
        # Kombine skor (path benzerliği + son segment benzerliği)
        combined_score = (similarity * 0.7) + (last_part_similarity * 0.3)
        
        if combined_score > 0.3:  # Minimum benzerlik eşiği
            candidates.append({
                "url": sitemap_url,
                "score": combined_score,
                "path_parts": len(sitemap_path_parts)
            })
    
    # 4. En yüksek skorlu ve en kısa path'e sahip URL'i seç
    if candidates:
        # Önce skora göre sırala, sonra path uzunluğuna göre (kısa olanlar öncelikli)
        candidates.sort(key=lambda x: (-x["score"], x["path_parts"]))
        best_match = candidates[0]
        
        if best_match["score"] > 0.5:  # Yeterince benzer
            return best_match["url"]
    
    # 5. Eğer benzer bulunamadıysa, aynı kategori/klasör altındaki URL'leri dene
    if len(old_path_parts) > 1:
        parent_path = '/'.join(old_path_parts[:-1])  # Son segment hariç
        
        for sitemap_url in sitemap_urls:
            parsed_sitemap = urlparse(sitemap_url)
            sitemap_path = parsed_sitemap.path.rstrip('/')
            
            if sitemap_path.startswith(parent_path):
                return sitemap_url
    
    # 6. Son çare: Ana sayfa veya blog sayfası
    domain = site.domain if not site.domain.startswith('http') else urlparse(site.domain).netloc
    base_url = f"https://{domain}" if not domain.startswith('http') else domain
    
    # Blog sayfası bul
    blog_candidates = [
        f"{base_url}/blog",
        f"{base_url}/blog/",
        f"{base_url}/dental-blog",
        f"{base_url}/dental-blog/",
        base_url,
        f"{base_url}/"
    ]
    
    for blog_url in blog_candidates:
        if blog_url in sitemap_urls:
            return blog_url
    
    return None




