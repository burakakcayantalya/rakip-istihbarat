# ============================================
# WordPress REST API - Redirect Link Düzeltme
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
                # meta_data bir liste mi dict mi kontrol et
                if isinstance(meta_data, str):
                    logs.append({"message": f"⚠️ Meta data string formatında, parse ediliyor...", "type": "warning"})
                    try:
                        meta_data = json.loads(meta_data)
                    except:
                        logs.append({"message": f"⚠️ Meta data parse edilemedi", "type": "warning"})
                        meta_data = None
                
                if meta_data and isinstance(meta_data, list):
                    logs.append({"message": f"📋 {len(meta_data)} meta kaydı bulundu (meta endpoint)", "type": "info"})
                    
                    # _elementor_data meta'sını bul
                    for meta in meta_data:
                        if isinstance(meta, dict) and meta.get('key') == '_elementor_data':
                            elementor_json = meta.get('value', '')
                            if isinstance(elementor_json, str):
                                logs.append({"message": f"✅ Elementor data bulundu ({endpoint}/meta): {len(elementor_json)} karakter", "type": "success"})
                                return True, elementor_json
                            elif isinstance(elementor_json, (dict, list)):
                                json_str = json.dumps(elementor_json)
                                logs.append({"message": f"✅ Elementor data bulundu ({endpoint}/meta): {len(json_str)} karakter", "type": "success"})
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
                        # Elementor data string olarak gelir, JSON'a çevirmeye gerek yok (zaten string)
                        if isinstance(elementor_json, str):
                            logs.append({"message": f"✅ Elementor data bulundu (post data içinde): {len(elementor_json)} karakter", "type": "success"})
                            return True, elementor_json
                        elif isinstance(elementor_json, (dict, list)):
                            # Eğer dict/list olarak gelirse JSON'a çevir
                            json_str = json.dumps(elementor_json)
                            logs.append({"message": f"✅ Elementor data bulundu (post data içinde): {len(json_str)} karakter", "type": "success"})
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
        
        logs.append({"message": f"Post ID {post_id} için Elementor data alınıyor...", "type": "info"})
        
        # Elementor data'yı al
        success, elementor_json = await self.get_elementor_data(post_id, post_type=post_type, logs=logs)
        if not success or not elementor_json:
            logs.append({"message": "❌ Elementor data alınamadı", "type": "error"})
            return {
                "success": False,
                "message": "Elementor data alınamadı",
                "changes_count": 0,
                "logs": logs
            }
        
        logs.append({"message": "✅ Elementor data başarıyla alındı", "type": "success"})
        
        # Orijinal JSON'u cache'te tut (karşılaştırma için)
        original_json = elementor_json
        logs.append({"message": f"💾 Orijinal JSON cache'lendi ({len(original_json)} karakter)", "type": "info"})
        
        # URL'leri normalize et (farklı formatları yakala)
        from urllib.parse import urlparse
        parsed_old = urlparse(old_url)
        old_path = parsed_old.path
        old_domain = f"{parsed_old.scheme}://{parsed_old.netloc}" if parsed_old.netloc else ""
        
        # Daha kapsamlı URL varyasyonları (trailing slash hem var hem yok)
        old_url_variants = []
        
        # Tam URL varyasyonları
        old_url_variants.append(old_url)  # Orijinal
        if old_url.endswith('/'):
            old_url_variants.append(old_url.rstrip('/'))  # Trailing slash'i kaldır
        else:
            old_url_variants.append(old_url + '/')  # Trailing slash ekle
        
        # Path varyasyonları (hem / ile hem / olmadan)
        if old_path:
            old_url_variants.append(old_path)  # Orijinal path
            if old_path.endswith('/'):
                old_url_variants.append(old_path.rstrip('/'))  # Trailing slash'i kaldır
            else:
                old_url_variants.append(old_path + '/')  # Trailing slash ekle
        
        # Domain varsa domain'li varyasyonları da ekle
        if old_domain:
            if old_path:
                old_url_variants.append(f"{old_domain}{old_path}")  # Domain + path
                if old_path.endswith('/'):
                    old_url_variants.append(f"{old_domain}{old_path.rstrip('/')}")  # Domain + path (slash yok)
                else:
                    old_url_variants.append(f"{old_domain}{old_path}/")  # Domain + path (slash var)
        
        # JSON escape edilmiş varyasyonları ekle (\/ ve \" için)
        escaped_variants = []
        for variant in old_url_variants[:]:  # Kopyasını al
            if variant:
                # Escape edilmiş versiyonları ekle
                escaped_variant = variant.replace('/', '\\/').replace('"', '\\"')
                escaped_variants.append(escaped_variant)
                # Hem escape edilmiş hem normal olanı ekle
                old_url_variants.append(escaped_variant)
        
        # Duplicate'leri kaldır (order'i koruyarak)
        seen = set()
        old_url_variants = [x for x in old_url_variants if x and (x not in seen, seen.add(x))[0]]
        
        # Eski URL'yi logla
        logs.append({"message": f"🔍 Aranacak URL: {old_url}", "type": "info"})
        logs.append({"message": f"📋 Yeni URL: {new_url}", "type": "info"})
        logs.append({"message": f"📋 {len(old_url_variants)} farklı varyasyon deneniyor...", "type": "info"})
        
        # Regex ile string içinde değiştir
        changes_count = 0
        new_json = elementor_json
        
        # Önce basit string search ile kontrol et ve bulunan varyasyonları kaydet
        found_variants = []
        for variant in old_url_variants:
            if variant and variant in elementor_json:
                found_variants.append(variant)
                logs.append({"message": f"  ✅ '{variant}' bulundu!", "type": "success"})
        
        if not found_variants:
            logs.append({"message": f"⚠️ Hiçbir URL varyasyonu bulunamadı!", "type": "warning"})
            # Elementor JSON'un bir kısmını göster (debug için)
            json_preview = elementor_json[:1000] if len(elementor_json) > 1000 else elementor_json
            logs.append({"message": f"📋 Elementor JSON önizleme (ilk 1000 karakter): {json_preview[:500]}...", "type": "info"})
        else:
            logs.append({"message": f"📋 {len(found_variants)} varyasyon bulundu, değiştirme işlemi başlatılıyor...", "type": "info"})
            
            # DEBUG: URL'in geçtiği yerleri bul ve göster
            logs.append({"message": f"🔍 DEBUG: URL'in geçtiği yerler aranıyor...", "type": "info"})
            for variant in found_variants:
                # URL'in geçtiği satırları bul (context ile)
                import re as re_module
                pattern = re_module.escape(variant)
                matches = list(re_module.finditer(pattern, elementor_json))
                if matches:
                    logs.append({"message": f"📋 '{variant}' için {len(matches)} eşleşme bulundu:", "type": "info"})
                    # İlk 5 eşleşmeyi göster (öncesi ve sonrası ile)
                    for i, match in enumerate(matches[:5], 1):
                        start = max(0, match.start() - 200)
                        end = min(len(elementor_json), match.end() + 200)
                        context = elementor_json[start:end]
                        # JSON'u daha okunabilir hale getir
                        try:
                            # Eğer JSON parse edilebiliyorsa formatla
                            import json as json_module
                            # Context'i JSON olarak parse etmeye çalış
                            # Ama önce tam bir JSON objesi olmayabilir, o yüzden sadece göster
                            logs.append({"message": f"  {i}. Konum: {match.start()}-{match.end()}", "type": "info"})
                            logs.append({"message": f"     Context: ...{context}...", "type": "info"})
                        except:
                            logs.append({"message": f"  {i}. Konum: {match.start()}-{match.end()}", "type": "info"})
                            logs.append({"message": f"     Context: ...{context}...", "type": "info"})
                    
                    if len(matches) > 5:
                        logs.append({"message": f"  ... ve {len(matches) - 5} eşleşme daha", "type": "info"})
            
            # DEBUG: JSON'u parse et ve URL içeren field'ları bul
            try:
                import json as json_module
                elementor_data = json_module.loads(elementor_json)
                logs.append({"message": f"🔍 DEBUG: JSON parse edildi, URL içeren field'lar aranıyor...", "type": "info"})
                
                def find_url_fields(data, path="", depth=0, max_depth=10):
                    """Recursive olarak URL içeren field'ları bul"""
                    url_fields = []
                    if depth > max_depth:
                        return url_fields
                    
                    if isinstance(data, dict):
                        for key, value in data.items():
                            current_path = f"{path}.{key}" if path else key
                            if isinstance(value, (dict, list)):
                                url_fields.extend(find_url_fields(value, current_path, depth + 1, max_depth))
                            elif isinstance(value, str):
                                # URL içeren string'leri kontrol et
                                for variant in found_variants:
                                    if variant in value:
                                        url_fields.append({
                                            'path': current_path,
                                            'key': key,
                                            'value': value[:200] + '...' if len(value) > 200 else value,
                                            'matched_variant': variant
                                        })
                                        break
                    elif isinstance(data, list):
                        for i, item in enumerate(data):
                            current_path = f"{path}[{i}]" if path else f"[{i}]"
                            if isinstance(item, (dict, list)):
                                url_fields.extend(find_url_fields(item, current_path, depth + 1, max_depth))
                            elif isinstance(item, str):
                                for variant in found_variants:
                                    if variant in item:
                                        url_fields.append({
                                            'path': current_path,
                                            'key': f'[{i}]',
                                            'value': item[:200] + '...' if len(item) > 200 else item,
                                            'matched_variant': variant
                                        })
                                        break
                    return url_fields
                
                url_fields = find_url_fields(elementor_data)
                if url_fields:
                    logs.append({"message": f"📋 URL içeren {len(url_fields)} field bulundu:", "type": "info"})
                    for i, field in enumerate(url_fields[:10], 1):  # İlk 10'unu göster
                        logs.append({"message": f"  {i}. Path: {field['path']}", "type": "info"})
                        logs.append({"message": f"     Key: {field['key']}", "type": "info"})
                        logs.append({"message": f"     Value: {field['value']}", "type": "info"})
                        logs.append({"message": f"     Matched: {field['matched_variant']}", "type": "info"})
                    if len(url_fields) > 10:
                        logs.append({"message": f"  ... ve {len(url_fields) - 10} field daha", "type": "info"})
                else:
                    logs.append({"message": f"⚠️ JSON parse edildi ama URL içeren field bulunamadı", "type": "warning"})
            except Exception as e:
                logs.append({"message": f"⚠️ JSON parse hatası: {str(e)}", "type": "warning"})
        
        for old_variant in old_url_variants:
            if not old_variant:  # Boş varyasyonları atla
                continue
                
            # Escape özel karakterler
            escaped_old = re.escape(old_variant)
            
            # Escape edilmiş varyasyonu hazırla
            escaped_variant = old_variant.replace('/', '\\/').replace('"', '\\"')
            
            # Pattern 1: <a href="..."> formatında (hem normal hem escape edilmiş) - ÖNCE BUNU DENE
            # Tam <a> tag'ini yakala ki tag bozulmasın
            pattern1_escaped = rf'(<a\s+[^>]*href=\\")([^"]*{re.escape(escaped_variant)}[^"]*)(\\"[^>]*>)'
            pattern1_normal = rf'(<a\s+[^>]*href=["\'])([^"\']*{escaped_old}[^"\']*)(["\'][^>]*>)'
            
            # Pattern 2: href="..." veya href='...' içinde eski URL (fallback - sadece href)
            pattern2_escaped = rf'(href=\\")([^"]*{re.escape(escaped_variant)}[^"]*)(\\")'
            pattern2_normal = rf'(href=["\'])([^"\']*{escaped_old}[^"\']*)(["\'])'
            
            # Pattern 3: "url": "..." içinde eski URL (hem normal hem escape edilmiş)
            pattern3_escaped = rf'("url"\\s*:\\s*\\")([^"]*{re.escape(escaped_variant)}[^"]*)(\\")'
            pattern3_normal = rf'("url"\s*:\s*["\'])([^"\']*{escaped_old}[^"\']*)(["\'])'
            
            # Pattern'leri öncelik sırasına göre dene (önce <a> tag'i, sonra diğerleri)
            patterns = [
                (pattern1_escaped, '<a> tag (escaped)'),
                (pattern1_normal, '<a> tag (normal)'),
                (pattern2_escaped, 'href attribute (escaped)'),
                (pattern2_normal, 'href attribute (normal)'),
                (pattern3_escaped, 'url field (escaped)'),
                (pattern3_normal, 'url field (normal)'),
            ]
            
            for pattern, pattern_name in patterns:
                matches = list(re.finditer(pattern, new_json))
                if matches:
                    logs.append({"message": f"  ✅ {pattern_name} içinde '{old_variant}' bulundu: {len(matches)} eşleşme", "type": "success"})
            
            def replace_func(match):
                nonlocal changes_count
                # Grupları al
                groups = match.groups()
                if len(groups) >= 3:
                    prefix = groups[0]
                    url_part = groups[1]
                    suffix = groups[2]
                    
                    # CSS url() fonksiyonu içinde mi kontrol et - EĞER ÖYLEYSE DEĞİŞTİRME
                    # url() fonksiyonu genellikle style attribute'unda veya CSS içinde olur
                    full_match = match.group(0)
                    if 'url(' in full_match.lower() or 'background' in full_match.lower() or 'style' in full_match.lower():
                        # CSS içinde olabilir, atla
                        logs.append({"message": f"  ⚠️ CSS url() fonksiyonu tespit edildi, atlandı", "type": "warning"})
                        return match.group(0)  # Değiştirme yapma
                    
                    # Escape edilmiş format mı kontrol et
                    is_escaped = '\\/' in url_part or '\\"' in prefix or '\\"' in suffix
                    
                    if is_escaped:
                        # Escape edilmiş formatı unescape et
                        unescaped_url_part = url_part.replace('\\/', '/').replace('\\"', '"')
                        unescaped_variant = old_variant.replace('\\/', '/').replace('\\"', '"')
                        unescaped_new_url = new_url.replace('\\/', '/').replace('\\"', '"')
                        
                        # Replace yap
                        unescaped_new_url_part = unescaped_url_part.replace(unescaped_variant, unescaped_new_url)
                        
                        # Tekrar escape et
                        new_url_part = unescaped_new_url_part.replace('/', '\\/').replace('"', '\\"')
                    else:
                        # Normal format
                        new_url_part = url_part.replace(old_variant, new_url)
                    
                    if new_url_part != url_part:  # Sadece gerçekten değiştiyse say
                        changes_count += 1
                        # Tam HTML tag'ini göster
                        old_full_tag = f"{prefix}{url_part}{suffix}"
                        new_full_tag = f"{prefix}{new_url_part}{suffix}"
                        logs.append({"message": f"  🔄 Değiştiriliyor:", "type": "info"})
                        logs.append({"message": f"     ESKİ: {old_full_tag}", "type": "info"})
                        logs.append({"message": f"     YENİ: {new_full_tag}", "type": "info"})
                    return f"{prefix}{new_url_part}{suffix}"
                else:
                    # Genel replace - CSS kontrolü yap
                    matched_text = match.group(0)
                    if 'url(' in matched_text.lower() or 'background' in matched_text.lower() or 'style' in matched_text.lower():
                        logs.append({"message": f"  ⚠️ CSS içeriği tespit edildi, atlandı", "type": "warning"})
                        return matched_text  # Değiştirme yapma
                    
                    new_text = matched_text.replace(old_variant, new_url)
                    if new_text != matched_text:
                        changes_count += 1
                        logs.append({"message": f"  🔄 Değiştiriliyor:", "type": "info"})
                        logs.append({"message": f"     ESKİ: {matched_text}", "type": "info"})
                        logs.append({"message": f"     YENİ: {new_text}", "type": "info"})
                    return new_text
            
            # Önce spesifik pattern'leri dene
            for pattern, pattern_name in patterns:
                new_json = re.sub(pattern, replace_func, new_json)
            
            # Son çare: Genel string replace (sadece URL benzeri görünen yerlerde)
            # Bu daha riskli, o yüzden sadece href, url gibi alanlarda yap
            url_like_pattern = rf'(href|url|link|src)\s*[:=]\s*["\']?([^"\'\s]*{escaped_old}[^"\'\s]*)["\']?'
            def url_replace_func(m):
                full_match = m.group(0)
                if old_variant in full_match:
                    new_match = full_match.replace(old_variant, new_url)
                    if new_match != full_match:
                        nonlocal changes_count
                        changes_count += 1
                        logs.append({"message": f"  🔄 Genel URL değiştiriliyor:", "type": "info"})
                        logs.append({"message": f"     ESKİ: {full_match}", "type": "info"})
                        logs.append({"message": f"     YENİ: {new_match}", "type": "info"})
                    return new_match
                return full_match
            new_json = re.sub(url_like_pattern, url_replace_func, new_json)
        
        # Eğer regex ile bulunamadıysa ama string search'te bulunduysa, güvenli string replace yap
        if changes_count == 0 and found_variants:
            logs.append({"message": f"⚠️ Regex pattern'ler çalışmadı, güvenli string replace deneniyor...", "type": "warning"})
            for variant in found_variants:
                if variant in new_json:
                    # Sadece href, url, link gibi field'larda değiştir (CSS'i bozmamak için)
                    # Pattern: "href": "...", "url": "...", "link": "..." gibi JSON field'larında
                    safe_patterns = [
                        rf'("href"\s*:\s*["\'])([^"\']*{re.escape(variant)}[^"\']*)(["\'])',
                        rf'("url"\s*:\s*["\'])([^"\']*{re.escape(variant)}[^"\']*)(["\'])',
                        rf'("link"\s*:\s*["\'])([^"\']*{re.escape(variant)}[^"\']*)(["\'])',
                        rf'("src"\s*:\s*["\'])([^"\']*{re.escape(variant)}[^"\']*)(["\'])',
                        rf'(href=["\'])([^"\']*{re.escape(variant)}[^"\']*)(["\'])',  # HTML href
                    ]
                    
                    for pattern in safe_patterns:
                        def safe_replace_func(match):
                            nonlocal changes_count
                            groups = match.groups()
                            if len(groups) >= 3:
                                prefix = groups[0]
                                url_part = groups[1]
                                suffix = groups[2]
                                
                                # CSS field'larını kontrol et - CSS'i bozmamak için
                                field_name = prefix.split(':')[0].strip('"').strip('\\"')
                                css_related_fields = ['css', 'style', 'background', 'background-image', 'backgroundImage', 'custom_css', 'customCSS', 'custom_css_pro', 'customCSSPro']
                                if any(css_field in field_name.lower() for css_field in css_related_fields):
                                    logs.append({"message": f"  ⚠️ CSS field atlandı: {field_name}", "type": "warning"})
                                    return match.group(0)  # Değiştirme yapma
                                
                                # Sadece href, url, link, src gibi link field'larında değiştir
                                link_fields = ['href', 'url', 'link', 'src']
                                if not any(link_field in field_name.lower() for link_field in link_fields):
                                    # Eğer field name yoksa veya link field değilse, prefix'e bak
                                    if not any(link_field in prefix.lower() for link_field in link_fields):
                                        logs.append({"message": f"  ⚠️ Link field değil, atlandı: {field_name or prefix[:50]}", "type": "warning"})
                                        return match.group(0)  # Değiştirme yapma
                                
                                # Eğer escape edilmiş formattaysa, önce unescape et, sonra replace yap, sonra tekrar escape et
                                is_escaped = '\\/' in url_part or '\\"' in prefix or '\\"' in suffix
                                if is_escaped:
                                    # Escape edilmiş formatı unescape et
                                    unescaped_url_part = url_part.replace('\\/', '/').replace('\\"', '"')
                                    unescaped_variant = variant.replace('\\/', '/').replace('\\"', '"')
                                    unescaped_new_url = new_url.replace('\\/', '/').replace('\\"', '"')
                                    
                                    # Replace yap
                                    unescaped_new_url_part = unescaped_url_part.replace(unescaped_variant, unescaped_new_url)
                                    
                                    # Tekrar escape et
                                    new_url_part = unescaped_new_url_part.replace('/', '\\/').replace('"', '\\"')
                                else:
                                    # Normal format
                                    new_url_part = url_part.replace(variant, new_url)
                                
                                if new_url_part != url_part:
                                    changes_count += 1
                                    # Tam HTML tag'ini göster
                                    old_full_tag = f"{prefix}{url_part}{suffix}"
                                    new_full_tag = f"{prefix}{new_url_part}{suffix}"
                                    logs.append({"message": f"  🔄 Güvenli replace:", "type": "info"})
                                    logs.append({"message": f"     ESKİ: {old_full_tag}", "type": "info"})
                                    logs.append({"message": f"     YENİ: {new_full_tag}", "type": "info"})
                                return f"{prefix}{new_url_part}{suffix}"
                            return match.group(0)
                        
                        matches_before = len(list(re.finditer(pattern, new_json)))
                        new_json = re.sub(pattern, safe_replace_func, new_json)
                        matches_after = len(list(re.finditer(pattern, new_json)))
                        
                        if matches_before > matches_after:
                            logs.append({"message": f"  ✅ Güvenli pattern ile {matches_before - matches_after} değişiklik yapıldı", "type": "success"})
                    
                    # Eğer hala değişiklik yapılmadıysa, sadece JSON field'larında dene
                    if changes_count == 0:
                        logs.append({"message": f"⚠️ Güvenli pattern'ler çalışmadı, JSON field'larında arama yapılıyor...", "type": "warning"})
                        # JSON field pattern: "field_name": "value" formatında
                        json_field_pattern = rf'("[^"]+"\s*:\s*["\'])([^"\']*{re.escape(variant)}[^"\']*)(["\'])'
                        def json_field_replace_func(match):
                            nonlocal changes_count
                            groups = match.groups()
                            if len(groups) >= 3:
                                prefix = groups[0]
                                url_part = groups[1]
                                suffix = groups[2]
                                
                                # CSS, style, background gibi field'larda değiştirme yapma
                                field_name = prefix.split(':')[0].strip('"')
                                css_related_fields = ['css', 'style', 'background', 'background-image', 'backgroundImage', 'custom_css']
                                if any(css_field in field_name.lower() for css_field in css_related_fields):
                                    logs.append({"message": f"  ⚠️ CSS field atlandı: {field_name}", "type": "warning"})
                                    return match.group(0)  # Değiştirme yapma
                                
                                new_url_part = url_part.replace(variant, new_url)
                                if new_url_part != url_part:
                                    changes_count += 1
                                    # Tam field değerini göster
                                    old_full_value = f"{prefix}{url_part}{suffix}"
                                    new_full_value = f"{prefix}{new_url_part}{suffix}"
                                    logs.append({"message": f"  🔄 JSON field replace ({field_name}):", "type": "info"})
                                    logs.append({"message": f"     ESKİ: {old_full_value}", "type": "info"})
                                    logs.append({"message": f"     YENİ: {new_full_value}", "type": "info"})
                                return f"{prefix}{new_url_part}{suffix}"
                            return match.group(0)
                        
                        new_json = re.sub(json_field_pattern, json_field_replace_func, new_json)
        
        if changes_count == 0:
            logs.append({"message": f"⚠️ Link bulunamadı. Denenen varyasyonlar:", "type": "warning"})
            for i, variant in enumerate(old_url_variants[:10], 1):
                logs.append({"message": f"  {i}. {variant}", "type": "info"})
            
            return {
                "success": False,
                "message": f"Link bulunamadı. {len(old_url_variants)} farklı varyasyon denenmiş ancak eşleşme bulunamadı.",
                "changes_count": 0,
                "logs": logs
            }
        
        logs.append({"message": f"✅ {changes_count} adet link bulundu", "type": "success"})
        
        # JSON karşılaştırması yap - sadece URL değişikliklerini kontrol et
        logs.append({"message": "🔍 JSON karşılaştırması yapılıyor...", "type": "info"})
        
        # Orijinal ve yeni JSON'u parse et
        try:
            import json as json_module
            original_data = json_module.loads(original_json)
            new_data = json_module.loads(new_json)
            
            # Recursive olarak farkları bul
            def find_differences(old_obj, new_obj, path="", differences=None):
                if differences is None:
                    differences = []
                
                if isinstance(old_obj, dict) and isinstance(new_obj, dict):
                    all_keys = set(old_obj.keys()) | set(new_obj.keys())
                    for key in all_keys:
                        current_path = f"{path}.{key}" if path else key
                        if key not in old_obj:
                            differences.append({
                                'path': current_path,
                                'type': 'added',
                                'old': None,
                                'new': new_obj[key]
                            })
                        elif key not in new_obj:
                            differences.append({
                                'path': current_path,
                                'type': 'removed',
                                'old': old_obj[key],
                                'new': None
                            })
                        else:
                            find_differences(old_obj[key], new_obj[key], current_path, differences)
                elif isinstance(old_obj, list) and isinstance(new_obj, list):
                    max_len = max(len(old_obj), len(new_obj))
                    for i in range(max_len):
                        current_path = f"{path}[{i}]" if path else f"[{i}]"
                        if i >= len(old_obj):
                            differences.append({
                                'path': current_path,
                                'type': 'added',
                                'old': None,
                                'new': new_obj[i]
                            })
                        elif i >= len(new_obj):
                            differences.append({
                                'path': current_path,
                                'type': 'removed',
                                'old': old_obj[i],
                                'new': None
                            })
                        else:
                            find_differences(old_obj[i], new_obj[i], current_path, differences)
                else:
                    # Primitive değerler
                    if old_obj != new_obj:
                        # Sadece URL değişikliklerini kontrol et
                        old_str = str(old_obj)
                        new_str = str(new_obj)
                        
                        # Eğer eski URL yeni URL'e dönüştüyse, bu beklenen bir değişiklik
                        if old_url in old_str and new_url in new_str:
                            differences.append({
                                'path': path,
                                'type': 'url_change',
                                'old': old_str,
                                'new': new_str
                            })
                        else:
                            # Beklenmeyen değişiklik!
                            differences.append({
                                'path': path,
                                'type': 'unexpected_change',
                                'old': old_str,
                                'new': new_str
                            })
                
                return differences
            
            differences = find_differences(original_data, new_data)
            
            # Farkları analiz et
            url_changes = [d for d in differences if d['type'] == 'url_change']
            unexpected_changes = [d for d in differences if d['type'] == 'unexpected_change']
            
            logs.append({"message": f"📋 Toplam {len(differences)} değişiklik bulundu", "type": "info"})
            logs.append({"message": f"✅ {len(url_changes)} URL değişikliği (beklenen)", "type": "success"})
            
            if unexpected_changes:
                logs.append({"message": f"⚠️ {len(unexpected_changes)} beklenmeyen değişiklik bulundu!", "type": "warning"})
                for i, diff in enumerate(unexpected_changes[:5], 1):
                    logs.append({"message": f"  {i}. Path: {diff['path']}", "type": "warning"})
                    logs.append({"message": f"     ESKİ: {str(diff['old'])[:200]}", "type": "warning"})
                    logs.append({"message": f"     YENİ: {str(diff['new'])[:200]}", "type": "warning"})
                
                # Beklenmeyen değişiklikler varsa, sadece URL değişikliklerini uygula
                logs.append({"message": "⚠️ Beklenmeyen değişiklikler tespit edildi, sadece URL değişiklikleri uygulanacak", "type": "warning"})
                
                # Orijinal JSON'a geri dön ve sadece URL'leri değiştir
                new_json = original_json
                for diff in url_changes:
                    # Sadece URL değişikliklerini uygula
                    old_value = diff['old']
                    new_value = diff['new']
                    new_json = new_json.replace(old_value, new_value)
                
                logs.append({"message": "✅ Sadece URL değişiklikleri uygulandı", "type": "success"})
            else:
                logs.append({"message": "✅ Tüm değişiklikler beklenen URL değişiklikleri", "type": "success"})
                
        except Exception as e:
            logs.append({"message": f"⚠️ JSON karşılaştırması yapılamadı: {str(e)}", "type": "warning"})
            logs.append({"message": "⚠️ Değişiklikler uygulanacak ama kontrol edilemeyecek", "type": "warning"})
        
        if dry_run:
            logs.append({"message": "🔍 Dry-run modu: Değişiklik yapılmadı", "type": "info"})
            return {
                "success": True,
                "message": f"Dry-run: {changes_count} link bulundu (değişiklik yapılmadı)",
                "changes_count": changes_count,
                "logs": logs
            }
        
        logs.append({"message": "📝 Elementor data güncelleniyor...", "type": "info"})
        
        # ÖNCE: Elementor Native Replace endpoint'ini kullan (daha güvenli - Elementor'un kendi mantığını kullanır)
        logs.append({"message": f"🔍 Elementor Native Replace endpoint'i çağrılıyor...", "type": "info"})
        
        # Yeni endpoint: custom/v1/elementor-native-replace
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
                    auth=self.auth,
                    json=native_replace_data
                )
                
                if response.status_code == 200:
                    php_result = response.json()
                    php_changes = php_result.get('changes_count', 0)
                    logs.append({"message": f"✅ Elementor Native Replace başarılı: {php_changes} link değiştirildi", "type": "success"})
                    logs.append({"message": f"✅ Elementor cache otomatik temizlendi", "type": "success"})
                    return {
                        "success": True,
                        "message": f"{php_changes} link başarıyla düzeltildi (Elementor Native Replace)",
                        "changes_count": php_changes,
                        "logs": logs
                    }
                else:
                    error_msg = response.text
                    logs.append({"message": f"⚠️ Elementor Native Replace çalışmadı (HTTP {response.status_code}): {error_msg}", "type": "warning"})
        except Exception as e:
            logs.append({"message": f"⚠️ Elementor Native Replace hatası: {str(e)}. Fallback yöntem deneniyor...", "type": "warning"})
        
        # Fallback 1: Eski endpoint'i dene (wp/v2/elementor-meta/{post_id})
        logs.append({"message": f"⚠️ Fallback 1: Eski endpoint deneniyor...", "type": "warning"})
        update_data = {
            'old_url': old_url,
            'new_url': new_url
        }
        success_php, php_result, error_php = await self._make_request("POST", f"elementor-meta/{post_id}", update_data)
        if success_php and php_result:
            php_changes = php_result.get('changes_count', changes_count)
            logs.append({"message": f"✅ Fallback endpoint başarılı: {php_changes} link değiştirildi", "type": "success"})
            logs.append({"message": f"✅ Elementor cache temizlendi", "type": "success"})
            return {
                "success": True,
                "message": f"{php_changes} link başarıyla düzeltildi (Fallback endpoint)",
                "changes_count": php_changes,
                "logs": logs
            }
        
        logs.append({"message": f"⚠️ Tüm PHP endpoint'leri çalışmadı. Python fallback yöntem deneniyor...", "type": "warning"})
        
        # Fallback 2: Python tarafında JSON gönder (eski yöntem)
        logs.append({"message": f"⚠️ Fallback: Python tarafında JSON güncelleme yapılıyor...", "type": "warning"})
        
        # JSON'u escape edilmiş format'a çevir (Elementor formatı)
        import json as json_module
        try:
            # Önce JSON'u parse et
            elementor_data = json_module.loads(new_json) if isinstance(new_json, str) else new_json
            # Sonra minified format'ta dump et
            updated_data_string = json_module.dumps(elementor_data, separators=(',', ':'))
            # Elementor'un istediği escape edilmiş slash formatını ekle
            updated_data_string = updated_data_string.replace('/', '\\/')
            logs.append({"message": f"✅ JSON escape edilmiş formata çevrildi", "type": "success"})
        except Exception as e:
            logs.append({"message": f"⚠️ JSON parse hatası, string olarak gönderiliyor: {str(e)}", "type": "warning"})
            updated_data_string = new_json.replace('/', '\\/')
        
        update_data_fallback = {
            'elementor_data': updated_data_string
        }
        success_custom, custom_result, error_custom = await self._make_request("POST", f"elementor-meta/{post_id}", update_data_fallback)
        if success_custom:
            logs.append({"message": f"✅ Elementor data fallback yöntemle güncellendi", "type": "success"})
            return {
                "success": True,
                "message": f"{changes_count} link başarıyla düzeltildi (fallback)",
                "changes_count": changes_count,
                "logs": logs
            }
        
        logs.append({"message": f"❌ Tüm güncelleme yöntemleri başarısız", "type": "error"})
        return {
            "success": False,
            "message": f"Güncelleme hatası: PHP yöntemi ({error_php}), Fallback yöntemi ({error_custom})",
            "changes_count": changes_count,
            "logs": logs
        }
        
        logs.append({"message": f"✅ {changes_count} link başarıyla düzeltildi", "type": "success"})
        
        return {
            "success": True,
            "message": f"{changes_count} link başarıyla düzeltildi",
            "changes_count": changes_count,
            "logs": logs
        }

