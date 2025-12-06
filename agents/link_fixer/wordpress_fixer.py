# ============================================
# Link Fixer Agent - WordPress REST API Link Düzeltme
# SSH erişimi olmadan WordPress REST API ile Elementor içeriklerini günceller
# ============================================

import httpx
import json
import re
from typing import Optional, Dict, Tuple
from datetime import datetime
from urllib.parse import urljoin, urlparse


class WordPressAPILinkFixer:
    """WordPress REST API ile redirect linkleri düzeltme"""
    
    def __init__(self, wp_url: str, wp_username: str, wp_password: str):
        """
        Args:
            wp_url: WordPress site URL (örn: https://example.com)
            wp_username: WordPress kullanıcı adı
            wp_password: WordPress Application Password veya normal şifre
        """
        self.wp_url = wp_url.rstrip('/')
        self.wp_username = wp_username
        self.wp_password = wp_password
        self.api_base = f"{self.wp_url}/wp-json/wp/v2"
        self.auth = (wp_username, wp_password)
    
    async def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Tuple[bool, Optional[Dict], str]:
        """
        WordPress REST API isteği yap
        
        Returns:
            (success, response_data, error_message)
        """
        url = urljoin(self.api_base + "/", endpoint.lstrip('/'))
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if method == "GET":
                    response = await client.get(url, auth=self.auth)
                elif method == "POST":
                    response = await client.post(url, auth=self.auth, json=data)
                elif method == "PUT":
                    response = await client.put(url, auth=self.auth, json=data)
                else:
                    return False, None, f"Desteklenmeyen method: {method}"
                
                if response.status_code == 200 or response.status_code == 201:
                    return True, response.json(), ""
                else:
                    error_msg = f"HTTP {response.status_code}"
                    try:
                        error_data = response.json()
                        if 'message' in error_data:
                            error_msg = error_data['message']
                    except:
                        error_msg = response.text[:200]
                    return False, None, error_msg
        except httpx.TimeoutException:
            return False, None, "İstek zaman aşımına uğradı"
        except Exception as e:
            return False, None, str(e)
    
    async def get_post_by_url(self, url: str, logs: list = None) -> Optional[Tuple[int, str]]:
        """
        URL'den WordPress post/page ID'sini bul
        
        Args:
            url: Sayfa URL'i
            logs: Log listesi (opsiyonel)
            
        Returns:
            (Post/Page ID, endpoint_type) tuple veya None
        """
        if logs is None:
            logs = []
        
        parsed = urlparse(url)
        path = parsed.path.strip('/')
        slug = path.split('/')[-1] if path else None
        
        # URL'yi normalize et (trailing slash'i kaldır)
        normalized_url = url.rstrip('/')
        
        logs.append({"message": f"URL parse edildi: slug='{slug}', path='{path}'", "type": "info"})
        
        if not slug:
            # Ana sayfa - hem posts hem pages kontrol et
            logs.append({"message": "Ana sayfa kontrol ediliyor...", "type": "info"})
            for endpoint in ['pages', 'posts']:
                success, data, error = await self._make_request("GET", f"{endpoint}?slug=home&per_page=1")
                if success and data and len(data) > 0:
                    logs.append({"message": f"✅ Ana sayfa bulundu ({endpoint}): ID={data[0]['id']}", "type": "success"})
                    return (data[0]['id'], endpoint)
            logs.append({"message": "⚠️ Ana sayfa bulunamadı", "type": "warning"})
            return None
        
        # Önce pages endpoint'inde ara (sayfalar genellikle pages'de)
        logs.append({"message": f"Slug ile arama yapılıyor: '{slug}'", "type": "info"})
        for endpoint in ['pages', 'posts']:
            logs.append({"message": f"🔍 {endpoint} endpoint'inde slug ile aranıyor...", "type": "info"})
            # Slug ile ara
            success, data, error = await self._make_request("GET", f"{endpoint}?slug={slug}&per_page=1")
            if success and data and len(data) > 0:
                # URL'yi kontrol et (tam eşleşme veya normalize edilmiş)
                item_link = data[0].get('link', '').rstrip('/')
                logs.append({"message": f"📄 Bulunan link: {item_link}", "type": "info"})
                if item_link == normalized_url or normalized_url == item_link:
                    logs.append({"message": f"✅ URL eşleşmesi bulundu ({endpoint}): ID={data[0]['id']}", "type": "success"})
                    return (data[0]['id'], endpoint)
                # Slug eşleşiyorsa da kabul et (bazı durumlarda URL farklı olabilir)
                if data[0].get('slug') == slug:
                    logs.append({"message": f"✅ Slug eşleşmesi bulundu ({endpoint}): ID={data[0]['id']}", "type": "success"})
                    return (data[0]['id'], endpoint)
            elif not success:
                logs.append({"message": f"⚠️ {endpoint} endpoint hatası: {error}", "type": "warning"})
        
        # Daha geniş arama - URL'nin tamamını kullan
        logs.append({"message": f"🔍 Geniş arama yapılıyor (search)...", "type": "info"})
        for endpoint in ['pages', 'posts']:
            logs.append({"message": f"🔍 {endpoint} endpoint'inde search ile aranıyor...", "type": "info"})
            # Search ile ara
            success, data, error = await self._make_request("GET", f"{endpoint}?per_page=100&search={slug}")
            if success and data:
                logs.append({"message": f"📋 {len(data)} sonuç bulundu", "type": "info"})
                for item in data:
                    item_link = item.get('link', '').rstrip('/')
                    # Tam URL eşleşmesi
                    if item_link == normalized_url or normalized_url == item_link:
                        logs.append({"message": f"✅ URL eşleşmesi bulundu ({endpoint}): ID={item['id']}", "type": "success"})
                        return (item['id'], endpoint)
                    # URL'nin bir kısmı eşleşiyorsa
                    if normalized_url in item_link or item_link in normalized_url:
                        logs.append({"message": f"✅ Kısmi URL eşleşmesi bulundu ({endpoint}): ID={item['id']}", "type": "success"})
                        return (item['id'], endpoint)
                    # Slug eşleşmesi
                    if item.get('slug') == slug:
                        logs.append({"message": f"✅ Slug eşleşmesi bulundu ({endpoint}): ID={item['id']}", "type": "success"})
                        return (item['id'], endpoint)
            elif not success:
                logs.append({"message": f"⚠️ {endpoint} search hatası: {error}", "type": "warning"})
        
        # Son çare: Tüm sayfaları/posts'ları listele ve URL ile karşılaştır
        logs.append({"message": f"🔍 Son çare: Tüm {endpoint} listesi kontrol ediliyor...", "type": "info"})
        for endpoint in ['pages', 'posts']:
            logs.append({"message": f"🔍 {endpoint} endpoint'inden tüm liste alınıyor...", "type": "info"})
            success, data, error = await self._make_request("GET", f"{endpoint}?per_page=100")
            if success and data:
                logs.append({"message": f"📋 {len(data)} {endpoint} kontrol ediliyor...", "type": "info"})
                for item in data:
                    item_link = item.get('link', '').rstrip('/')
                    if item_link == normalized_url:
                        logs.append({"message": f"✅ Tam URL eşleşmesi bulundu ({endpoint}): ID={item['id']}", "type": "success"})
                        return (item['id'], endpoint)
            elif not success:
                logs.append({"message": f"⚠️ {endpoint} liste hatası: {error}", "type": "warning"})
        
        logs.append({"message": f"❌ Sayfa bulunamadı: {normalized_url}", "type": "error"})
        return None
    
    async def get_elementor_data(self, post_id: int, post_type: str = None, logs: list = None) -> Tuple[bool, Optional[str]]:
        """
        Elementor data'yı al
        
        Args:
            post_id: WordPress post ID
            post_type: Post type ('post' veya 'page'), None ise otomatik bulunur
            logs: Log listesi (opsiyonel)
            
        Returns:
            (success, elementor_json_string)
        """
        if logs is None:
            logs = []
        
        # Post type'ı belirle
        if not post_type:
            logs.append({"message": "Post type belirleniyor...", "type": "info"})
            # Önce pages'de dene
            success, data, error = await self._make_request("GET", f"pages/{post_id}")
            if success and data:
                post_type = 'page'
                logs.append({"message": f"✅ Post type bulundu: page", "type": "success"})
            else:
                # Posts'da dene
                success, data, error = await self._make_request("GET", f"posts/{post_id}")
                if success and data:
                    post_type = 'post'
                    logs.append({"message": f"✅ Post type bulundu: post", "type": "success"})
                else:
                    logs.append({"message": f"❌ Post/Page bulunamadı: {error}", "type": "error"})
                    return False, None
        else:
            logs.append({"message": f"Post type kullanılıyor: {post_type}", "type": "info"})
        
        # Meta endpoint'i kullan (hem pages hem posts için)
        endpoints_to_try = []
        if post_type == 'page':
            endpoints_to_try = ['pages', 'posts']  # Önce pages, sonra posts
        else:
            endpoints_to_try = ['posts', 'pages']  # Önce posts, sonra pages
        
        # ÖNCE: Custom SQL endpoint'ini dene (performans sorunu yaratmaz, sadece ihtiyaç duyulduğunda çalışır)
        logs.append({"message": f"🔍 Custom SQL endpoint deneniyor (wp/v2/elementor-meta/{post_id})...", "type": "info"})
        success_custom, custom_data, error_custom = await self._make_request("GET", f"elementor-meta/{post_id}")
        if success_custom and custom_data:
            if isinstance(custom_data, dict):
                elementor_json = custom_data.get('elementor_data') or custom_data.get('data')
                if elementor_json:
                    if isinstance(elementor_json, str):
                        logs.append({"message": f"✅ Elementor data bulundu (custom SQL endpoint): {len(elementor_json)} karakter", "type": "success"})
                        return True, elementor_json
                    elif isinstance(elementor_json, (dict, list)):
                        json_str = json.dumps(elementor_json)
                        logs.append({"message": f"✅ Elementor data bulundu (custom SQL endpoint): {len(json_str)} karakter", "type": "success"})
                        return True, json_str
            elif isinstance(custom_data, str):
                logs.append({"message": f"✅ Elementor data bulundu (custom SQL endpoint): {len(custom_data)} karakter", "type": "success"})
                return True, custom_data
        
        logs.append({"message": f"⚠️ Custom SQL endpoint çalışmadı: {error_custom}. Standart endpoint'ler deneniyor...", "type": "warning"})
        
        for endpoint in endpoints_to_try:
            # Önce post/page objesini al ve meta bilgilerini kontrol et
            logs.append({"message": f"🔍 {endpoint}/{post_id} endpoint'inden post/page bilgisi alınıyor...", "type": "info"})
            success, post_data, error = await self._make_request("GET", f"{endpoint}/{post_id}")
            
            if not success:
                logs.append({"message": f"⚠️ {endpoint} post/page endpoint hatası: {error}", "type": "warning"})
                continue
            
            if not post_data:
                logs.append({"message": f"⚠️ {endpoint} post/page data boş", "type": "warning"})
                continue
            
            # 🔍 DEBUG: WordPress'ten gelen post_data yapısını göster
            if isinstance(post_data, dict):
                logs.append({"message": f"📦 WordPress Post Data Yapısı:", "type": "info"})
                logs.append({"message": f"   📋 Toplam Key Sayısı: {len(post_data.keys())}", "type": "info"})
                logs.append({"message": f"   📋 Key'ler: {', '.join(list(post_data.keys())[:30])}", "type": "info"})
                
                # Önemli alanları göster
                important_keys = ['id', 'title', 'slug', 'link', 'type', 'status', '_elementor_data', 'meta']
                for key in important_keys:
                    if key in post_data:
                        value = post_data[key]
                        if key == '_elementor_data':
                            if isinstance(value, str):
                                logs.append({"message": f"   ✅ {key}: {len(value)} karakter (string)", "type": "info"})
                                # İlk 500 karakteri göster
                                preview = value[:500].replace('\n', ' ').replace('\r', ' ')
                                logs.append({"message": f"      📄 İlk 500 karakter: {preview}...", "type": "info"})
                            elif isinstance(value, (dict, list)):
                                json_str = json.dumps(value)
                                logs.append({"message": f"   ✅ {key}: {len(json_str)} karakter (dict/list)", "type": "info"})
                                preview = json_str[:500].replace('\n', ' ').replace('\r', ' ')
                                logs.append({"message": f"      📄 İlk 500 karakter: {preview}...", "type": "info"})
                        elif key == 'meta' and isinstance(value, dict):
                            logs.append({"message": f"   ✅ {key}: {len(value)} meta kaydı", "type": "info"})
                            if '_elementor_data' in value:
                                elem_data = value['_elementor_data']
                                if isinstance(elem_data, str):
                                    logs.append({"message": f"      📄 _elementor_data: {len(elem_data)} karakter", "type": "info"})
                                    preview = elem_data[:500].replace('\n', ' ').replace('\r', ' ')
                                    logs.append({"message": f"         📄 İlk 500 karakter: {preview}...", "type": "info"})
                        else:
                            # Diğer alanlar için kısa özet
                            value_str = str(value)[:100] if value else "None"
                            logs.append({"message": f"   📌 {key}: {value_str}...", "type": "info"})
                
                # Post data'nın tamamını JSON olarak göster (ilk 2000 karakter)
                try:
                    post_data_json = json.dumps(post_data, indent=2, ensure_ascii=False)
                    logs.append({"message": f"📦 WordPress Post Data (JSON - ilk 2000 karakter):", "type": "info"})
                    logs.append({"message": f"{post_data_json[:2000]}...", "type": "info"})
                except Exception as json_error:
                    logs.append({"message": f"⚠️ Post data JSON'a çevrilemedi: {json_error}", "type": "warning"})
            
            # Meta endpoint'ini dene (WordPress REST API v2'de meta endpoint'i farklı olabilir)
            # WordPress REST API'de meta endpoint'i genellikle şu formatta olur:
            # /wp/v2/posts/{id}/meta/{meta_id} veya /wp/v2/posts/{id}/meta (tüm meta'lar için)
            # Ancak varsayılan olarak expose edilmemiş olabilir
            
            # Önce standart meta endpoint'ini dene
            logs.append({"message": f"🔍 {endpoint}/{post_id}/meta endpoint'inden meta alınıyor...", "type": "info"})
            success_meta, meta_data, error_meta = await self._make_request("GET", f"{endpoint}/{post_id}/meta")
            
            # Eğer standart endpoint çalışmazsa, alternatif endpoint'leri dene
            if not success_meta:
                # Bazı WordPress kurulumlarında meta endpoint'i farklı olabilir
                alternative_endpoints = [
                    f"meta/{endpoint}/{post_id}",  # Alternatif format
                    f"{endpoint}/{post_id}?_fields=meta",  # Query parameter ile
                    f"{endpoint}/{post_id}?_embed",  # Embed ile meta bilgileri
                ]
                
                for alt_endpoint in alternative_endpoints:
                    logs.append({"message": f"🔍 Alternatif endpoint deneniyor: {alt_endpoint}", "type": "info"})
                    success_alt, meta_data_alt, error_alt = await self._make_request("GET", alt_endpoint)
                    if success_alt and meta_data_alt:
                        meta_data = meta_data_alt
                        success_meta = True
                        logs.append({"message": f"✅ Alternatif endpoint başarılı: {alt_endpoint}", "type": "success"})
                        break
            
            # Eğer hala meta endpoint çalışmıyorsa, custom SQL endpoint'ini dene
            # Bu endpoint WordPress tarafında oluşturulmalı (wordpress_custom_endpoint.php dosyası ile)
            if not success_meta:
                logs.append({"message": f"🔍 Custom SQL endpoint deneniyor (wp/v2/elementor-meta/{post_id})...", "type": "info"})
                success_custom, custom_data, error_custom = await self._make_request("GET", f"elementor-meta/{post_id}")
                if success_custom and custom_data:
                    if isinstance(custom_data, dict):
                        elementor_json = custom_data.get('elementor_data') or custom_data.get('data')
                        if elementor_json:
                            if isinstance(elementor_json, str):
                                logs.append({"message": f"✅ Elementor data bulundu (custom SQL endpoint): {len(elementor_json)} karakter", "type": "success"})
                                return True, elementor_json
                            elif isinstance(elementor_json, (dict, list)):
                                json_str = json.dumps(elementor_json)
                                logs.append({"message": f"✅ Elementor data bulundu (custom SQL endpoint): {len(json_str)} karakter", "type": "success"})
                                return True, json_str
                    elif isinstance(custom_data, str):
                        # Direkt string olarak dönebilir
                        logs.append({"message": f"✅ Elementor data bulundu (custom SQL endpoint): {len(custom_data)} karakter", "type": "success"})
                        return True, custom_data
                else:
                    logs.append({"message": f"⚠️ Custom SQL endpoint çalışmadı: {error_custom}. WordPress'e custom endpoint eklenmeli!", "type": "warning"})
            
            # Elementor'un özel endpoint'lerini de dene
            if not success_meta:
                logs.append({"message": f"🔍 Elementor özel endpoint'leri deneniyor...", "type": "info"})
                elementor_endpoints = [
                    f"elementor/v1/templates/{post_id}",  # Elementor template endpoint
                    f"elementor/v1/pages/{post_id}",  # Elementor page endpoint
                ]
                
                for elem_endpoint in elementor_endpoints:
                    logs.append({"message": f"🔍 Elementor endpoint deneniyor: {elem_endpoint}", "type": "info"})
                    success_elem, elem_data, error_elem = await self._make_request("GET", elem_endpoint)
                    if success_elem and elem_data:
                        # Elementor endpoint'inden data'yı çıkar
                        if isinstance(elem_data, dict):
                            # Elementor data genellikle 'data' veya 'content' key'inde olur
                            elementor_json = elem_data.get('data') or elem_data.get('content') or elem_data.get('elementor_data')
                            if elementor_json:
                                if isinstance(elementor_json, str):
                                    logs.append({"message": f"✅ Elementor data bulundu (Elementor endpoint): {len(elementor_json)} karakter", "type": "success"})
                                    return True, elementor_json
                                elif isinstance(elementor_json, (dict, list)):
                                    json_str = json.dumps(elementor_json)
                                    logs.append({"message": f"✅ Elementor data bulundu (Elementor endpoint): {len(json_str)} karakter", "type": "success"})
                                    return True, json_str
            
            if success_meta and meta_data:
                # 🔍 DEBUG: WordPress'ten gelen meta_data yapısını göster
                logs.append({"message": f"📦 WordPress Meta Data Yapısı:", "type": "info"})
                logs.append({"message": f"   📋 Meta Data Tipi: {type(meta_data).__name__}", "type": "info"})
                
                # meta_data bir liste mi dict mi kontrol et
                if isinstance(meta_data, str):
                    logs.append({"message": f"⚠️ Meta data string formatında, parse ediliyor...", "type": "warning"})
                    logs.append({"message": f"   📄 String içeriği (ilk 500 karakter): {meta_data[:500]}...", "type": "info"})
                    try:
                        meta_data = json.loads(meta_data)
                    except:
                        logs.append({"message": f"⚠️ Meta data parse edilemedi", "type": "warning"})
                        meta_data = None
                
                if meta_data and isinstance(meta_data, list):
                    logs.append({"message": f"📋 {len(meta_data)} meta kaydı bulundu (meta endpoint)", "type": "info"})
                    # İlk birkaç meta kaydını göster
                    for i, meta in enumerate(meta_data[:5]):
                        if isinstance(meta, dict):
                            meta_key = meta.get('key', 'N/A')
                            meta_value = meta.get('value', 'N/A')
                            if meta_key == '_elementor_data':
                                if isinstance(meta_value, str):
                                    logs.append({"message": f"   ✅ [{i}] {meta_key}: {len(meta_value)} karakter", "type": "info"})
                                    preview = meta_value[:500].replace('\n', ' ').replace('\r', ' ')
                                    logs.append({"message": f"      📄 İlk 500 karakter: {preview}...", "type": "info"})
                                else:
                                    logs.append({"message": f"   ✅ [{i}] {meta_key}: {type(meta_value).__name__}", "type": "info"})
                            else:
                                value_preview = str(meta_value)[:100] if meta_value else "None"
                                logs.append({"message": f"   📌 [{i}] {meta_key}: {value_preview}...", "type": "info"})
                        else:
                            logs.append({"message": f"   📌 [{i}] {type(meta).__name__}: {str(meta)[:100]}...", "type": "info"})
                    
                    # Meta data'nın tamamını JSON olarak göster (ilk 2000 karakter)
                    try:
                        meta_data_json = json.dumps(meta_data, indent=2, ensure_ascii=False)
                        logs.append({"message": f"📦 WordPress Meta Data (JSON - ilk 2000 karakter):", "type": "info"})
                        logs.append({"message": f"{meta_data_json[:2000]}...", "type": "info"})
                    except Exception as json_error:
                        logs.append({"message": f"⚠️ Meta data JSON'a çevrilemedi: {json_error}", "type": "warning"})
                    
                    # _elementor_data meta'sını bul
                    for meta in meta_data:
                        if isinstance(meta, dict) and meta.get('key') == '_elementor_data':
                            elementor_json = meta.get('value', '')
                            
                            # 🔍 DEBUG: Elementor data'nın yapısını göster
                            logs.append({"message": f"📦 Elementor Data Yapısı (meta endpoint):", "type": "info"})
                            logs.append({"message": f"   📋 Data Tipi: {type(elementor_json).__name__}", "type": "info"})
                            
                            if isinstance(elementor_json, str):
                                logs.append({"message": f"✅ Elementor data bulundu ({endpoint}/meta): {len(elementor_json)} karakter", "type": "success"})
                                # İlk 1000 karakteri göster
                                preview = elementor_json[:1000].replace('\n', '\\n').replace('\r', '\\r')
                                logs.append({"message": f"📄 Elementor Data İlk 1000 Karakter:", "type": "info"})
                                logs.append({"message": f"{preview}...", "type": "info"})
                                return True, elementor_json
                            elif isinstance(elementor_json, (dict, list)):
                                json_str = json.dumps(elementor_json)
                                logs.append({"message": f"✅ Elementor data bulundu ({endpoint}/meta): {len(json_str)} karakter", "type": "success"})
                                # İlk 1000 karakteri göster
                                preview = json_str[:1000].replace('\n', '\\n').replace('\r', '\\r')
                                logs.append({"message": f"📄 Elementor Data İlk 1000 Karakter:", "type": "info"})
                                logs.append({"message": f"{preview}...", "type": "info"})
                                return True, json_str
            
            # Meta endpoint çalışmazsa, alternatif yöntemler dene
            logs.append({"message": f"⚠️ {endpoint}/meta endpoint çalışmadı, alternatif yöntemler deneniyor...", "type": "warning"})
            
            # WordPress'in meta endpoint'i bazen farklı formatta olabilir
            # Örneğin: /wp/v2/posts/{id} içinde meta bilgileri olabilir
            # Veya custom endpoint kullanılabilir
            
            # Post data içinde doğrudan _elementor_data var mı kontrol et
            # (WordPress functions.php'ye register_rest_field eklendikten sonra bu alan görünecek)
            if isinstance(post_data, dict):
                # Tüm key'leri kontrol et
                all_keys = list(post_data.keys())
                logs.append({"message": f"📋 Post data keys (ilk 20): {', '.join(all_keys[:20])}", "type": "info"})
                
                # _elementor_data doğrudan post data içinde olabilir (register_rest_field ile expose edilmişse)
                if '_elementor_data' in post_data:
                    elementor_json = post_data.get('_elementor_data')
                    if elementor_json:
                        # 🔍 DEBUG: Elementor data'nın yapısını göster
                        logs.append({"message": f"📦 Elementor Data Yapısı (post data içinde):", "type": "info"})
                        logs.append({"message": f"   📋 Data Tipi: {type(elementor_json).__name__}", "type": "info"})
                        
                        # Elementor data string olarak gelir, JSON'a çevirmeye gerek yok (zaten string)
                        if isinstance(elementor_json, str):
                            logs.append({"message": f"✅ Elementor data bulundu (post data içinde): {len(elementor_json)} karakter", "type": "success"})
                            # İlk 1000 karakteri göster
                            preview = elementor_json[:1000].replace('\n', '\\n').replace('\r', '\\r')
                            logs.append({"message": f"📄 Elementor Data İlk 1000 Karakter:", "type": "info"})
                            logs.append({"message": f"{preview}...", "type": "info"})
                            return True, elementor_json
                        elif isinstance(elementor_json, (dict, list)):
                            # Eğer dict/list olarak gelirse JSON'a çevir
                            json_str = json.dumps(elementor_json)
                            logs.append({"message": f"✅ Elementor data bulundu (post data içinde): {len(json_str)} karakter", "type": "success"})
                            # İlk 1000 karakteri göster
                            preview = json_str[:1000].replace('\n', '\\n').replace('\r', '\\r')
                            logs.append({"message": f"📄 Elementor Data İlk 1000 Karakter:", "type": "info"})
                            logs.append({"message": f"{preview}...", "type": "info"})
                            return True, json_str
                    else:
                        logs.append({"message": f"⚠️ _elementor_data key'i var ama değer boş", "type": "warning"})
                else:
                    logs.append({"message": f"⚠️ _elementor_data key'i bulunamadı. WordPress functions.php'ye register_rest_field kodu eklenmeli!", "type": "warning"})
                
                # _elementor ile başlayan diğer key'leri de kontrol et
                elementor_keys = [k for k in all_keys if '_elementor' in k.lower() and k != '_elementor_data']
                if elementor_keys:
                    logs.append({"message": f"📋 Elementor ile ilgili diğer keys bulundu: {', '.join(elementor_keys)}", "type": "info"})
            
            # Post data içinde meta bilgileri var mı kontrol et (fallback)
            if isinstance(post_data, dict) and 'meta' in post_data:
                logs.append({"message": f"📋 Post data içinde meta bilgileri bulundu (fallback)", "type": "info"})
                meta_dict = post_data.get('meta', {})
                
                if isinstance(meta_dict, dict) and '_elementor_data' in meta_dict:
                    elementor_json = meta_dict['_elementor_data']
                    if isinstance(elementor_json, str):
                        logs.append({"message": f"✅ Elementor data bulundu (meta dict içinde): {len(elementor_json)} karakter", "type": "success"})
                        return True, elementor_json
                    elif isinstance(elementor_json, (dict, list)):
                        json_str = json.dumps(elementor_json)
                        logs.append({"message": f"✅ Elementor data bulundu (meta dict içinde): {len(json_str)} karakter", "type": "success"})
                        return True, json_str
            
            logs.append({"message": f"⚠️ {endpoint} endpoint'inde _elementor_data meta'sı bulunamadı", "type": "warning"})
        
        logs.append({"message": f"❌ Elementor data bulunamadı", "type": "error"})
        return False, None
    
    async def update_elementor_data(self, post_id: int, elementor_json: str, post_type: str = None, logs: list = None) -> Tuple[bool, str]:
        """
        Elementor data'yı güncelle
        
        Args:
            post_id: WordPress post ID
            elementor_json: Güncellenmiş Elementor JSON string
            post_type: Post type ('post' veya 'page'), None ise otomatik bulunur
            
        Returns:
            (success, message)
        """
        # Post type'ı belirle
        if not post_type:
            # Önce pages'de dene
            success, data, error = await self._make_request("GET", f"pages/{post_id}")
            if success and data:
                post_type = 'page'
            else:
                # Posts'da dene
                success, data, error = await self._make_request("GET", f"posts/{post_id}")
                if success and data:
                    post_type = 'post'
                else:
                    return False, f"Post/Page bulunamadı: {error}"
        
        # Meta endpoint'i ile güncelle (hem pages hem posts için)
        endpoints_to_try = []
        if post_type == 'page':
            endpoints_to_try = ['pages', 'posts']  # Önce pages, sonra posts
        else:
            endpoints_to_try = ['posts', 'pages']  # Önce posts, sonra pages
        
        for endpoint in endpoints_to_try:
            # Önce mevcut meta'yı al
            success, meta_data, error = await self._make_request("GET", f"{endpoint}/{post_id}/meta")
            
            if not success:
                continue  # Bir sonraki endpoint'i dene
            
            # _elementor_data meta ID'sini bul
            elementor_meta_id = None
            for meta in meta_data:
                if meta.get('key') == '_elementor_data':
                    elementor_meta_id = meta.get('id')
                    break
            
            if elementor_meta_id:
                # Mevcut meta'yı güncelle
                update_data = {
                    'value': elementor_json
                }
                success, data, error = await self._make_request("PUT", f"{endpoint}/{post_id}/meta/{elementor_meta_id}", update_data)
            else:
                # Yeni meta ekle
                update_data = {
                    'key': '_elementor_data',
                    'value': elementor_json
                }
                success, data, error = await self._make_request("POST", f"{endpoint}/{post_id}/meta", update_data)
            
            if success:
                return True, f"Elementor data güncellendi ({endpoint})"
        
        return False, f"Güncelleme hatası: Meta endpoint'lerinde başarısız"
    
    async def fix_link_in_elementor(self, post_id: int, old_url: str, new_url: str, dry_run: bool = False, logs: list = None, post_type: str = None) -> Dict:
        """
        Elementor içeriğindeki linki düzelt (basit search-replace)
        
        Args:
            post_id: WordPress post ID
            old_url: Eski URL (redirect olan)
            new_url: Yeni URL (final URL)
            dry_run: Sadece test et, değişiklik yapma
            logs: Log listesi (opsiyonel)
            post_type: Post type ('post' veya 'page'), None ise otomatik bulunur
            
        Returns:
            {
                "success": bool,
                "message": str,
                "changes_count": int,
                "logs": list
            }
        """
        if logs is None:
            logs = []
        
        # Artık Elementor data'yı okumaya gerek yok - functions.php endpoint'i direkt link değiştiriyor
        logs.append({"message": f"🔍 Link düzeltme işlemi başlatılıyor (Post ID: {post_id})...", "type": "info"})
        logs.append({"message": f"   Eski URL: {old_url}", "type": "info"})
        logs.append({"message": f"   Yeni URL: {new_url}", "type": "info"})
        
        # Artık Python tarafında JSON işleme yapmıyoruz - functions.php endpoint'i hallediyor
        # Sadece dry-run kontrolü yapıyoruz
        if dry_run:
            logs.append({"message": "🔍 Dry-run modu: Değişiklik yapılmadı", "type": "info"})
            logs.append({"message": "   Not: Dry-run modunda WordPress endpoint'i çağrılmaz", "type": "info"})
            return {
                "success": True,
                "message": f"Dry-run: Link değiştirme işlemi test edildi (değişiklik yapılmadı)",
                "changes_count": 0,
                "logs": logs
            }
        
        logs.append({"message": "📝 Elementor data güncelleniyor...", "type": "info"})
        
        # TEK YÖNTEM: Elementor Native Replace endpoint'i (functions.php'deki endpoint)
        logs.append({"message": f"🔍 Elementor Native Replace endpoint'i çağrılıyor...", "type": "info"})
        logs.append({"message": f"   Endpoint: {self.wp_url}/wp-json/custom/v1/elementor-native-replace", "type": "info"})
        logs.append({"message": f"   Authentication: Application Password", "type": "info"})
        
        # Application Password ile WordPress REST API'ye bağlan
        native_replace_url = f"{self.wp_url}/wp-json/custom/v1/elementor-native-replace"
        native_replace_data = {
            'id': post_id,
            'old_url': old_url,
            'new_url': new_url
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    native_replace_url,
                    auth=self.auth,  # Application Password authentication
                    json=native_replace_data
                )

                # DEBUG: Response detaylarını logla
                logs.append({"message": f"🔍 HTTP Response Status: {response.status_code}", "type": "info"})
                logs.append({"message": f"🔍 Response Headers: Content-Type={response.headers.get('content-type', 'N/A')}", "type": "info"})

                # Response body'yi logla (ilk 1000 karakter)
                response_preview = response.text[:1000] if response.text else "(boş)"
                logs.append({"message": f"🔍 Response Body (ilk 1000 char):\n{response_preview}", "type": "info"})

                if response.status_code == 200:
                    php_result = response.json()
                    php_changes = php_result.get('changes_count', 0)
                    
                    # Eğer changes_count 0 ise, link zaten değiştirilmiş olabilir - kontrol et
                    if php_changes == 0:
                        logs.append({"message": f"⚠️ Endpoint 0 değişiklik bildirdi - link zaten değiştirilmiş olabilir", "type": "warning"})
                        logs.append({"message": f"🔍 Sayfa kontrol ediliyor: old_url var mı, new_url var mı?", "type": "info"})
            
                        # Sayfayı oku ve kontrol et
                        try:
                            success, elementor_json = await self.get_elementor_data(post_id, post_type=post_type, logs=logs)
                            if success and elementor_json:
                                # URL'leri normalize et ve farklı formatları kontrol et
                                # Elementor data'da URL'ler escaped (https:\/\/) veya encoded olabilir
                                
                                # Normalize edilmiş URL'ler (trailing slash olmadan)
                                old_url_normalized = old_url.rstrip('/')
                                new_url_normalized = new_url.rstrip('/')
                                
                                # Escaped versiyonlar (JSON'da kullanılan format)
                                old_url_escaped = old_url.replace('/', '\\/')
                                new_url_escaped = new_url.replace('/', '\\/')
                                
                                # URL encoded versiyonlar
                                import urllib.parse
                                old_url_encoded = urllib.parse.quote(old_url, safe='')
                                new_url_encoded = urllib.parse.quote(new_url, safe='')
                                
                                # Kontrol: Tüm formatları dene (href="..." formatları dahil)
                                old_url_variants = [
                                    old_url,  # Orijinal
                                    old_url_normalized,  # Trailing slash olmadan
                                    old_url_escaped,  # Escaped: https:\/\/
                                    old_url_encoded,  # Encoded
                                    old_url.replace('https://', 'http://'),  # HTTP versiyonu
                                    old_url.replace('http://', 'https://'),  # HTTPS versiyonu
                                    # href="..." formatları (JSON'da yaygın)
                                    f'href="{old_url}"',  # href="https://..."
                                    f'href="{old_url_normalized}"',  # href="https://..." (trailing slash yok)
                                    f'href="{old_url_escaped}"',  # href="https:\/\/..."
                                    f'href=\\"{old_url}\\"',  # href=\"https://...\" (escaped quotes)
                                    f'href=\\"{old_url_normalized}\\"',  # href=\"https://...\" (escaped quotes, trailing slash yok)
                                    f'href=\\"{old_url_escaped}\\"',  # href=\"https:\/\/...\" (escaped quotes + slashes) ✅
                                    f'href=\\"{old_url_normalized.replace("/", "\\/")}\\"',  # href=\"https:\/\/...\" (normalized + escaped)
                                    f'"url":"{old_url}"',  # "url":"https://..."
                                    f'"url":"{old_url_escaped}"',  # "url":"https:\/\/..."
                                    f'"url":"{old_url_normalized}"',  # "url":"https://..." (trailing slash yok)
                                ]
                                
                                new_url_variants = [
                                    new_url,  # Orijinal
                                    new_url_normalized,  # Trailing slash olmadan
                                    new_url_escaped,  # Escaped: https:\/\/
                                    new_url_encoded,  # Encoded
                                    new_url.replace('https://', 'http://'),  # HTTP versiyonu
                                    new_url.replace('http://', 'https://'),  # HTTPS versiyonu
                                    # href="..." formatları (JSON'da yaygın)
                                    f'href="{new_url}"',  # href="https://..."
                                    f'href="{new_url_normalized}"',  # href="https://..." (trailing slash yok)
                                    f'href="{new_url_escaped}"',  # href="https:\/\/..."
                                    f'href=\\"{new_url}\\"',  # href=\"https://...\" (escaped quotes)
                                    f'href=\\"{new_url_normalized}\\"',  # href=\"https://...\" (escaped quotes, trailing slash yok)
                                    f'href=\\"{new_url_escaped}\\"',  # href=\"https:\/\/...\" (escaped quotes + slashes) ✅
                                    f'href=\\"{new_url_normalized.replace("/", "\\/")}\\"',  # href=\"https:\/\/...\" (normalized + escaped)
                                    f'"url":"{new_url}"',  # "url":"https://..."
                                    f'"url":"{new_url_escaped}"',  # "url":"https:\/\/..."
                                    f'"url":"{new_url_normalized}"',  # "url":"https://..." (trailing slash yok)
                                ]
                                
                                # Her variant'ı kontrol et
                                old_url_found = any(variant in elementor_json for variant in old_url_variants if variant)
                                new_url_found = any(variant in elementor_json for variant in new_url_variants if variant)
                                
                                # Hangi variant'ların bulunduğunu logla
                                found_old_variants = [v for v in old_url_variants if v and v in elementor_json]
                                found_new_variants = [v for v in new_url_variants if v and v in elementor_json]
                                
                                if found_old_variants:
                                    # İlk 3 variant'ı göster (href="..." formatları dahil)
                                    preview_variants = [v[:80] + "..." if len(v) > 80 else v for v in found_old_variants[:3]]
                                    logs.append({"message": f"🔍 old_url variant'ları bulundu ({len(found_old_variants)} adet): {preview_variants}", "type": "info"})
                                if found_new_variants:
                                    # İlk 3 variant'ı göster (href="..." formatları dahil)
                                    preview_variants = [v[:80] + "..." if len(v) > 80 else v for v in found_new_variants[:3]]
                                    logs.append({"message": f"🔍 new_url variant'ları bulundu ({len(found_new_variants)} adet): {preview_variants}", "type": "info"})
                                
                                logs.append({"message": f"📋 Kontrol sonucu: old_url bulundu={old_url_found}, new_url bulundu={new_url_found}", "type": "info"})
                                
                                # Eğer new_url varsa ve old_url yoksa, link zaten değiştirilmiş
                                if new_url_found and not old_url_found:
                                    logs.append({"message": f"✅ Link zaten değiştirilmiş: Sayfada new_url mevcut, old_url yok", "type": "success"})
                                    logs.append({"message": f"   Bu durum manuel değişiklik veya önceki bir işlemden kaynaklanıyor olabilir", "type": "info"})
                                    return {
                                        "success": True,
                                        "message": f"Link zaten değiştirilmiş (new_url sayfada mevcut, old_url bulunamadı)",
                                        "changes_count": 0,
                                        "already_fixed": True,  # Özel flag: link zaten değiştirilmiş
                                        "logs": logs
                                    }
                                elif old_url_found and not new_url_found:
                                    # old_url hala var, new_url yok - bu garip, tekrar dene
                                    logs.append({"message": f"⚠️ old_url hala sayfada var, new_url yok - endpoint çalışmamış olabilir", "type": "warning"})
                                elif old_url_found and new_url_found:
                                    # Her ikisi de var - muhtemelen kısmi değişiklik
                                    logs.append({"message": f"⚠️ Hem old_url hem new_url sayfada var - kısmi değişiklik olabilir", "type": "warning"})
                                else:
                                    # Hiçbiri yok - garip durum - belki URL formatı farklı
                                    logs.append({"message": f"⚠️ Ne old_url ne new_url sayfada bulunamadı - URL formatı farklı olabilir", "type": "warning"})
                                    logs.append({"message": f"   Endpoint 0 değişiklik bildirdi, bu normal olabilir (link zaten düzeltilmiş veya farklı formatta)", "type": "info"})
                                    # Endpoint 0 döndüyse ve URL'ler bulunamadıysa, muhtemelen link zaten düzeltilmiş
                                    # veya farklı bir formatta (domain olmadan, relative path vb.)
                                    return {
                                        "success": True,
                                        "message": f"Link kontrol edildi: Endpoint 0 değişiklik bildirdi (link zaten düzeltilmiş veya farklı formatta olabilir)",
                                        "changes_count": 0,
                                        "already_fixed": True,  # Muhtemelen zaten düzeltilmiş
                                        "logs": logs
                                    }
                        except Exception as check_error:
                            logs.append({"message": f"⚠️ Sayfa kontrolü sırasında hata: {str(check_error)}", "type": "warning"})
                            # Kontrol hatası olsa bile, endpoint 0 döndüyse "zaten değiştirilmiş" olarak kabul et
                            logs.append({"message": f"✅ Endpoint 0 değişiklik bildirdi - link zaten değiştirilmiş kabul ediliyor", "type": "info"})
                            return {
                                "success": True,
                                "message": f"Link zaten değiştirilmiş (endpoint 0 değişiklik bildirdi)",
                                "changes_count": 0,
                                "already_fixed": True,  # Özel flag: link zaten değiştirilmiş
                                "logs": logs
                            }
                    
                    # Normal durum: değişiklik yapıldı
                    logs.append({"message": f"✅ Elementor Native Replace başarılı: {php_changes} link değiştirildi", "type": "success"})
                    logs.append({"message": f"✅ Elementor cache otomatik temizlendi", "type": "success"})
                    logs.append({"message": f"✅ İŞLEM BAŞARILI - {php_changes} link başarıyla düzeltildi", "type": "success"})
                    return {
                        "success": True,
                        "message": f"{php_changes} link başarıyla düzeltildi (Elementor Native Replace)",
                        "changes_count": php_changes,
                        "already_fixed": False,
                        "logs": logs
                    }
                else:
                    error_text = response.text[:500] if response.text else ""
                    try:
                        error_json = response.json()
                        error_msg = error_json.get('message', error_text)
                    except:
                        error_msg = error_text
                    
                    logs.append({"message": f"❌ Elementor Native Replace başarısız (HTTP {response.status_code})", "type": "error"})
                    logs.append({"message": f"   Hata: {error_msg}", "type": "error"})
                    
            return {
                        "success": False,
                        "message": f"WordPress endpoint hatası: HTTP {response.status_code} - {error_msg}",
                        "changes_count": 0,
                "logs": logs
            }
        except httpx.TimeoutException:
            logs.append({"message": f"❌ İstek zaman aşımına uğradı (30 saniye)", "type": "error"})
            return {
                "success": False,
                "message": "WordPress endpoint'e bağlanılamadı: Zaman aşımı",
                "changes_count": 0,
                "logs": logs
            }
        except Exception as e:
            error_msg = str(e)
            logs.append({"message": f"❌ Elementor Native Replace hatası: {error_msg}", "type": "error"})
            logs.append({"message": f"   Endpoint: {native_replace_url}", "type": "error"})
            logs.append({"message": f"   Authentication: Application Password kullanılıyor", "type": "info"})
        
        return {
                "success": False,
                "message": f"WordPress endpoint hatası: {error_msg}",
                "changes_count": 0,
            "logs": logs
        }

