#!/usr/bin/env python3
"""
Elementor JSON'dan H taglarını, paragrafları ve linkleri çıkarır
"""

import json
import re
from typing import List, Dict
from bs4 import BeautifulSoup

def extract_content_recursive(element: Dict, results: List[Dict], path: str = ""):
    """
    Elementor JSON yapısını recursive olarak tarar ve içerikleri çıkarır
    """
    el_type = element.get("elType", "")
    widget_type = element.get("widgetType", "")
    settings = element.get("settings", {})
    element_id = element.get("id", "")
    
    current_path = f"{path}/{el_type}" if path else el_type
    if widget_type:
        current_path += f"/{widget_type}"
    
    # H1-H6 Tagları (Heading Widget)
    if widget_type == "heading":
        title = settings.get("title") or settings.get("title_text", "")
        header_size = settings.get("header_size", "h2")
        
        if title:
            # HTML tag'lerini temizle
            title_clean = re.sub(r'<[^>]+>', '', str(title)).strip()
            if title_clean:
                results.append({
                    "type": "heading",
                    "tag": header_size if header_size.startswith("h") else f"h{header_size}",
                    "content": title_clean,
                    "original": title,
                    "element_id": element_id,
                    "path": current_path,
                    "settings": {
                        "header_size": header_size,
                        "title_color": settings.get("title_color"),
                        "align": settings.get("align", "left")
                    }
                })
    
    # Paragraflar (Text Editor Widget)
    if widget_type == "text-editor":
        editor = settings.get("editor", "")
        
        if editor:
            # HTML içeriğini parse et
            soup = BeautifulSoup(editor, 'html.parser')
            
            # Paragrafları bul
            paragraphs = soup.find_all('p')
            for idx, p in enumerate(paragraphs):
                p_text = p.get_text().strip()
                if p_text:
                    results.append({
                        "type": "paragraph",
                        "tag": "p",
                        "content": p_text,
                        "original": str(p),
                        "element_id": element_id,
                        "path": current_path,
                        "paragraph_index": idx,
                        "settings": {
                            "align": settings.get("align", "left"),
                            "text_color": settings.get("text_color")
                        }
                    })
            
            # H taglarını da kontrol et (text-editor içinde olabilir)
            headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
            for h in headings:
                h_text = h.get_text().strip()
                if h_text:
                    results.append({
                        "type": "heading",
                        "tag": h.name,
                        "content": h_text,
                        "original": str(h),
                        "element_id": element_id,
                        "path": current_path,
                        "settings": {}
                    })
    
    # Linkler (Button Widget veya link içeren widget'lar)
    link = settings.get("link", {})
    if isinstance(link, dict):
        url = link.get("url", "")
        if url:
            text = settings.get("text", "") or settings.get("title", "") or settings.get("title_text", "") or url
            text_clean = re.sub(r'<[^>]+>', '', str(text)).strip()
            
            if text_clean and url:
                results.append({
                    "type": "link",
                    "tag": "a",
                    "content": text_clean,
                    "url": url,
                    "original_url": url,  # Orijinal URL'yi sakla
                    "element_id": element_id,
                    "path": current_path,
                    "widget_type": widget_type,
                    "settings": {
                        "is_external": link.get("is_external", False),
                        "nofollow": link.get("nofollow", False)
                    }
                })
    
    # Icon List içindeki linkler
    if widget_type == "icon-list":
        icon_list = settings.get("icon_list", [])
        for icon_item in icon_list:
            if isinstance(icon_item, dict):
                item_link = icon_item.get("link", {})
                if isinstance(item_link, dict):
                    item_url = item_link.get("url", "")
                    item_text = icon_item.get("text", "")
                    if item_url and item_text:
                        results.append({
                            "type": "link",
                            "tag": "a",
                            "content": item_text,
                            "url": item_url,
                            "original_url": item_url,  # Orijinal URL'yi sakla
                            "original": item_text,  # Orijinal text'i sakla
                            "element_id": element_id,
                            "path": current_path,
                            "widget_type": "icon-list-item",
                            "_id": icon_item.get("_id", ""),  # Icon list item'ın _id'sini sakla
                            "settings": {
                                "is_external": item_link.get("is_external", False),
                                "nofollow": item_link.get("nofollow", False)
                            }
                        })
    
    # Recursive: Alt elementleri tara
    elements = element.get("elements", [])
    for child_element in elements:
        extract_content_recursive(child_element, results, current_path)

def extract_all_content(elementor_json: str) -> Dict:
    """
    Elementor JSON'dan tüm içerikleri çıkarır
    """
    try:
        if isinstance(elementor_json, str):
            data = json.loads(elementor_json)
        else:
            data = elementor_json
        
        results = []
        
        # Ana elementleri tara
        if isinstance(data, list):
            for element in data:
                extract_content_recursive(element, results)
        elif isinstance(data, dict):
            extract_content_recursive(data, results)
        
        # Sonuçları kategorize et
        headings = [r for r in results if r["type"] == "heading"]
        paragraphs = [r for r in results if r["type"] == "paragraph"]
        links = [r for r in results if r["type"] == "link"]
        
        return {
            "headings": headings,
            "paragraphs": paragraphs,
            "links": links,
            "all": results,
            "stats": {
                "total_headings": len(headings),
                "total_paragraphs": len(paragraphs),
                "total_links": len(links),
                "total_items": len(results)
            }
        }
    except Exception as e:
        print(f"❌ Hata: {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    # JSON dosyasını oku
    with open("mommymakeoverturkey_net_elementor.json", "r", encoding="utf-8") as f:
        elementor_json = f.read()
    
    print("🔍 Elementor JSON analiz ediliyor...")
    print("-" * 60)
    
    # İçerikleri çıkar
    content = extract_all_content(elementor_json)
    
    if not content:
        print("❌ İçerik çıkarılamadı!")
        return
    
    stats = content["stats"]
    print(f"\n📊 İstatistikler:")
    print(f"   H Tagları: {stats['total_headings']}")
    print(f"   Paragraflar: {stats['total_paragraphs']}")
    print(f"   Linkler: {stats['total_links']}")
    print(f"   Toplam: {stats['total_items']}")
    
    # Sonuçları JSON olarak kaydet
    output_file = "elementor_content_extracted.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(content, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ İçerikler çıkarıldı ve kaydedildi: {output_file}")
    
    # Örnek göster
    print(f"\n📋 Örnek H Tagları (ilk 5):")
    for i, h in enumerate(content["headings"][:5], 1):
        print(f"   {i}. [{h['tag']}] {h['content'][:80]}...")
    
    print(f"\n📋 Örnek Paragraflar (ilk 3):")
    for i, p in enumerate(content["paragraphs"][:3], 1):
        print(f"   {i}. {p['content'][:100]}...")
    
    print(f"\n📋 Örnek Linkler (ilk 5):")
    for i, link in enumerate(content["links"][:5], 1):
        print(f"   {i}. {link['content']} -> {link['url']}")

if __name__ == "__main__":
    main()

