# ============================================
# Rakip İçerik İstihbarat Sistemi V2
# Scraper - Sitemap Okuma ve İçerik Çekme
# ============================================

import asyncio
import httpx
import re
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from typing import List, Optional, Dict, Set
from urllib.parse import urljoin, urlparse
from dataclasses import dataclass
from datetime import datetime
from dateutil import parser as date_parser
import random

from config import settings


@dataclass
class PageContent:
    """Sayfa içerik veri yapısı"""
    url: str
    title: str
    content: str  # Temizlenmiş saf metin
    word_count: int
    fetched_at: datetime


@dataclass
class SitemapUrl:
    """Sitemap URL veri yapısı (lastmod ile)"""
    url: str
    lastmod: Optional[datetime] = None  # Sitemap'taki son değişiklik tarihi


@dataclass
class SitemapResult:
    """Sitemap sonuç veri yapısı"""
    urls: List[SitemapUrl]  # URL ve lastmod bilgisi
    nested_sitemaps: List[str]
    total_found: int
    errors: List[str]


class Scraper:
    """
    Web scraper sınıfı.
    Sitemap okuma ve sayfa içeriği çekme işlemlerini yapar.
    """
    
    # Yaygın User-Agent'lar (rotasyon için)
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    ]
    
    # İçerikten çıkarılacak HTML etiketleri
    EXCLUDE_TAGS = ['script', 'style', 'nav', 'header', 'footer', 'aside', 'noscript', 'iframe', 'form']
    
    # İçerik için öncelikli etiketler
    CONTENT_TAGS = ['article', 'main', '.content', '.post-content', '.entry-content', '#content', '.article-body']
    
    def __init__(self, delay: float = None, timeout: float = 30.0):
        """
        Args:
            delay: İstekler arası bekleme süresi (saniye)
            timeout: İstek zaman aşımı (saniye)
        """
        self.delay = delay or settings.REQUEST_DELAY_SECONDS
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
    
    def _get_random_user_agent(self) -> str:
        """Rastgele User-Agent seç"""
        return random.choice(self.USER_AGENTS)
    
    async def _get_client(self) -> httpx.AsyncClient:
        """HTTP client al veya oluştur"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": self._get_random_user_agent(),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
                }
            )
        return self._client
    
    async def close(self):
        """HTTP client'ı kapat"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
    
    async def _fetch_url(self, url: str) -> Optional[str]:
        """
        URL'den içerik çek.
        
        Args:
            url: Çekilecek URL
        
        Returns:
            HTML içerik veya None (hata durumunda)
        """
        try:
            client = await self._get_client()
            
            # User-Agent'ı rotasyonla değiştir
            headers = {"User-Agent": self._get_random_user_agent()}
            
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            
            return response.text
        
        except httpx.HTTPStatusError as e:
            print(f"⚠️ HTTP Hatası ({e.response.status_code}): {url}")
            return None
        except httpx.RequestError as e:
            print(f"⚠️ İstek Hatası: {url} - {str(e)}")
            return None
        except Exception as e:
            print(f"⚠️ Beklenmeyen Hata: {url} - {str(e)}")
            return None
    
    # ============================================
    # SITEMAP İŞLEMLERİ
    # ============================================
    
    async def find_sitemap(self, domain: str) -> List[str]:
        """
        Sitenin sitemap URL'lerini bul.
        Önce robots.txt'e bakar, bulamazsa yaygın konumları dener.
        
        Args:
            domain: Site domain'i (örn: "example.com")
        
        Returns:
            Bulunan sitemap URL'leri listesi
        """
        sitemaps = []
        base_url = f"https://{domain}" if not domain.startswith('http') else domain
        
        # 1. robots.txt'ten sitemap'leri bul
        robots_url = urljoin(base_url, "/robots.txt")
        robots_content = await self._fetch_url(robots_url)
        
        if robots_content:
            # Sitemap: satırlarını bul
            sitemap_pattern = re.compile(r'Sitemap:\s*(.+)', re.IGNORECASE)
            matches = sitemap_pattern.findall(robots_content)
            sitemaps.extend([m.strip() for m in matches])
        
        # 2. Eğer robots.txt'te yoksa, yaygın konumları dene
        if not sitemaps:
            common_paths = [
                "/sitemap.xml",
                "/sitemap_index.xml",
                "/sitemap-index.xml",
                "/sitemaps/sitemap.xml",
                "/wp-sitemap.xml",  # WordPress
                "/post-sitemap.xml",
                "/page-sitemap.xml",
            ]
            
            for path in common_paths:
                sitemap_url = urljoin(base_url, path)
                content = await self._fetch_url(sitemap_url)
                
                if content and '<?xml' in content[:100]:
                    sitemaps.append(sitemap_url)
                    break  # İlk bulunanı kullan
                
                await asyncio.sleep(0.5)  # Rate limiting
        
        return sitemaps
    
    async def parse_sitemap(self, sitemap_url: str, max_urls: int = 10000) -> SitemapResult:
        """
        Sitemap'i parse et ve URL'leri lastmod tarihleriyle birlikte çıkar.
        Nested (iç içe) sitemap'leri otomatik olarak açar.
        
        Args:
            sitemap_url: Sitemap URL'i
            max_urls: Maksimum URL sayısı limiti
        
        Returns:
            SitemapResult: Bulunan URL'ler (lastmod ile) ve hatalar
        """
        urls: Dict[str, SitemapUrl] = {}  # URL -> SitemapUrl mapping (dedupe için)
        nested_sitemaps: List[str] = []
        errors: List[str] = []
        
        async def _parse_single_sitemap(url: str):
            """Tek bir sitemap dosyasını parse et"""
            content = await self._fetch_url(url)
            
            if not content:
                errors.append(f"Sitemap yüklenemedi: {url}")
                return
            
            try:
                root = ET.fromstring(content)
                
                # XML namespace'leri
                namespaces = {
                    'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9',
                    'xhtml': 'http://www.w3.org/1999/xhtml'
                }
                
                # URL'leri bul (urlset)
                for url_elem in root.findall('.//sm:url', namespaces):
                    loc = url_elem.find('sm:loc', namespaces)
                    lastmod = url_elem.find('sm:lastmod', namespaces)
                    
                    if loc is not None and loc.text:
                        page_url = loc.text.strip()
                        
                        # lastmod tarihini parse et
                        lastmod_date = None
                        if lastmod is not None and lastmod.text:
                            try:
                                lastmod_date = date_parser.parse(lastmod.text.strip())
                            except Exception:
                                pass
                        
                        if len(urls) < max_urls:
                            urls[page_url] = SitemapUrl(url=page_url, lastmod=lastmod_date)
                
                # Namespace olmadan da dene (bazı sitemap'ler namespace kullanmıyor)
                if not urls:
                    for url_elem in root.findall('.//url'):
                        loc = url_elem.find('loc')
                        lastmod = url_elem.find('lastmod')
                        
                        if loc is not None and loc.text:
                            page_url = loc.text.strip()
                            
                            lastmod_date = None
                            if lastmod is not None and lastmod.text:
                                try:
                                    lastmod_date = date_parser.parse(lastmod.text.strip())
                                except Exception:
                                    pass
                            
                            if len(urls) < max_urls:
                                urls[page_url] = SitemapUrl(url=page_url, lastmod=lastmod_date)
                
                # Nested sitemap'leri bul (sitemapindex)
                for sitemap_elem in root.findall('.//sm:sitemap', namespaces):
                    loc = sitemap_elem.find('sm:loc', namespaces)
                    if loc is not None and loc.text:
                        nested_sitemaps.append(loc.text.strip())
                
                # Namespace olmadan
                for sitemap_elem in root.findall('.//sitemap'):
                    loc = sitemap_elem.find('loc')
                    if loc is not None and loc.text:
                        if loc.text.strip() not in nested_sitemaps:
                            nested_sitemaps.append(loc.text.strip())
            
            except ET.ParseError as e:
                errors.append(f"XML parse hatası ({url}): {str(e)}")
            except Exception as e:
                errors.append(f"Sitemap parse hatası ({url}): {str(e)}")
        
        # Ana sitemap'i parse et
        await _parse_single_sitemap(sitemap_url)
        
        # Nested sitemap'leri parse et
        for nested_url in nested_sitemaps[:20]:  # Max 20 nested sitemap
            if len(urls) >= max_urls:
                break
            
            await asyncio.sleep(self.delay)
            await _parse_single_sitemap(nested_url)
        
        return SitemapResult(
            urls=list(urls.values()),
            nested_sitemaps=nested_sitemaps,
            total_found=len(urls),
            errors=errors
        )
    
    # ============================================
    # İÇERİK ÇEKME İŞLEMLERİ
    # ============================================
    
    def _extract_text(self, html: str) -> str:
        """
        HTML'den saf metin çıkar.
        Menü, footer, reklam gibi kısımları atlar.
        
        Args:
            html: Ham HTML içerik
        
        Returns:
            Temizlenmiş saf metin
        """
        if not html:
            return ""
        
        soup = BeautifulSoup(html, 'lxml')
        
        # İstenmeyen etiketleri kaldır
        for tag in self.EXCLUDE_TAGS:
            for element in soup.find_all(tag):
                element.decompose()
        
        # Önce içerik alanını bulmaya çalış
        content = None
        
        for selector in self.CONTENT_TAGS:
            if selector.startswith('.'):
                content = soup.find(class_=selector[1:])
            elif selector.startswith('#'):
                content = soup.find(id=selector[1:])
            else:
                content = soup.find(selector)
            
            if content:
                break
        
        # İçerik alanı bulunamadıysa body'yi kullan
        if not content:
            content = soup.find('body') or soup
        
        # Metni çıkar
        text = content.get_text(separator=' ', strip=True)
        
        # Çoklu boşlukları temizle
        text = re.sub(r'\s+', ' ', text)
        
        return text.strip()
    
    def _extract_title(self, html: str) -> str:
        """HTML'den sayfa başlığını çıkar"""
        if not html:
            return ""
        
        soup = BeautifulSoup(html, 'lxml')
        
        # Önce <title> etiketine bak
        title_tag = soup.find('title')
        if title_tag and title_tag.string:
            return title_tag.string.strip()
        
        # <h1> etiketine bak
        h1_tag = soup.find('h1')
        if h1_tag:
            return h1_tag.get_text(strip=True)
        
        # og:title meta tag'ına bak
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return og_title['content'].strip()
        
        return ""
    
    async def fetch_page(self, url: str) -> Optional[PageContent]:
        """
        Sayfa içeriğini çek ve işle.
        
        Args:
            url: Sayfa URL'i
        
        Returns:
            PageContent: İşlenmiş sayfa içeriği veya None
        """
        html = await self._fetch_url(url)
        
        if not html:
            return None
        
        title = self._extract_title(html)
        content = self._extract_text(html)
        word_count = len(content.split()) if content else 0
        
        return PageContent(
            url=url,
            title=title,
            content=content,
            word_count=word_count,
            fetched_at=datetime.utcnow()
        )
    
    async def fetch_pages_batch(
        self, 
        urls: List[str], 
        batch_size: int = 5,
        progress_callback=None
    ) -> List[PageContent]:
        """
        Birden fazla sayfayı batch halinde çek.
        
        Args:
            urls: URL listesi
            batch_size: Her batch'teki URL sayısı
            progress_callback: İlerleme callback fonksiyonu
        
        Returns:
            PageContent listesi
        """
        results = []
        total = len(urls)
        
        for i in range(0, total, batch_size):
            batch = urls[i:i + batch_size]
            
            tasks = [self.fetch_page(url) for url in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in batch_results:
                if isinstance(result, PageContent):
                    results.append(result)
            
            # İlerleme bildirimi
            if progress_callback:
                progress_callback(min(i + batch_size, total), total)
            
            # Rate limiting
            if i + batch_size < total:
                await asyncio.sleep(self.delay)
        
        return results


# Global scraper instance
scraper = Scraper()
