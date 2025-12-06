#!/usr/bin/env python3
"""
WordPress'ten güncel Elementor JSON'unu çeker ve elementor_content_extracted.json dosyasını günceller
Kullanım: python sync_from_wordpress.py
"""

import asyncio
import httpx
import json
from urllib.parse import urlparse
import sys
import os

# Ana dizini path'e ekle (core.database için)
main_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, main_dir)

# wpeupdate klasörünü path'e ekle (extract_content_from_elementor için)
wpeupdate_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, wpeupdate_dir)

from core.database import SessionLocal, Site
from extract_content_from_elementor import extract_all_content

def get_site_credentials(domain: str = "mommymakeoverturkey.net"):
    """Veritabanından site bilgilerini al"""
    db = SessionLocal()
    try:
        site = db.query(Site).filter(
            Site.domain.like(f"%{domain}%"),
            Site.is_competitor == False
        ).first()
        
        if not site:
            return None, None, None, None
        
        if not site.wp_api_url or not site.wp_api_username or not site.wp_api_password:
            return None, None, None, None
        
        return site.wp_api_url, site.wp_api_username, site.wp_api_password, site.domain
    finally:
        db.close()

async def get_post_by_url(wp_url: str, url: str, auth: tuple):
    """URL'den WordPress post/page ID'sini bul"""
    api_base = f"{wp_url.rstrip('/')}/wp-json/wp/v2"
    parsed = urlparse(url)
    path = parsed.path.strip('/')
    slug = path.split('/')[-1] if path else None
    
    if not slug or slug == "":
        # Ana sayfa
        for endpoint in ['pages', 'posts']:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{api_base}/{endpoint}?slug=home&per_page=1",
                    auth=auth
                )
                if response.status_code == 200:
                    data = response.json()
                    if data and len(data) > 0:
                        return (data[0]['id'], endpoint)
        
        # Ana sayfa için alternatif: ID=1
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{api_base}/pages/1",
                auth=auth
            )
            if response.status_code == 200:
                return (1, 'page')
        
        return None
    
    # Slug ile ara
    for endpoint in ['pages', 'posts']:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{api_base}/{endpoint}?slug={slug}&per_page=1",
                auth=auth
            )
            if response.status_code == 200:
                data = response.json()
                if data and len(data) > 0:
                    return (data[0]['id'], endpoint)
    
    return None

async def get_elementor_data(wp_url: str, post_id: int, post_type: str, auth: tuple):
    """Elementor JSON data'yı al"""
    api_base = f"{wp_url.rstrip('/')}/wp-json/wp/v2"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # REST API'den post/page objesini al
        response = await client.get(
            f"{api_base}/{post_type}/{post_id}",
            auth=auth
        )
        
        if response.status_code == 200:
            post_data = response.json()
            
            if '_elementor_data' in post_data:
                elementor_data = post_data['_elementor_data']
                if elementor_data:
                    if isinstance(elementor_data, str):
                        return elementor_data
                    else:
                        return json.dumps(elementor_data, ensure_ascii=False)
        
        # Meta endpoint'ini dene
        response_meta = await client.get(
            f"{api_base}/{post_type}/{post_id}/meta",
            auth=auth
        )
        
        if response_meta.status_code == 200:
            meta_data = response_meta.json()
            if isinstance(meta_data, list):
                for meta_item in meta_data:
                    if meta_item.get('key') == '_elementor_data':
                        elementor_json = meta_item.get('value')
                        if elementor_json:
                            if isinstance(elementor_json, str):
                                return elementor_json
                            else:
                                return json.dumps(elementor_json, ensure_ascii=False)
    
    return None

async def main():
    print("🔄 WordPress'ten güncel Elementor JSON çekiliyor...")
    print("=" * 60)
    
    # Veritabanından site bilgilerini al
    wp_url, wp_username, wp_password, domain = get_site_credentials()
    
    if not wp_url or not wp_username or not wp_password:
        print("\n⚠️  WordPress API bilgileri veritabanında bulunamadı!")
        print("   Manuel olarak girebilirsiniz.\n")
        import getpass
        wp_url = input("WordPress Site URL: ").strip() or "https://mommymakeoverturkey.net"
        wp_username = input("WordPress Kullanıcı Adı: ").strip()
        wp_password = getpass.getpass("WordPress Application Password: ").strip()
        domain = urlparse(wp_url).netloc
        
        if not wp_username or not wp_password:
            print("\n❌ Kullanıcı adı ve şifre gerekli!")
            return
    
    auth = (wp_username, wp_password)
    page_url = wp_url.rstrip('/')
    
    print(f"🌐 Site: {page_url}")
    print(f"👤 Kullanıcı: {wp_username}")
    print("-" * 60)
    
    # Post ID'yi bul
    print("🔍 Sayfa ID'si bulunuyor...")
    result = await get_post_by_url(wp_url, page_url, auth)
    if not result:
        print("❌ Sayfa bulunamadı!")
        return
    
    post_id, post_type = result
    print(f"✅ Sayfa bulundu: ID={post_id}, Type={post_type}")
    
    # Elementor data'yı al
    print("\n📥 Elementor JSON indiriliyor...")
    elementor_json = await get_elementor_data(wp_url, post_id, post_type, auth)
    
    if not elementor_json:
        print("❌ Elementor data bulunamadı!")
        return
    
    # Orijinal JSON'u kaydet
    domain_clean = domain.replace('.', '_')
    original_json_file = f"{domain_clean}_elementor.json"
    with open(original_json_file, 'w', encoding='utf-8') as f:
        f.write(elementor_json)
    
    print(f"✅ Orijinal JSON kaydedildi: {original_json_file}")
    print(f"📊 JSON boyutu: {len(elementor_json)} karakter")
    
    # İçerikleri extract et
    print("\n🔍 İçerikler çıkarılıyor...")
    extracted_content = extract_all_content(elementor_json)
    
    if not extracted_content:
        print("❌ İçerik çıkarılamadı!")
        return
    
    stats = extracted_content["stats"]
    print(f"✅ İçerikler çıkarıldı:")
    print(f"   📝 H Tagları: {stats['total_headings']}")
    print(f"   📄 Paragraflar: {stats['total_paragraphs']}")
    print(f"   🔗 Linkler: {stats['total_links']}")
    print(f"   📊 Toplam: {stats['total_items']}")
    
    # Extracted JSON'u kaydet
    extracted_json_file = "elementor_content_extracted.json"
    with open(extracted_json_file, 'w', encoding='utf-8') as f:
        json.dump(extracted_content, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Extracted JSON güncellendi: {extracted_json_file}")
    print("\n" + "=" * 60)
    print("✅ Tamamlandı! Artık elementor_content_extracted.json dosyasını düzenleyebilirsiniz.")
    print("   Değişiklikleri push etmek için: python push_to_wordpress.py")

if __name__ == "__main__":
    asyncio.run(main())

