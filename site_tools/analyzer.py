# ============================================
# Site Tools - Analyzer Engine
# DÜZELTİLMİŞ: HTTP fetch ile HTML alma
# ============================================

import asyncio
import httpx
import json
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass

from config import settings


@dataclass
class H1Result:
    """H1 analiz sonucu"""
    status: str  # ok, missing, duplicate
    count: int
    contents: List[str]


@dataclass
class SchemaResult:
    """Schema analiz sonucu"""
    status: str  # ok, missing, error
    types: List[str]
    errors: Optional[str] = None


@dataclass
class LinkCheckResult:
    """Link kontrol sonucu"""
    url: str
    status_code: int  # Redirect veren URL'in status code'u (301, 302, vs.)
    final_url: str
    final_status_code: int  # Final URL'in status code'u (genellikle 200)
    redirect_chain: List[Dict]
    is_broken: bool
    is_redirect: bool


class SiteAnalyzer:
    """
    Site analiz motoru.
    H1, Schema, Internal Link kontrolü yapar.
    """
    
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    ]
    
    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """HTTP client al veya oluştur"""
        if self._client is None or self._client.is_closed:
            import random
            self._client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=False,
                headers={
                    "User-Agent": random.choice(self.USER_AGENTS),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
                }
            )
        return self._client
    
    async def close(self):
        """Client'ı kapat ve cache'i temizle"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None  # Cache'i temizle
    
    async def clear_cache_for_url(self, url: str):
        """
        Belirli bir URL için cache'i temizle
        Client'ı yeniden oluşturarak cache'i temizler
        """
        # Client'ı kapat ve yeniden oluştur (cache temizleme)
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
        # Yeni client oluşturulacak (bir sonraki _get_client çağrısında)
        print(f"🔄 Cache temizlendi: {url}")
    
    # ============================================
    # HTML FETCH & CLEAN
    # ============================================
    
    async def fetch_html(self, url: str) -> Optional[str]:
        """
        Sayfanın HTML içeriğini çek.
        Analiz için gerekli - düz metin değil, tam HTML.
        """
        try:
            client = await self._get_client()
            response = await client.get(url, follow_redirects=True)
            
            if response.status_code == 200:
                return response.text
            else:
                print(f"⚠️ HTTP {response.status_code}: {url[:50]}")
                return None
                
        except httpx.RequestError as e:
            print(f"❌ Fetch hatası ({url[:50]}): {str(e)[:50]}")
            return None
        except Exception as e:
            print(f"❌ Beklenmeyen hata ({url[:50]}): {str(e)[:50]}")
            return None
    
    def clean_html(self, html_content: str) -> str:
        """
        HTML'i temizle - Elementor wrapper'larını kaldır, sadece içerik taglarını al.
        
        Optimizasyon: 10.000 satırlık Elementor HTML'i ~500-1000 satırlık temiz HTML'e dönüştürür.
        Sadece şunları tutar: nav, p, h1-h6, a tagları
        
        Args:
            html_content: Ham HTML içeriği
            
        Returns:
            Temizlenmiş HTML (sadece içerik tagları)
        """
        if not html_content:
            return ""
        
        try:
            soup = BeautifulSoup(html_content, 'lxml')
            
            # İzin verilen taglar: nav, p, h1-h6, a
            allowed_tags = {'nav', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a'}
            
            # Tüm tagları kontrol et - izin verilmeyenleri kaldır
            for element in soup.find_all(True):
                tag_name = element.name.lower()
                
                # İzin verilen tag ise, sadece attribute'ları temizle
                if tag_name in allowed_tags:
                    # Elementor class'larını kaldır
                    if element.get('class'):
                        element['class'] = [cls for cls in element['class'] 
                                           if not cls.startswith('elementor-') 
                                           and not cls.startswith('widget-')]
                        if not element['class']:
                            del element['class']
                    
                    # Elementor data attribute'larını kaldır
                    attrs_to_remove = []
                    for attr in list(element.attrs.keys()):
                        if attr.startswith('data-elementor-') or attr.startswith('data-widget-'):
                            attrs_to_remove.append(attr)
                    for attr in attrs_to_remove:
                        del element[attr]
                
                # İzin verilmeyen tag ise, içeriğini koruyarak unwrap et
                else:
                    element.unwrap()
            
            # Temiz HTML'i string olarak döndür
            cleaned_html = str(soup)
            
            # İstatistik (debug için)
            original_size = len(html_content)
            cleaned_size = len(cleaned_html)
            reduction = ((original_size - cleaned_size) / original_size * 100) if original_size > 0 else 0
            
            if reduction > 50:  # %50'den fazla küçülme varsa logla
                print(f"   📦 HTML temizlendi: {original_size:,} → {cleaned_size:,} byte (%{reduction:.1f} azalma)")
            
            return cleaned_html
            
        except Exception as e:
            print(f"⚠️ HTML temizleme hatası: {e}")
            # Hata durumunda orijinal HTML'i döndür
            return html_content
    
    # ============================================
    # H1 ANALİZİ
    # ============================================
    
    def analyze_h1(self, html_content: str) -> H1Result:
        """
        HTML içeriğindeki H1 tag'lerini analiz et.
        
        Returns:
            H1Result: status (ok/missing/duplicate), count, contents
        """
        if not html_content:
            return H1Result(status="missing", count=0, contents=[])
        
        try:
            soup = BeautifulSoup(html_content, 'lxml')
            h1_tags = soup.find_all('h1')
            
            contents = []
            for h1 in h1_tags:
                text = h1.get_text(strip=True)
                if text:
                    contents.append(text[:200])  # Max 200 karakter
            
            count = len(contents)
            
            if count == 0:
                status = "missing"
            elif count == 1:
                status = "ok"
            else:
                status = "duplicate"
            
            return H1Result(status=status, count=count, contents=contents)
        
        except Exception as e:
            print(f"❌ H1 analiz hatası: {e}")
            return H1Result(status="error", count=0, contents=[])
    
    # ============================================
    # SCHEMA ANALİZİ
    # ============================================
    
    def analyze_schema(self, html_content: str) -> SchemaResult:
        """
        HTML içeriğindeki Schema.org yapısını analiz et.
        JSON-LD formatını kontrol eder.
        
        Returns:
            SchemaResult: status (ok/missing/error), types, errors
        """
        if not html_content:
            return SchemaResult(status="missing", types=[])
        
        try:
            soup = BeautifulSoup(html_content, 'lxml')
            
            # JSON-LD script tag'lerini bul
            schema_scripts = soup.find_all('script', type='application/ld+json')
            
            if not schema_scripts:
                return SchemaResult(status="missing", types=[])
            
            schema_types = []
            errors = []
            
            for script in schema_scripts:
                try:
                    content = script.string
                    if not content:
                        continue
                    
                    # Temizle (bazen comment veya whitespace olabiliyor)
                    content = content.strip()
                    if not content:
                        continue
                    
                    # JSON parse et
                    data = json.loads(content)
                    
                    # Schema type'ları çıkar
                    types = self._extract_schema_types(data)
                    schema_types.extend(types)
                    
                except json.JSONDecodeError as e:
                    errors.append(f"JSON hatası: {str(e)[:30]}")
                except Exception as e:
                    errors.append(f"Parse hatası: {str(e)[:30]}")
            
            # Duplicate type'ları temizle
            schema_types = list(set(schema_types))
            
            if errors and not schema_types:
                return SchemaResult(
                    status="error",
                    types=[],
                    errors="; ".join(errors[:3])  # Max 3 hata
                )
            elif schema_types:
                return SchemaResult(
                    status="ok", 
                    types=schema_types,
                    errors="; ".join(errors[:3]) if errors else None
                )
            else:
                return SchemaResult(status="missing", types=[])
        
        except Exception as e:
            print(f"❌ Schema analiz hatası: {e}")
            return SchemaResult(status="error", types=[], errors=str(e)[:50])
    
    def _extract_schema_types(self, data) -> List[str]:
        """Schema verilerinden type'ları çıkar"""
        types = []
        
        if isinstance(data, dict):
            # @type alanını kontrol et
            if "@type" in data:
                t = data["@type"]
                if isinstance(t, list):
                    types.extend(t)
                else:
                    types.append(str(t))
            
            # @graph içinde nested schema'lar olabilir
            if "@graph" in data:
                for item in data["@graph"]:
                    types.extend(self._extract_schema_types(item))
        
        elif isinstance(data, list):
            for item in data:
                types.extend(self._extract_schema_types(item))
        
        return types
    
    # ============================================
    # INTERNAL LINK ANALİZİ
    # ============================================
    
    def extract_internal_links(self, html_content: str, base_url: str, site_domain: str) -> List[Dict]:
        """
        HTML'den internal linkleri çıkar.
        
        Returns:
            List[Dict]: [{"url": "...", "anchor_text": "..."}]
        """
        if not html_content:
            return []
        
        try:
            soup = BeautifulSoup(html_content, 'lxml')
            links = []
            seen_urls = set()
            
            # Site domain'ini normalize et
            site_domain = site_domain.lower().replace('www.', '')
            
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href'].strip()

                # Boş veya javascript linkleri atla
                if not href or href.startswith(('javascript:', 'mailto:', 'tel:', '#', 'data:')):
                    continue

                # WordPress navigation linklerini atla (Previous/Next Post)
                # Bu linkler tema tarafından otomatik oluşturulur ve Elementor ile düzenlenemez
                parent = a_tag.parent
                if parent:
                    parent_class = parent.get('class', [])
                    if isinstance(parent_class, list):
                        parent_classes = ' '.join(parent_class)
                    else:
                        parent_classes = str(parent_class)

                    # WordPress tema navigation class'ları
                    nav_keywords = ['nav-previous', 'nav-next', 'nav-links', 'post-navigation',
                                   'entry-navigation', 'pagination', 'ast-left-arrow', 'ast-right-arrow']

                    if any(keyword in parent_classes.lower() for keyword in nav_keywords):
                        # Navigation link - atla (Elementor dışı)
                        continue

                    # rel="prev" veya rel="next" olan linkleri de atla
                    rel_attr = a_tag.get('rel', [])
                    if isinstance(rel_attr, list):
                        rel_attr = ' '.join(rel_attr)
                    if 'prev' in str(rel_attr).lower() or 'next' in str(rel_attr).lower():
                        continue
                
                # Absolute URL'ye çevir
                full_url = urljoin(base_url, href)
                
                # Parse et
                parsed = urlparse(full_url)
                
                # Internal link mi kontrol et
                parsed_domain = parsed.netloc.lower().replace('www.', '')
                
                if site_domain in parsed_domain or parsed_domain in site_domain:
                    # URL'yi normalize et
                    normalized_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                    if parsed.query:
                        normalized_url += f"?{parsed.query}"
                    
                    # Duplicate kontrolü
                    if normalized_url in seen_urls:
                        continue
                    seen_urls.add(normalized_url)
                    
                    anchor_text = a_tag.get_text(strip=True)[:200] if a_tag.get_text(strip=True) else ""
                    
                    links.append({
                        "url": normalized_url,
                        "anchor_text": anchor_text
                    })
            
            return links
        
        except Exception as e:
            print(f"❌ Link çıkarma hatası: {e}")
            return []
    
    async def check_link(self, url: str, max_redirects: int = 5) -> LinkCheckResult:
        """
        Tek bir linki kontrol et, redirect chain'i takip et.
        
        Returns:
            LinkCheckResult: status_code, final_url, redirect_chain, is_broken, is_redirect
        """
        client = await self._get_client()
        
        redirect_chain = []
        current_url = url
        redirect_status = 0  # İlk redirect'in status code'u (301, 302, vs.)
        final_status = 0  # Final URL'in status code'u (genellikle 200)
        
        try:
            for i in range(max_redirects + 1):
                try:
                    # Önce HEAD dene (daha hızlı)
                    response = await client.head(current_url, follow_redirects=False, timeout=10.0)
                    status = response.status_code
                    
                    # HEAD desteklemiyorsa GET dene
                    if status == 405:
                        response = await client.get(current_url, follow_redirects=False, timeout=10.0)
                        status = response.status_code
                    
                    # İlk redirect'in status code'unu kaydet
                    if i == 0 and status in (301, 302, 303, 307, 308):
                        redirect_status = status
                    
                    final_status = status
                    
                    # Redirect mi?
                    if status in (301, 302, 303, 307, 308):
                        location = response.headers.get('location', '')
                        if location:
                            redirect_chain.append({
                                "url": current_url,
                                "status": status
                            })
                            current_url = urljoin(current_url, location)
                            continue
                    
                    # Redirect değil, döngüden çık
                    break
                    
                except httpx.RequestError as e:
                    final_status = 0  # Connection error
                    if i == 0:
                        redirect_status = 0
                    break
                except Exception as e:
                    final_status = 0
                    if i == 0:
                        redirect_status = 0
                    break
        
        except Exception as e:
            final_status = 0
            redirect_status = 0
        
        is_redirect = len(redirect_chain) > 0
        is_broken = final_status == 0 or final_status >= 400
        
        # Eğer redirect varsa, status_code redirect'in status code'u, yoksa final_status
        return LinkCheckResult(
            url=url,
            status_code=redirect_status if is_redirect else final_status,
            final_url=current_url,
            final_status_code=final_status,
            redirect_chain=redirect_chain,
            is_broken=is_broken,
            is_redirect=is_redirect
        )
    
    async def check_links_batch(
        self, 
        links: List[Dict], 
        batch_size: int = 3,
        delay: float = 0.5
    ) -> List[LinkCheckResult]:
        """
        Birden fazla linki batch halinde kontrol et.
        """
        results = []
        
        for i in range(0, len(links), batch_size):
            batch = links[i:i + batch_size]
            
            tasks = [self.check_link(link["url"]) for link in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for j, result in enumerate(batch_results):
                if isinstance(result, LinkCheckResult):
                    results.append(result)
                else:
                    # Hata durumunda
                    results.append(LinkCheckResult(
                        url=batch[j]["url"],
                        status_code=0,
                        final_url=batch[j]["url"],
                        final_status_code=0,
                        redirect_chain=[],
                        is_broken=True,
                        is_redirect=False
                    ))
            
            # Rate limiting
            if i + batch_size < len(links):
                await asyncio.sleep(delay)
        
        return results
    
    # ============================================
    # TAM SAYFA ANALİZİ
    # ============================================
    
    async def analyze_page_full(self, url: str, site_domain: str) -> Optional[Dict]:
        """
        Bir sayfayı tam analiz et:
        1. HTML'i HTTP ile çek
        2. HTML'i temizle (Elementor wrapper'larını kaldır, sadece içerik taglarını al)
        3. H1 analizi
        4. Schema analizi
        5. Internal link çıkarma
        
        Optimizasyon: 10.000 satırlık Elementor HTML'i ~500-1000 satırlık temiz HTML'e dönüştürür.
        
        Returns:
            Dict: Tüm analiz sonuçları veya None (fetch başarısız)
        """
        # HTML'i çek
        raw_html = await self.fetch_html(url)
        
        if not raw_html:
            return None
        
        # HTML'i temizle - Elementor wrapper'larını kaldır, sadece içerik taglarını al
        cleaned_html = self.clean_html(raw_html)
        
        # H1 analizi (temizlenmiş HTML ile)
        h1_result = self.analyze_h1(cleaned_html)
        
        # Schema analizi (orijinal HTML ile - schema script tagları body'de olabilir)
        schema_result = self.analyze_schema(raw_html)
        
        # Internal link çıkarma (temizlenmiş HTML ile)
        internal_links = self.extract_internal_links(cleaned_html, url, site_domain)
        
        return {
            "h1": h1_result,
            "schema": schema_result,
            "internal_links": internal_links,
            "internal_links_count": len(internal_links),
            "html_length": len(raw_html),
            "cleaned_html_length": len(cleaned_html)
        }


# Global analyzer instance
site_analyzer = SiteAnalyzer()
