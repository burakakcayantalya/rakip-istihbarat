# ============================================
# AI Helper - Page Analyzer Module
# Sayfa bazlı analiz: HTML'i paragraflara böl ve her paragraf için AI çağrısı yap
# ============================================

import httpx
import asyncio
import random
from typing import List, Dict, Optional, Tuple
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from .models import AIHelperProject, AIHelperCluster, AIHelperOpportunity, add_log
from services.gemini_ai import gemini_ai
from services.deepseek_ai import deepseek_ai
from core.database import get_setting


class PageAnalyzer:
    """Sayfa bazlı analiz: HTML'i paragraflara böl ve her paragraf için AI çağrısı yap"""
    
    def __init__(self, project_id: int, db_session, ai_provider: str = "gemini", ai_model: str = "gemini-flash-latest"):
        self.project_id = project_id
        self.db = db_session
        self.ai_provider = ai_provider
        self.ai_model = ai_model
        
        # AI provider kontrolü
        try:
            from core.database import get_setting
            if ai_provider == "gemini":
                api_key = get_setting(db_session, "GEMINI_API_KEY")
                if not api_key:
                    add_log(project_id, "WARNING", "PAGE_ANALYZER", "Gemini API key bulunamadı. Lütfen ayarlardan ekleyin.", {}, db_session)
            elif ai_provider == "deepseek":
                api_key = get_setting(db_session, "DEEPSEEK_API_KEY")
                if not api_key:
                    add_log(project_id, "WARNING", "PAGE_ANALYZER", "Deepseek API key bulunamadı. Lütfen ayarlardan ekleyin.", {}, db_session)
        except:
            pass
    
    async def _generate_text(self, prompt: str, max_retries: int = 3) -> str:
        """
        AI provider'a göre metin üret (retry mekanizması ile)
        
        Args:
            prompt: AI'a gönderilecek prompt
            max_retries: Maksimum retry sayısı (default: 3)
        
        Returns:
            AI'dan gelen response
        """
        last_error = None
        
        for attempt in range(max_retries):
            try:
                if self.ai_provider == "gemini":
                    response = await gemini_ai.generate(prompt, max_tokens=2000)
                    if not response or not response.strip():
                        add_log(self.project_id, "WARNING", "PAGE_ANALYZER", f"Gemini boş response döndürdü", {
                            "prompt_length": len(prompt),
                            "provider": "gemini",
                            "attempt": attempt + 1
                        }, self.db)
                    return response or ""
                elif self.ai_provider == "deepseek":
                    messages = [
                        {"role": "system", "content": "Sen bir SEO uzmanısın. Internal linking ve içerik optimizasyonu konusunda uzmanlaşmışsın."},
                        {"role": "user", "content": prompt}
                    ]
                    response = await deepseek_ai.chat(messages, max_tokens=2000)
                    
                    if not isinstance(response, str):
                        add_log(self.project_id, "ERROR", "PAGE_ANALYZER", f"Deepseek response string değil: {type(response)}", {
                            "prompt_length": len(prompt),
                            "provider": "deepseek",
                            "response_type": str(type(response)),
                            "attempt": attempt + 1
                        }, self.db)
                        return ""
                    
                    if not response or not response.strip():
                        add_log(self.project_id, "WARNING", "PAGE_ANALYZER", f"Deepseek boş response döndürdü", {
                            "prompt_length": len(prompt),
                            "provider": "deepseek",
                            "attempt": attempt + 1
                        }, self.db)
                    return response or ""
                else:
                    raise ValueError(f"Bilinmeyen AI provider: {self.ai_provider}")
            
            except Exception as e:
                last_error = e
                error_type = str(type(e).__name__)
                error_msg = str(e)
                
                # 503, 429, 500 gibi geçici hatalar için retry yap
                is_retryable = (
                    "503" in error_msg or 
                    "429" in error_msg or 
                    "500" in error_msg or
                    "Service Unavailable" in error_msg or
                    "rate limit" in error_msg.lower() or
                    "timeout" in error_msg.lower()
                )
                
                if is_retryable and attempt < max_retries - 1:
                    # Exponential backoff: 2^attempt saniye bekle (1s, 2s, 4s)
                    wait_seconds = 2 ** attempt
                    add_log(self.project_id, "WARNING", "PAGE_ANALYZER", f"AI API hatası (geçici), {wait_seconds}s sonra tekrar denenecek (deneme {attempt + 1}/{max_retries})", {
                        "error": error_msg[:200],
                        "error_type": error_type,
                        "provider": self.ai_provider,
                        "attempt": attempt + 1,
                        "max_retries": max_retries,
                        "wait_seconds": wait_seconds
                    }, self.db)
                    
                    await asyncio.sleep(wait_seconds)
                    continue
                else:
                    # Retry yapılmayacak veya max retry'a ulaşıldı
                    if attempt == max_retries - 1:
                        add_log(self.project_id, "ERROR", "PAGE_ANALYZER", f"AI text generation hatası (tüm denemeler başarısız): {error_msg}", {
                            "error": error_msg,
                            "error_type": error_type,
                            "provider": self.ai_provider,
                            "prompt_length": len(prompt),
                            "attempts": max_retries
                        }, self.db)
                    raise Exception(f"AI text generation hatası: {error_msg} (Type: {error_type})") from e
        
        # Buraya gelmemeli ama yine de
        if last_error:
            raise last_error
        return ""
    
    async def _get_page_html(self, url: str) -> Optional[str]:
        """Sayfa HTML'ini al"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    return response.text
        except Exception as e:
            add_log(self.project_id, "ERROR", "PAGE_ANALYZER", f"HTML alınamadı ({url}): {str(e)}", {"url": url, "error": str(e)}, self.db)
        return None
    
    def _count_internal_links(self, html: str, base_domain: str) -> int:
        """
        Sayfadaki internal link sayısını say (menu/footer hariç)
        
        Args:
            html: Sayfa HTML'i
            base_domain: Site domain'i (örn: "example.com")
        
        Returns:
            Internal link sayısı (menu/footer hariç)
        """
        soup = BeautifulSoup(html, 'html.parser')
        
        # Menu ve footer'ı hariç tut
        for elem in soup.find_all(['nav', 'header', 'footer', 'aside']):
            elem.decompose()
        
        # Ana içerik alanını bul
        content_selectors = [
            'article',
            'main',
            '[role="main"]',
            '.content',
            '.post-content',
            '.entry-content',
            '#content'
        ]
        
        content_div = None
        for selector in content_selectors:
            content_div = soup.select_one(selector)
            if content_div:
                break
        
        if not content_div:
            content_div = soup.find('body')
            if not content_div:
                content_div = soup
        
        # Başlıkları (h1-h6) hariç tut - onlar internal link sayımına dahil değil
        for heading in content_div.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            heading.decompose()
        
        # Internal linkleri say (sadece paragraflardaki)
        internal_links = 0
        for link in content_div.find_all('a', href=True):
            href = link.get('href', '')
            if not href:
                continue
            
            # Absolute URL kontrolü
            if href.startswith('http://') or href.startswith('https://'):
                if base_domain in href:
                    internal_links += 1
            # Relative URL kontrolü
            elif href.startswith('/') or not href.startswith('#'):
                internal_links += 1
        
        return internal_links
    
    def _extract_paragraphs(self, html: str) -> List[Dict[str, str]]:
        """
        HTML'den paragrafları çıkar ve her paragraftaki internal link sayısını kontrol et
        
        Returns:
            [
                {"index": 0, "text": "paragraf metni", "html": "<p>paragraf html</p>", "has_internal_link": False},
                ...
            ]
        """
        soup = BeautifulSoup(html, 'html.parser')
        paragraphs = []
        
        # Ana içerik alanını bul (article, main, content, vb.)
        content_selectors = [
            'article',
            'main',
            '[role="main"]',
            '.content',
            '.post-content',
            '.entry-content',
            '#content'
        ]
        
        content_div = None
        for selector in content_selectors:
            content_div = soup.select_one(selector)
            if content_div:
                break
        
        if not content_div:
            # Ana içerik bulunamazsa body'yi kullan
            content_div = soup.find('body')
            if not content_div:
                content_div = soup
        
        # Sadece <p> tag'lerini bul (başlıklar hariç)
        # Önce başlıkları (h1-h6) kaldır - bunlar işlemden muaf
        for heading in content_div.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            heading.decompose()  # Başlıkları tamamen kaldır
        
        # Sadece <p> tag'lerini al (div, section vb. değil)
        para_elements = content_div.find_all('p', recursive=True)
        
        for idx, elem in enumerate(para_elements):
            # Boş elementleri atla
            text = elem.get_text(strip=True)
            if not text or len(text) < 20:  # En az 20 karakter
                continue
            
            # Bu paragrafta internal link var mı kontrol et
            has_internal_link = False
            for link in elem.find_all('a', href=True):
                href = link.get('href', '')
                if href and (href.startswith('http') or href.startswith('/')):
                    has_internal_link = True
                    break
            
            # HTML'i temizle: Elementor widget kodlarını kaldır, saf HTML'e çevir
            # Element'i kopyala (orijinali bozmamak için)
            clean_elem = BeautifulSoup(str(elem), 'html.parser')
            
            # Elementor class'larını ve data attribute'larını temizle
            for tag in clean_elem.find_all(True):
                # Elementor class'larını kaldır
                if tag.get('class'):
                    original_classes = tag['class']
                    if isinstance(original_classes, list):
                        clean_classes = [c for c in original_classes if not c.startswith('elementor') and not c.startswith('widget')]
                        if clean_classes:
                            tag['class'] = clean_classes
                        else:
                            del tag['class']
                    elif isinstance(original_classes, str):
                        if not original_classes.startswith('elementor') and not original_classes.startswith('widget'):
                            pass  # Class'ı koru
                        else:
                            del tag['class']
                
                # Elementor data attribute'larını kaldır
                attrs_to_remove = []
                for attr in list(tag.attrs.keys()):
                    if attr.startswith('data-elementor') or attr.startswith('data-widget') or attr.startswith('data-id'):
                        attrs_to_remove.append(attr)
                for attr in attrs_to_remove:
                    del tag[attr]
            
            # Elementor wrapper div'lerini kaldır (sadece içeriği al)
            for wrapper in clean_elem.find_all(['div', 'section'], class_=lambda x: x and ('elementor' in str(x).lower() or 'widget' in str(x).lower())):
                # Wrapper'ın içeriğini al, wrapper'ı kaldır
                wrapper.unwrap()
            
            # Saf HTML'i al (sadece içerik, wrapper'lar yok)
            html_content = str(clean_elem)
            
            paragraphs.append({
                "index": idx,
                "text": text,
                "html": html_content,
                "has_internal_link": has_internal_link
            })
        
        return paragraphs
    
    async def analyze_page_paragraphs(
        self, 
        source_url: str, 
        cluster_id: int,
        all_sitemap_urls: List[str]
    ) -> int:
        """
        Bir sayfayı analiz et: HTML'i paragraflara böl, internal link kontrolü yap, her paragraf için AI çağrısı yap
        
        Args:
            source_url: Analiz edilecek sayfa URL'i
            cluster_id: Küme ID
            all_sitemap_urls: Sitemap'teki tüm URL'ler (link önerileri için)
        
        Returns:
            Oluşturulan opportunity sayısı
        """
        add_log(self.project_id, "INFO", "PAGE_ANALYZER", f"📄 Sayfa analizi başlatıldı: {source_url}", {
            "url": source_url,
            "cluster_id": cluster_id
        }, self.db)
        
        # HTML'i al
        html = await self._get_page_html(source_url)
        if not html:
            add_log(self.project_id, "WARNING", "PAGE_ANALYZER", f"HTML alınamadı: {source_url}", {"url": source_url}, self.db)
            return 0
        
        # Base domain'i çıkar
        from urllib.parse import urlparse
        parsed_url = urlparse(source_url)
        base_domain = parsed_url.netloc
        
        # Internal link sayısını kontrol et (menu/footer hariç)
        internal_link_count = self._count_internal_links(html, base_domain)
        add_log(self.project_id, "INFO", "PAGE_ANALYZER", f"🔗 Sayfada {internal_link_count} internal link bulundu (menu/footer hariç)", {
            "url": source_url,
            "internal_link_count": internal_link_count
        }, self.db)
        
        # Eğer 12'den fazla internal link varsa sayfaya dokunma
        if internal_link_count > 12:
            add_log(self.project_id, "INFO", "PAGE_ANALYZER", f"⏭️ Sayfada {internal_link_count} internal link var (12'den fazla), atlanıyor: {source_url}", {
                "url": source_url,
                "internal_link_count": internal_link_count,
                "reason": "12'den fazla internal link mevcut"
            }, self.db)
            return 0
        
        # Paragraflara böl
        paragraphs = self._extract_paragraphs(html)
        if not paragraphs:
            add_log(self.project_id, "WARNING", "PAGE_ANALYZER", f"Paragraf bulunamadı: {source_url}", {"url": source_url}, self.db)
            return 0
        
        # Sadece internal link olmayan paragrafları filtrele
        paragraphs_without_links = [p for p in paragraphs if not p.get("has_internal_link", False)]
        
        if not paragraphs_without_links:
            add_log(self.project_id, "INFO", "PAGE_ANALYZER", f"ℹ️ Tüm paragraflarda internal link var, atlanıyor: {source_url}", {
                "url": source_url,
                "total_paragraphs": len(paragraphs)
            }, self.db)
            return 0
        
        add_log(self.project_id, "INFO", "PAGE_ANALYZER", f"📝 {len(paragraphs_without_links)} paragraf bulundu (internal link olmayan): {source_url}", {
            "url": source_url,
            "total_paragraphs": len(paragraphs),
            "paragraphs_without_links": len(paragraphs_without_links)
        }, self.db)
        
        # Sitemap URL'lerini liste olarak hazırla (kaynak URL hariç)
        other_urls = [url for url in all_sitemap_urls if url != source_url]
        urls_list = "\n".join([f"- {url}" for url in other_urls[:50]])  # İlk 50 URL
        
        total_opportunities = 0
        
        # Her paragraf için AI çağrısı yap (sadece internal link olmayanlar)
        for para_idx, paragraph in enumerate(paragraphs_without_links):
            try:
                add_log(self.project_id, "INFO", "PAGE_ANALYZER", f"📝 Paragraf {para_idx + 1}/{len(paragraphs)} analiz ediliyor: {source_url}", {
                    "url": source_url,
                    "paragraph_index": para_idx,
                    "total_paragraphs": len(paragraphs)
                }, self.db)
                
                # İlk paragraf hemen, diğerleri random 5 dakika bekle (4-6 dakika arası)
                if para_idx > 0:
                    wait_minutes = random.uniform(4.0, 6.0)  # 4-6 dakika arası random
                    wait_seconds = int(wait_minutes * 60)
                    add_log(self.project_id, "INFO", "PAGE_ANALYZER", f"⏳ {wait_minutes:.1f} dakika bekleniyor (paragraf {para_idx + 1})...", {
                        "url": source_url,
                        "paragraph_index": para_idx,
                        "wait_minutes": wait_minutes
                    }, self.db)
                    await asyncio.sleep(wait_seconds)
                
                # AI prompt'u hazırla (temizlenmiş HTML paragrafı ile)
                prompt = f"""Aşağıdaki bir makale paragrafı (temizlenmiş HTML formatında) ve sitemap'teki diğer URL'lerin listesi var. Bu paragrafa internal link eklenmesi gerekiyorsa, bütün paragrafı Elementor HTML widget'ine direkt koyulacak şekilde HTML kodları ile paylaş.

PARAGRAF (HTML):
{paragraph['html']}

PARAGRAF (METİN):
{paragraph['text'][:800]}

SİTEMAP'TEKİ DİĞER URL'LER:
{urls_list}

EĞER LİNK EKLENMESİ GEREKİYORSA:
1. Paragrafa uygun internal link(ler) ekle
2. Her link için alt_text (title attribute) otomatik olarak koda uygula
3. Bütün paragrafı HTML kodları ile döndür (Elementor widget'e direkt koyulacak şekilde)
4. Linkler doğal görünmeli, paragrafın akışını bozmamalı

EĞER LİNK EKLENMESİ GEREKMİYORSA:
Sadece "no_link_needed" döndür.

Sadece JSON formatında cevap ver:
{{
  "needs_link": true/false,
  "html_snippet": "<p>Güncellenmiş paragraf HTML kodu (linkler dahil, alt_text'ler uygulanmış)</p>",
  "links_added": [
    {{
      "target_url": "https://example.com/target-page",
      "anchor_text": "anchor text",
      "alt_text": "link açıklaması (title attribute için)"
    }}
  ],
  "reason": "neden link eklendi/eklenmedi"
}}

Sadece JSON döndür, başka açıklama yapma."""
                
                add_log(self.project_id, "INFO", "PAGE_ANALYZER", f"AI'a prompt gönderiliyor (paragraf {para_idx + 1})...", {
                    "url": source_url,
                    "paragraph_index": para_idx,
                    "provider": self.ai_provider,
                    "model": self.ai_model,
                    "prompt_length": len(prompt),
                    "prompt": prompt
                }, self.db)
                
                try:
                    response = await self._generate_text(prompt)
                except Exception as e:
                    add_log(self.project_id, "ERROR", "PAGE_ANALYZER", f"AI text generation exception (paragraf {para_idx + 1}): {str(e)}", {
                        "url": source_url,
                        "paragraph_index": para_idx,
                        "error": str(e)
                    }, self.db)
                    continue
                
                if not response or not response.strip():
                    add_log(self.project_id, "ERROR", "PAGE_ANALYZER", f"AI'dan boş response alındı (paragraf {para_idx + 1})", {
                        "url": source_url,
                        "paragraph_index": para_idx
                    }, self.db)
                    continue
                
                # AI'dan gelen cevabı logla
                add_log(self.project_id, "INFO", "PAGE_ANALYZER", f"AI'dan cevap alındı (paragraf {para_idx + 1})", {
                    "url": source_url,
                    "paragraph_index": para_idx,
                    "response": response,
                    "response_length": len(response)
                }, self.db)
                
                # JSON'u parse et
                response_clean = response.strip()
                if "```json" in response_clean:
                    response_clean = response_clean.split("```json")[1].split("```")[0].strip()
                elif "```" in response_clean:
                    response_clean = response_clean.split("```")[1].split("```")[0].strip()
                
                if "{" in response_clean and "}" in response_clean:
                    start = response_clean.find("{")
                    end = response_clean.rfind("}") + 1
                    response_clean = response_clean[start:end]
                
                if not response_clean or not response_clean.strip():
                    add_log(self.project_id, "ERROR", "PAGE_ANALYZER", f"AI response'undan JSON çıkarılamadı (paragraf {para_idx + 1})", {
                        "url": source_url,
                        "paragraph_index": para_idx,
                        "response_preview": response[:200]
                    }, self.db)
                    continue
                
                import json
                try:
                    ai_result = json.loads(response_clean)
                except json.JSONDecodeError as e:
                    add_log(self.project_id, "ERROR", "PAGE_ANALYZER", f"JSON parse hatası (paragraf {para_idx + 1}): {str(e)}", {
                        "url": source_url,
                        "paragraph_index": para_idx,
                        "error": str(e),
                        "response_preview": response_clean[:500]
                    }, self.db)
                    continue
                
                if not isinstance(ai_result, dict):
                    add_log(self.project_id, "ERROR", "PAGE_ANALYZER", f"AI response dictionary değil (paragraf {para_idx + 1}): {type(ai_result)}", {
                        "url": source_url,
                        "paragraph_index": para_idx
                    }, self.db)
                    continue
                
                # Link eklenmesi gerekiyorsa opportunity oluştur
                needs_link = ai_result.get("needs_link", False)
                html_snippet = ai_result.get("html_snippet", "")
                links_added = ai_result.get("links_added", [])
                
                if needs_link and html_snippet and links_added:
                    # Her link için opportunity oluştur
                    for link_info in links_added:
                        if not isinstance(link_info, dict):
                            continue
                        
                        target_url = link_info.get("target_url", "")
                        anchor_text = link_info.get("anchor_text", "")
                        alt_text = link_info.get("alt_text", "")
                        
                        if not target_url:
                            continue
                        
                        # HTML snippet'e alt_text ekle (eğer yoksa)
                        if alt_text and 'title=' not in html_snippet:
                            # Anchor tag'lerine title attribute ekle
                            import re
                            html_snippet = re.sub(
                                r'(<a[^>]*href=["\']' + re.escape(target_url) + r'["\'][^>]*)>',
                                r'\1 title="' + alt_text.replace('"', '&quot;') + '">',
                                html_snippet
                            )
                        
                        opportunity = AIHelperOpportunity(
                            project_id=self.project_id,
                            cluster_id=cluster_id,
                            source_url=source_url,
                            target_url=target_url,
                            target_keyword=anchor_text,
                            html_snippet=html_snippet,
                            paragraph_index=para_idx,
                            original_paragraph=paragraph['text'],
                            confidence_score=85.0,  # Yüksek confidence (AI direkt HTML verdi)
                            status="IN_POOL"
                        )
                        self.db.add(opportunity)
                        total_opportunities += 1
                    
                    add_log(self.project_id, "SUCCESS", "PAGE_ANALYZER", f"✅ Paragraf {para_idx + 1} için {len(links_added)} link opportunity oluşturuldu", {
                        "url": source_url,
                        "paragraph_index": para_idx,
                        "links_count": len(links_added)
                    }, self.db)
                else:
                    add_log(self.project_id, "INFO", "PAGE_ANALYZER", f"ℹ️ Paragraf {para_idx + 1} için link gerekmiyor", {
                        "url": source_url,
                        "paragraph_index": para_idx,
                        "reason": ai_result.get("reason", "")
                    }, self.db)
                
                # Her paragraf arasında kısa bir bekleme (rate limiting için)
                await asyncio.sleep(2)
                
            except Exception as e:
                add_log(self.project_id, "ERROR", "PAGE_ANALYZER", f"Paragraf analizi hatası ({source_url}, paragraf {para_idx}): {str(e)}", {
                    "error": str(e),
                    "url": source_url,
                    "paragraph_index": para_idx
                }, self.db)
                continue
        
        # Tüm opportunity'leri commit et
        self.db.commit()
        
        return total_opportunities
    
    async def analyze_cluster_pages(
        self,
        cluster_id: int,
        cluster_urls: List[str],
        site_id: int
    ) -> int:
        """
        Kümedeki tüm sayfaları analiz et (sayfa bazlı, paragraf bazlı)
        
        Args:
            cluster_id: Küme ID
            cluster_urls: Kümedeki URL'ler
            site_id: Site ID
        
        Returns:
            Toplam oluşturulan opportunity sayısı
        """
        add_log(self.project_id, "INFO", "PAGE_ANALYZER", f"🔍 Küme analizi başlatıldı: {len(cluster_urls)} sayfa", {
            "cluster_id": cluster_id,
            "url_count": len(cluster_urls)
        }, self.db)
        
        if not cluster_urls or len(cluster_urls) == 0:
            add_log(self.project_id, "WARNING", "PAGE_ANALYZER", "Kümede URL bulunmuyor", {"cluster_id": cluster_id}, self.db)
            return 0
        
        # Sitemap'ten tüm URL'leri al
        from core.database import Site
        site = self.db.query(Site).filter(Site.id == site_id).first()
        if not site or not site.sitemap_url:
            add_log(self.project_id, "ERROR", "PAGE_ANALYZER", "Site veya sitemap URL bulunamadı", {"site_id": site_id}, self.db)
            return 0
        
        from .strategist import Strategist
        strategist = Strategist(self.project_id, self.db, ai_provider=self.ai_provider, ai_model=self.ai_model)
        all_sitemap_urls = await strategist._parse_sitemap(site.sitemap_url)
        
        add_log(self.project_id, "INFO", "PAGE_ANALYZER", f"📋 Sitemap'ten {len(all_sitemap_urls)} URL alındı", {
            "total_urls": len(all_sitemap_urls)
        }, self.db)
        
        total_opportunities = 0
        
        # Her sayfa için analiz yap
        for idx, source_url in enumerate(cluster_urls, 1):
            try:
                add_log(self.project_id, "INFO", "PAGE_ANALYZER", f"📄 Sayfa {idx}/{len(cluster_urls)} analiz ediliyor: {source_url}", {
                    "cluster_id": cluster_id,
                    "url_index": idx,
                    "total_urls": len(cluster_urls),
                    "url": source_url
                }, self.db)
                
                opportunities = await self.analyze_page_paragraphs(
                    source_url=source_url,
                    cluster_id=cluster_id,
                    all_sitemap_urls=all_sitemap_urls
                )
                
                total_opportunities += opportunities
                
                add_log(self.project_id, "SUCCESS", "PAGE_ANALYZER", f"✅ Sayfa {idx}/{len(cluster_urls)} analizi tamamlandı: {opportunities} opportunity", {
                    "url": source_url,
                    "opportunities": opportunities
                }, self.db)
                
                # Her sayfa arasında kısa bir bekleme
                await asyncio.sleep(3)
                
            except Exception as e:
                add_log(self.project_id, "ERROR", "PAGE_ANALYZER", f"Sayfa analizi hatası ({source_url}): {str(e)}", {
                    "error": str(e),
                    "url": source_url
                }, self.db)
                continue
        
        add_log(self.project_id, "SUCCESS", "PAGE_ANALYZER", f"✅ Küme analizi tamamlandı: {total_opportunities} opportunity", {
            "cluster_id": cluster_id,
            "total_opportunities": total_opportunities
        }, self.db)
        
        return total_opportunities

