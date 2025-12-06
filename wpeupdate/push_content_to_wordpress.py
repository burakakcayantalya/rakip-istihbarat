#!/usr/bin/env python3
"""
Elementor Content Extracted JSON'daki değişiklikleri WordPress'e push eder
"""

import json
import asyncio
import httpx
import re
from typing import Dict, List, Optional
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import sys
import os

# Ana dizini path'e ekle (core.database ve agents için)
main_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, main_dir)

# Veritabanından site bilgilerini al
from core.database import SessionLocal, Site
from agents.link_fixer.wordpress_fixer import WordPressAPILinkFixer

def get_site_credentials(domain: str = "mommymakeoverturkey.net"):
    """Veritabanından site bilgilerini al"""
    db = SessionLocal()
    try:
        site = db.query(Site).filter(
            Site.domain.like(f"%{domain}%"),
            Site.is_competitor == False
        ).first()
        
        if not site:
            return None, None, None
        
        if not site.wp_api_url or not site.wp_api_username or not site.wp_api_password:
            return None, None, None
        
        return site.wp_api_url, site.wp_api_username, site.wp_api_password
    finally:
        db.close()

def find_element_by_id_recursive(element: Dict, element_id: str) -> Optional[Dict]:
    """Elementor JSON'da element_id'ye göre elementi bul"""
    if element.get("id") == element_id:
        return element
    
    elements = element.get("elements", [])
    for child in elements:
        result = find_element_by_id_recursive(child, element_id)
        if result:
            return result
    
    return None

def apply_content_changes_to_elementor(
    original_elementor_json: str,
    extracted_changes: Dict
) -> str:
    """
    Extracted JSON'daki değişiklikleri orijinal Elementor JSON'a uygular
    Sadece değişiklik yapılan öğeleri günceller (original != content)
    """
    try:
        # Orijinal Elementor JSON'u parse et
        if isinstance(original_elementor_json, str):
            elementor_data = json.loads(original_elementor_json)
        else:
            elementor_data = original_elementor_json
        
        # Değişiklikleri saptayıp uygula
        all_changes = extracted_changes.get("all", [])
        changes_applied = 0
        changes_detected = 0
        
        print("🔍 Değişiklikler kontrol ediliyor...")
        
        for change in all_changes:
            element_id = change.get("element_id")
            change_type = change.get("type")
            new_content = change.get("content")
            new_url = change.get("url")  # Link için
            original_content = change.get("original")  # Orijinal değer
            
            if not element_id:
                continue
            
            # Değişiklik kontrolü: original != content ise değişiklik var
            has_content_change = False
            has_url_change = False
            
            if change_type == "heading" or change_type == "paragraph":
                # HTML tag'lerini temizle ve karşılaştır
                import re
                original_clean = re.sub(r'<[^>]+>', '', str(original_content)).strip() if original_content else ""
                new_clean = str(new_content).strip() if new_content else ""
                has_content_change = (original_clean != new_clean)
            elif change_type == "link":
                original_url = change.get("original_url", "")
                # Icon list item'ları için: content bazen URL olabilir, original_content None olabilir
                if change.get("widget_type") == "icon-list-item" or change.get("widget_type") == "icon-list":
                    # Eğer original_content None ise ama content URL gibi görünüyorsa, onu original_content olarak kullan
                    if not original_content and new_content:
                        # Content URL formatında mı kontrol et
                        if isinstance(new_content, str) and (new_content.startswith("http://") or new_content.startswith("https://")):
                            # Content URL ise, original_content olarak kullan
                            original_content = new_content
                
                # Eğer original_url yoksa, orijinal JSON'dan URL'yi al
                if not original_url:
                    # Elementi bul ve mevcut URL'yi al
                    temp_element = None
                    for section in elementor_data:
                        temp_element = find_element_by_id_recursive(section, element_id)
                        if temp_element:
                            break
                    if temp_element:
                        temp_settings = temp_element.get("settings", {})
                        temp_link = temp_settings.get("link", {})
                        if isinstance(temp_link, dict):
                            original_url = temp_link.get("url", "")
                        # Icon list için
                        if not original_url and temp_settings.get("icon_list"):
                            for icon_item in temp_settings.get("icon_list", []):
                                if isinstance(icon_item, dict):
                                    item_link = icon_item.get("link", {})
                                    if isinstance(item_link, dict) and item_link.get("url"):
                                        # İlk URL'yi al (daha iyi eşleştirme için text'e de bakılabilir)
                                        if icon_item.get("text") == str(original_content):
                                            original_url = item_link.get("url", "")
                                            break
                
                has_content_change = (str(original_content) != str(new_content)) if original_content else False
                has_url_change = (str(original_url) != str(new_url)) if original_url and new_url else False
            
            # Değişiklik yoksa atla
            if not has_content_change and not has_url_change:
                continue
            
            changes_detected += 1
            
            # Elementi bul
            element = None
            for section in elementor_data:
                element = find_element_by_id_recursive(section, element_id)
                if element:
                    break
            
            if not element:
                print(f"⚠️  Element bulunamadı: {element_id}")
                continue
            
            settings = element.get("settings", {})
            
            # Heading değişikliği
            if change_type == "heading":
                if "title" in settings:
                    old_title = settings.get("title", "")
                    settings["title"] = new_content
                    changes_applied += 1
                    print(f"✅ Heading güncellendi: {element_id}")
                    print(f"   Eski: {str(old_title)[:50]}...")
                    print(f"   Yeni: {new_content[:50]}...")
                elif "title_text" in settings:
                    old_title = settings.get("title_text", "")
                    settings["title_text"] = new_content
                    changes_applied += 1
                    print(f"✅ Heading güncellendi: {element_id}")
                    print(f"   Eski: {str(old_title)[:50]}...")
                    print(f"   Yeni: {new_content[:50]}...")
            
            # Paragraph değişikliği
            elif change_type == "paragraph":
                editor = settings.get("editor", "")
                paragraph_index = change.get("paragraph_index", 0)
                
                if editor:
                    # HTML içindeki paragrafı güncelle
                    soup = BeautifulSoup(editor, 'html.parser')
                    paragraphs = soup.find_all('p')
                    
                    if paragraph_index < len(paragraphs):
                        old_para = paragraphs[paragraph_index].get_text()
                        # Paragrafı değiştir
                        paragraphs[paragraph_index].string = new_content
                        settings["editor"] = str(soup)
                        changes_applied += 1
                        print(f"✅ Paragraf güncellendi: {element_id} (index {paragraph_index})")
                        print(f"   Eski: {old_para[:50]}...")
                        print(f"   Yeni: {new_content[:50]}...")
                    else:
                        # Yeni paragraf ekle
                        new_p = soup.new_tag('p')
                        new_p.string = new_content
                        soup.append(new_p)
                        settings["editor"] = str(soup)
                        changes_applied += 1
                        print(f"✅ Yeni paragraf eklendi: {element_id} -> {new_content[:50]}...")
                else:
                    # Editor yoksa direkt ekle
                    settings["editor"] = f"<p>{new_content}</p>"
                    changes_applied += 1
                    print(f"✅ Paragraf eklendi (editor yoktu): {element_id} -> {new_content[:50]}...")
            
            # Link değişikliği
            elif change_type == "link":
                # Icon list içindeki linkler (özel işlem)
                if change.get("widget_type") == "icon-list-item" or change.get("widget_type") == "icon-list":
                    icon_list = settings.get("icon_list", [])
                    if not icon_list:
                        print(f"⚠️  Icon list bulunamadı: {element_id}")
                    else:
                        found_match = False
                        change_id = change.get("_id", "")  # Icon list item'ın _id'si
                        
                        for icon_item in icon_list:
                            if isinstance(icon_item, dict):
                                item_id = icon_item.get("_id", "")
                                item_text = icon_item.get("text", "")
                                item_link = icon_item.get("link", {})
                                item_url = item_link.get("url", "") if isinstance(item_link, dict) else ""
                                
                                # Önce _id ile eşleştir (en güvenilir)
                                id_matches = (item_id == change_id) if change_id and item_id else False
                                
                                # Normalize URLs (trailing slash'i ignore et)
                                item_url_normalized = item_url.rstrip('/') if item_url else ""
                                original_url_normalized = str(original_url).rstrip('/') if original_url else ""
                                
                                # Text ile eşleştir (icon list item'larında content = text)
                                text_matches = (str(item_text) == str(original_content)) if original_content else False
                                if not text_matches and new_content:
                                    # new_content text olabilir
                                    text_matches = (str(item_text) == str(new_content))
                                
                                # URL ile eşleştir
                                url_matches = (item_url_normalized == original_url_normalized) if original_url_normalized and item_url_normalized else False
                                
                                # Content ile URL eşleştirmesi (icon list item'larında content bazen URL olabilir)
                                if not text_matches and not url_matches and original_content:
                                    content_as_url = str(original_content).rstrip('/')
                                    url_matches = (content_as_url == item_url_normalized) if item_url_normalized else False
                                
                                # Eğer hala eşleşme yoksa, new_content ile de kontrol et (content URL formatında olabilir)
                                if not text_matches and not url_matches and new_content:
                                    if isinstance(new_content, str) and (new_content.startswith("http://") or new_content.startswith("https://")):
                                        new_content_normalized = str(new_content).rstrip('/')
                                        url_matches = (new_content_normalized == item_url_normalized) if item_url_normalized else False
                                
                                # _id, text veya URL ile eşleşme
                                if id_matches or text_matches or url_matches:
                                    found_match = True
                                    # Text değişikliği varsa güncelle
                                    if has_content_change and new_content:
                                        icon_item["text"] = new_content
                                    
                                    # URL değişikliği varsa güncelle
                                    if has_url_change and new_url:
                                        if not isinstance(item_link, dict):
                                            icon_item["link"] = {}
                                        icon_item["link"]["url"] = new_url
                                    
                                    changes_applied += 1
                                    print(f"✅ Icon list link güncellendi: {element_id}")
                                    if has_content_change:
                                        print(f"   Metin - Eski: {item_text[:50]}...")
                                        print(f"   Metin - Yeni: {new_content[:50]}...")
                                    if has_url_change:
                                        print(f"   URL - Eski: {item_url}")
                                        print(f"   URL - Yeni: {new_url}")
                                    break
                        
                        if not found_match:
                            print(f"⚠️  Icon list item eşleşmedi: {element_id}")
                            print(f"   Aranan text: {original_content}")
                            print(f"   Aranan URL: {original_url}")
                            print(f"   Icon list item sayısı: {len(icon_list)}")
                else:
                    # Normal button/link widget'ları için
                    link = settings.get("link", {})
                    original_url = change.get("original_url", "")
                    
                    if isinstance(link, dict):
                        old_url = link.get("url", "")
                        old_text = settings.get("text") or settings.get("title") or settings.get("title_text", "")
                        
                        if has_url_change and new_url:
                            link["url"] = new_url
                        if has_content_change and new_content:
                            # Button text'i güncelle
                            if "text" in settings:
                                settings["text"] = new_content
                            elif "title" in settings:
                                settings["title"] = new_content
                            elif "title_text" in settings:
                                settings["title_text"] = new_content
                        settings["link"] = link
                        changes_applied += 1
                        print(f"✅ Link güncellendi: {element_id}")
                        if has_content_change:
                            print(f"   Metin - Eski: {str(old_text)[:50]}...")
                            print(f"   Metin - Yeni: {new_content[:50]}...")
                        if has_url_change:
                            print(f"   URL - Eski: {old_url}")
                            print(f"   URL - Yeni: {new_url}")
        
        print(f"\n📊 Değişiklik Özeti:")
        print(f"   Tespit edilen değişiklik: {changes_detected}")
        print(f"   Uygulanan değişiklik: {changes_applied}")
        
        if changes_detected == 0:
            print("\n⚠️  Hiç değişiklik bulunamadı!")
            print("   elementor_content_extracted.json dosyasında 'content' değerlerini değiştirdiğinizden emin olun.")
            return None
        
        # JSON'a çevir
        return json.dumps(elementor_data, ensure_ascii=False)
    
    except Exception as e:
        print(f"❌ Hata: {e}")
        import traceback
        traceback.print_exc()
        return None

async def update_wordpress_elementor(
    wp_url: str,
    post_id: int,
    post_type: str,
    elementor_json: str,
    auth: tuple
):
    """WordPress'te Elementor JSON'u güncelle (Custom endpoint kullanarak)"""
    custom_api_base = f"{wp_url.rstrip('/')}/wp-json/custom/v1"
    
    print(f"\n📤 WordPress'e gönderiliyor...")
    print(f"   Post ID: {post_id}, Type: {post_type}")
    print(f"   Endpoint: {custom_api_base}/elementor-update-content")
    
    # Custom endpoint ile güncelle
    async with httpx.AsyncClient(timeout=60.0) as client:
        update_url = f"{custom_api_base}/elementor-update-content"
        
        update_data = {
            "id": post_id,
            "elementor_data": elementor_json
        }
        
        response = await client.post(
            update_url,
            auth=auth,
            json=update_data
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Elementor data WordPress'e gönderildi")
            print(f"   Mesaj: {result.get('message', 'Başarılı')}")
            print(f"   Cache temizlendi: {result.get('cache_cleared', False)}")
            print(f"   Sayfa güncellendi: {result.get('page_updated', False)}")
            return True
        else:
            print(f"❌ WordPress güncelleme hatası: HTTP {response.status_code}")
            try:
                error_data = response.json()
                error_msg = error_data.get('message', response.text[:500])
            except:
                error_msg = response.text[:500]
            print(f"   Hata: {error_msg}")
            return False

async def main():
    # Dosyaları oku
    print("📖 Dosyalar okunuyor...")
    print("=" * 60)
    
    # Extracted JSON'u oku
    try:
        with open("elementor_content_extracted.json", "r", encoding="utf-8") as f:
            extracted_changes = json.load(f)
    except FileNotFoundError:
        print("❌ elementor_content_extracted.json dosyası bulunamadı!")
        print("   Önce 'python sync_from_wordpress.py' komutunu çalıştırın.")
        return
    
    # Orijinal JSON dosyasını bul (domain'e göre)
    wp_url, wp_username, wp_password = get_site_credentials()
    if wp_url:
        domain = urlparse(wp_url).netloc.replace('.', '_')
        original_json_file = f"{domain}_elementor.json"
    else:
        # Varsayılan dosya adı
        original_json_file = "mommymakeoverturkey_net_elementor.json"
    
    try:
        with open(original_json_file, "r", encoding="utf-8") as f:
            original_elementor_json = f.read()
    except FileNotFoundError:
        print(f"❌ {original_json_file} dosyası bulunamadı!")
        print("   Önce 'python sync_from_wordpress.py' komutunu çalıştırın.")
        return
    
    print(f"✅ Dosyalar okundu")
    print(f"   Orijinal JSON: {original_json_file}")
    print(f"   Extracted JSON: elementor_content_extracted.json")
    print(f"   Toplam öğe: {len(extracted_changes.get('all', []))}")
    
    # Değişiklikleri uygula
    print(f"\n🔄 Değişiklikler uygulanıyor...")
    updated_elementor_json = apply_content_changes_to_elementor(
        original_elementor_json,
        extracted_changes
    )
    
    if not updated_elementor_json:
        print("❌ Değişiklikler uygulanamadı!")
        return
    
    # WordPress bilgilerini al
    wp_url, wp_username, wp_password = get_site_credentials()
    
    if not wp_url or not wp_username or not wp_password:
        print("\n⚠️  WordPress API bilgileri bulunamadı!")
        print("   Manuel olarak girebilirsiniz.\n")
        import getpass
        wp_url = input("WordPress Site URL: ").strip() or "https://mommymakeoverturkey.net"
        wp_username = input("WordPress Kullanıcı Adı: ").strip()
        wp_password = getpass.getpass("WordPress Application Password: ").strip()
        
        if not wp_username or not wp_password:
            print("\n❌ Kullanıcı adı ve şifre gerekli!")
            return
    
    # Post ID'yi bul (URL'den)
    if not wp_url:
        print("\n⚠️  WordPress API bilgileri bulunamadı!")
        print("   Manuel olarak girebilirsiniz.\n")
        import getpass
        wp_url = input("WordPress Site URL: ").strip() or "https://mommymakeoverturkey.net"
        wp_username = input("WordPress Kullanıcı Adı: ").strip()
        wp_password = getpass.getpass("WordPress Application Password: ").strip()
        
        if not wp_username or not wp_password:
            print("\n❌ Kullanıcı adı ve şifre gerekli!")
            return
    
    # Post ID'yi URL'den bul
    print("\n🔍 Sayfa ID'si bulunuyor...")
    auth = (wp_username, wp_password)
    
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
    
    result = await get_post_by_url(wp_url, wp_url.rstrip('/'), auth)
    
    if not result:
        print("❌ Sayfa bulunamadı!")
        return
    
    post_id, post_type = result
    print(f"✅ Sayfa bulundu: ID={post_id}, Type={post_type}")
    
    # Önce custom endpoint'i dene
    print(f"\n📤 WordPress'e gönderiliyor...")
    custom_api_base = f"{wp_url.rstrip('/')}/wp-json/custom/v1"
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Custom endpoint ile güncelle (yeni endpoint adı)
        update_url = f"{custom_api_base}/update-elementor-page"
        update_data = {
            "post_id": post_id,
            "elementor_data": updated_elementor_json
        }
        
        print(f"   🔍 Custom endpoint deneniyor: {update_url}")
        response = await client.post(
            update_url,
            auth=(wp_username, wp_password),
            json=update_data
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"\n✅ Başarılı! Değişiklikler WordPress'e gönderildi (custom endpoint)")
            print(f"   Mesaj: {result.get('message', 'Başarılı')}")
            print(f"   Cache temizlendi: {result.get('cache_cleared', False)}")
            print(f"   Sayfayı kontrol edin: {wp_url}")
            return
        
        # Custom endpoint çalışmadıysa, Link Fixer metodunu dene
        print(f"   ⚠️  Custom endpoint hatası: HTTP {response.status_code}")
        if response.status_code != 404:
            try:
                error_data = response.json()
                error_msg = error_data.get('message', response.text[:500])
            except:
                error_msg = response.text[:500]
            print(f"   Hata detayı: {error_msg}")
        
        print(f"\n   🔄 Link Fixer metodu deneniyor...")
        fixer = WordPressAPILinkFixer(wp_url, wp_username, wp_password)
        
        success, message = await fixer.update_elementor_data(
            post_id=post_id,
            elementor_json=updated_elementor_json,
            post_type=post_type,
            logs=[]
        )
        
        if success:
            print(f"\n✅ Başarılı! Değişiklikler WordPress'e gönderildi (meta endpoint)")
            print(f"   Mesaj: {message}")
            print(f"   Sayfayı kontrol edin: {wp_url}")
        else:
            print(f"\n❌ WordPress'e gönderilemedi!")
            print(f"   Hata: {message}")
            print(f"\n   💡 İpucu: wordpress_functions_fix.php dosyasının WordPress'e eklendiğinden emin olun")

if __name__ == "__main__":
    asyncio.run(main())

