# ============================================
# Entity Finder - Wikipedia Scraping ve Entity Bulma
# ============================================

import httpx
import re
from typing import List, Dict, Optional, Tuple
from urllib.parse import quote, urljoin, urlparse
from bs4 import BeautifulSoup
from dataclasses import dataclass

# ============================================
# BAĞLAMSAL ENTITY ÇIKARMA AYARLARI
# ============================================

# Hangi başlık hangi kategoriye girecek?
SECTION_MAPPING = {
    # HASTALIK / GEREKÇE (Neden yapılıyor?)
    "Condition": [
        "medical uses", "indications", "purpose", "diagnosis", "clinical applications",
        "uses", "applications", "treatment", "treatments", "therapy", "therapies",
        "diseases", "disorders", "conditions", "pathology", "pathologies"
    ],
    
    # YÖNTEM / SÜREÇ (Nasıl yapılıyor?)
    "Method": [
        "procedure", "technique", "method", "steps", "preparation", "placement",
        "process", "processes", "techniques", "methods", "procedures", "surgery",
        "surgical", "operation", "operations", "practice", "practices", "approach",
        "approaches", "protocol", "protocols"
    ],
    
    # MATERYAL (Ne kullanılıyor?)
    "Material": [
        "materials", "types", "instrumentation", "composition", "types of restoration",
        "equipment", "tools", "devices", "instruments", "technology", "technologies",
        "restoration", "restorations", "prosthesis", "prostheses", "implant", "implants"
    ],
    
    # RİSKLER (Ne olabilir?)
    "Risk": [
        "risks", "complications", "side effects", "failures", "contraindications", "disadvantages",
        "adverse", "safety", "precautions", "warnings", "contraindication", "failure",
        "complication", "side effect", "adverse effects", "safety concerns"
    ],
    
    # ALTERNATİFLER (Başka ne var?)
    "Alternative": [
        "alternatives", "related treatments", "related", "similar", "comparison",
        "vs", "versus", "other", "others", "types", "varieties", "variants"
    ],
    
    # GENEL KATEGORİLER (Dental sayfalar için)
    "Method": [
        "specialties", "specialty", "branches", "fields", "areas", "subfields",
        "education", "training", "career", "profession", "professional",
        "procedure", "technique", "method", "steps", "preparation", "placement",
        "process", "processes", "techniques", "methods", "procedures", "surgery",
        "surgical", "operation", "operations", "practice", "practices", "approach",
        "approaches", "protocol", "protocols"
    ]
}

# Makalede görmek istemediğin gürültü kelimeler (Blacklist)
BLACKLIST_KEYWORDS = [
    "isbn", "doi", "pmid", "journal", "citation", "history", "society", 
    "association", "united states", "century", "etymology", "referenc", 
    "external links", "see also", "edit", "help:", "file:", "special:"
]

@dataclass
class DentalEntity:
    """Bağlamsal entity veri yapısı"""
    name: str
    url: str
    category: str  # Condition, Material, Risk vb.
    source_section: str  # Hangi başlıktan bulduk?


class WikipediaEntityFinder:
    """Wikipedia'dan entity bulma servisi"""
    
    BASE_URL = "https://en.wikipedia.org"
    API_BASE = "https://en.wikipedia.org/api/rest_v1"
    
    # Wikipedia zorunlu User-Agent header'ı
    HEADERS = {
        "User-Agent": "RakipIstihbaratBot/2.0 (https://github.com/your-repo; contact@example.com) Python/httpx"
    }
    
    async def get_page_content_from_url(self, url: str) -> Optional[Dict]:
        """
        Wikipedia URL'inden sayfa içeriğini al
        
        Args:
            url: Wikipedia sayfası URL'i
        
        Returns:
            Sayfa içeriği ve bilgileri
        """
        try:
            async with httpx.AsyncClient(timeout=30.0, headers=self.HEADERS) as client:
                # URL'den sayfa anahtarını çıkar
                # Örn: https://en.wikipedia.org/wiki/Dentistry -> Dentistry
                page_key = url.split('/wiki/')[-1].split('#')[0].replace('_', ' ')
                page_title = page_key
                
                # HTML içeriğini al
                html_response = await client.get(url)
                
                if html_response.status_code == 200:
                    # API'den özet bilgisini al
                    try:
                        api_url = f"{self.API_BASE}/page/summary/{quote(page_key)}"
                        api_response = await client.get(api_url)
                        if api_response.status_code == 200:
                            api_data = api_response.json()
                            page_title = api_data.get("title", page_title)
                            summary = api_data.get("extract", "")
                        else:
                            summary = ""
                    except:
                        summary = ""
                    
                    return {
                        "title": page_title,
                        "url": url,
                        "html": html_response.text,
                        "summary": summary
                    }
        except Exception as e:
            print(f"⚠️ Wikipedia URL'den sayfa içeriği alınamadı: {e}")
        
        return None
    
    async def get_page_content(self, keyword: str) -> Optional[Dict]:
        """
        Wikipedia sayfasının içeriğini al
        
        Args:
            keyword: Anahtar kelime (örn: "dentistry")
        
        Returns:
            Sayfa içeriği ve bilgileri
        """
        try:
            async with httpx.AsyncClient(timeout=30.0, headers=self.HEADERS) as client:
                # Önce API'den sayfa özetini al
                api_url = f"{self.API_BASE}/page/summary/{quote(keyword)}"
                response = await client.get(api_url)
                
                if response.status_code == 200:
                    data = response.json()
                    page_title = data.get("title", keyword)
                    page_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")
                    
                    # HTML içeriğini al
                    html_url = f"{self.BASE_URL}/wiki/{quote(page_title)}"
                    html_response = await client.get(html_url)
                    
                    if html_response.status_code == 200:
                        return {
                            "title": page_title,
                            "url": page_url,
                            "html": html_response.text,
                            "summary": data.get("extract", "")
                        }
                elif response.status_code == 404:
                    # Sayfa bulunamadı, search yap
                    search_url = f"{self.API_BASE}/page/search/{quote(keyword)}"
                    search_response = await client.get(search_url, params={"limit": 1})
                    
                    if search_response.status_code == 200:
                        results = search_response.json()
                        pages = results.get("pages", [])
                        if pages:
                            first_page = pages[0]
                            page_title = first_page.get("title", keyword)
                            page_url = f"{self.BASE_URL}/wiki/{quote(first_page.get('key', page_title))}"
                            
                            html_response = await client.get(page_url)
                            if html_response.status_code == 200:
                                return {
                                    "title": page_title,
                                    "url": page_url,
                                    "html": html_response.text,
                                    "summary": first_page.get("extract", "")
                                }
        except Exception as e:
            print(f"⚠️ Wikipedia sayfa içeriği alınamadı: {e}")
        
        return None
    
    def extract_internal_links(self, html: str, base_keyword: str) -> List[Dict]:
        """
        HTML'den internal Wikipedia linklerini çıkar
        
        Args:
            html: Wikipedia sayfası HTML'i
            base_keyword: Anahtar kelime (ilgili linkleri filtrelemek için)
        
        Returns:
            Internal link listesi
        """
        soup = BeautifulSoup(html, 'html.parser')
        links = []
        seen_links = set()
        
        # Ana içerik bölümünü bul
        content_div = soup.find('div', {'id': 'mw-content-text'}) or soup.find('div', {'class': 'mw-parser-output'})
        if not content_div:
            content_div = soup
        
        # Tüm linkleri bul
        for link in content_div.find_all('a', href=True):
            href = link.get('href', '')
            
            # Sadece /wiki/ ile başlayan internal linkleri al
            if href.startswith('/wiki/'):
                # Red linkleri (henüz oluşturulmamış sayfalar) ve özel sayfaları atla
                if any(skip in href for skip in ['/wiki/File:', '/wiki/Image:', '/wiki/Category:', 
                                                  '/wiki/Template:', '/wiki/Help:', '/wiki/Wikipedia:',
                                                  '/wiki/User:', '/wiki/Talk:', '/wiki/Special:']):
                    continue
                
                # Fragment'leri kaldır (# ile başlayan kısımlar)
                href = href.split('#')[0]
                
                # Tam URL oluştur
                full_url = urljoin(self.BASE_URL, href)
                
                # Link adını al
                link_text = link.get_text(strip=True)
                
                # Sayfa adını çıkar (/wiki/Page_Name formatından)
                page_name = href.replace('/wiki/', '').replace('_', ' ')
                
                # Tekrarları önle
                if full_url not in seen_links and page_name:
                    seen_links.add(full_url)
                    links.append({
                        "url": full_url,
                        "title": page_name,
                        "link_text": link_text,
                        "page_key": href.replace('/wiki/', '')
                    })
        
        return links
    
    async def get_entity_info(self, page_key: str) -> Optional[Dict]:
        """
        Wikipedia sayfasından entity bilgilerini al
        
        Args:
            page_key: Wikipedia sayfa anahtarı (URL'den çıkarılan)
        
        Returns:
            Entity bilgileri
        """
        try:
            async with httpx.AsyncClient(timeout=30.0, headers=self.HEADERS) as client:
                # API'den sayfa özetini al
                api_url = f"{self.API_BASE}/page/summary/{quote(page_key)}"
                response = await client.get(api_url)
                
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "title": data.get("title", page_key),
                        "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                        "summary": data.get("extract", ""),
                        "description": data.get("description", "")
                    }
        except Exception as e:
            print(f"⚠️ Entity bilgisi alınamadı ({page_key}): {e}")
        
        return None
    
    def categorize_entity(self, entity_name: str, entity_summary: str, base_keyword: str) -> str:
        """
        Entity'yi kategorilere ayır
        
        Args:
            entity_name: Entity adı
            entity_summary: Entity özeti
            base_keyword: Anahtar kelime
        
        Returns:
            Kategori adı (örn: "cosmetic_dentistry", "restorative_dentistry")
        """
        text = (entity_name + " " + (entity_summary or "")).lower()
        base_lower = base_keyword.lower()
        
        # Kategori anahtar kelimeleri
        categories = {
            "cosmetic_dentistry": ["cosmetic", "aesthetic", "beauty", "smile", "whitening", "veneers", "crown", "appearance"],
            "restorative_dentistry": ["restorative", "restore", "repair", "replacement", "filling", "crown", "bridge", "implant"],
            "preventive_dentistry": ["preventive", "prevention", "clean", "hygiene", "oral health", "checkup"],
            "orthodontics": ["orthodontic", "orthodontics", "braces", "alignment", "straighten", "malocclusion"],
            "periodontics": ["periodontal", "periodontics", "gum", "gingivitis", "periodontitis"],
            "endodontics": ["endodontic", "endodontics", "root canal", "pulp"],
            "oral_surgery": ["surgery", "surgical", "extraction", "wisdom tooth", "oral surgery"],
            "prosthodontics": ["prosthodontic", "prosthodontics", "prosthesis", "denture", "prosthetic"],
            "pediatric_dentistry": ["pediatric", "children", "child", "pediatric dentistry", "kids"],
            "general_dentistry": []  # Varsayılan kategori
        }
        
        # Her kategori için skor hesapla
        category_scores = {}
        for cat_name, keywords in categories.items():
            score = 0
            for keyword in keywords:
                if keyword in text:
                    score += 1
            category_scores[cat_name] = score
        
        # En yüksek skorlu kategoriyi bul
        max_score = max(category_scores.values())
        if max_score > 0:
            best_category = max(category_scores, key=category_scores.get)
            return best_category
        
        # Eğer hiçbir kategori eşleşmediyse, anahtar kelime ile ilgili mi kontrol et
        if base_lower in text or any(word in text for word in base_lower.split()):
            return "general_dentistry"
        
        return "other"
    
    def extract_key_terms_from_page(self, html: str, base_keyword: str) -> List[str]:
        """
        Sayfa içeriğinden önemli terimleri çıkar (Wikipedia linklerinden)
        
        Args:
            html: Wikipedia sayfası HTML'i
            base_keyword: Anahtar kelime
        
        Returns:
            Önemli terim listesi (tüm internal link metinleri)
        """
        soup = BeautifulSoup(html, 'html.parser')
        
        # Ana içerik bölümünü bul
        content_div = soup.find('div', {'id': 'mw-content-text'}) or soup.find('div', {'class': 'mw-parser-output'})
        if not content_div:
            return []
        
        key_terms = []
        seen_terms = set()
        
        # Base keyword ile ilgili kelimeler
        base_lower = base_keyword.lower()
        base_words = set(base_lower.split())
        
        # Sayfada geçen TÜM Wikipedia linklerini al (bunlar önemli terimler)
        for link in content_div.find_all('a', href=True):
            href = link.get('href', '')
            if href.startswith('/wiki/'):
                # Özel sayfaları atla
                if any(skip in href for skip in ['/wiki/File:', '/wiki/Image:', '/wiki/Category:', 
                                                  '/wiki/Template:', '/wiki/Help:', '/wiki/Wikipedia:',
                                                  '/wiki/User:', '/wiki/Talk:', '/wiki/Special:']):
                    continue
                
                link_text = link.get_text(strip=True).lower()
                
                # Boş veya çok uzun terimleri atla
                if not link_text or len(link_text) > 50:
                    continue
                
                # Tekrarları önle
                if link_text in seen_terms:
                    continue
                
                seen_terms.add(link_text)
                
                # Tüm link metinlerini ekle (önemli terimler genelde link olur)
                # Örnek: "dental prosthesis", "titanium", "zirconia", "CAD/CAM" gibi
                words = link_text.split()
                if 1 <= len(words) <= 5:  # 1-5 kelime arası
                    key_terms.append(link_text)
        
        # İlk 100 önemli terimi döndür (sayfa içeriğindeki tüm linkler)
        return key_terms[:100]
    
    def calculate_relevance_score(self, entity_name: str, entity_summary: str, base_keyword: str, page_key_terms: List[str] = None) -> int:
        """
        Entity'nin anahtar kelime ile ilgili olma skorunu hesapla (0-100)
        
        Args:
            entity_name: Entity adı
            entity_summary: Entity özeti
            base_keyword: Anahtar kelime
            page_key_terms: Sayfa içeriğinden çıkarılan önemli terimler
        
        Returns:
            İlgili olma skoru (0-100)
        """
        text = (entity_name + " " + (entity_summary or "")).lower()
        base_lower = base_keyword.lower()
        base_words = base_lower.split()
        
        score = 0
        
        # Tam eşleşme
        if base_lower in text:
            score += 50
        
        # Kelime bazında eşleşme
        matched_words = sum(1 for word in base_words if word in text)
        if matched_words > 0:
            score += (matched_words / len(base_words)) * 30
        
        # Sayfa içeriğindeki önemli terimlerle eşleşme (EN ÖNEMLİSİ)
        if page_key_terms:
            entity_name_lower = entity_name.lower()
            entity_summary_lower = (entity_summary or "").lower()
            entity_text_lower = entity_name_lower + " " + entity_summary_lower
            
            for term in page_key_terms:
                # Entity adında veya summary'de bu terim geçiyor mu?
                if term in entity_text_lower:
                    # Terim ne kadar uzunsa o kadar önemli
                    term_words = term.split()
                    if len(term_words) == 1:
                        score += 20  # Tek kelime: titanium, zirconia gibi
                    elif len(term_words) == 2:
                        score += 35  # İki kelime: dental prosthesis, CAD/CAM gibi
                    else:
                        score += 50  # Üç+ kelime: çok spesifik terimler
                    
                    # Entity adı tam olarak sayfa içeriğindeki linklerden biriyse ekstra bonus
                    if term == entity_name_lower:
                        score += 30  # Tam eşleşme bonusu
        
        # İlgili terimler
        related_terms = {
            "dentistry": ["dental", "tooth", "teeth", "oral", "dentist", "prosthesis", "prosthetic", "implant", "crown", "bridge"],
            "dental": ["dentistry", "tooth", "teeth", "oral", "dentist", "prosthesis", "prosthetic", "implant", "crown", "bridge"],
            "implant": ["dental", "tooth", "teeth", "oral", "surgery", "prosthesis", "prosthetic", "titanium", "zirconia", "osseointegration"],
            "cosmetic": ["aesthetic", "beauty", "appearance", "smile", "whitening", "veneers"]
        }
        
        if base_lower in related_terms:
            for term in related_terms[base_lower]:
                if term in text:
                    score += 10
        
        return min(100, score)
    
    async def find_entities_from_keyword(self, keyword: str = None, wikipedia_url: str = None, max_links: int = 100) -> Tuple[List[Dict], Dict]:
        """
        Anahtar kelime veya URL'den Wikipedia'dan entity'leri bul
        
        Args:
            keyword: Anahtar kelime (örn: "dentistry") - opsiyonel
            wikipedia_url: Wikipedia sayfası URL'i - opsiyonel
            max_links: Maksimum kontrol edilecek link sayısı
        
        Returns:
            (entity_listesi, kategori_dict) tuple
        """
        # Ana sayfayı al
        if wikipedia_url:
            page_content = await self.get_page_content_from_url(wikipedia_url)
            # URL'den keyword çıkar (kategorilendirme için)
            if page_content:
                keyword = page_content.get("title", "")
        else:
            page_content = await self.get_page_content(keyword)
        
        if not page_content:
            return [], {}
        
        if not keyword:
            keyword = page_content.get("title", "")
        
        # Sayfa içeriğinden önemli terimleri çıkar (dental prosthesis, titanium, zirconia, CAD/CAM gibi)
        page_key_terms = self.extract_key_terms_from_page(page_content["html"], keyword)
        print(f"🔍 Sayfa içeriğinden {len(page_key_terms)} önemli terim çıkarıldı: {page_key_terms[:10]}")
        
        # Internal linkleri çıkar
        links = self.extract_internal_links(page_content["html"], keyword)
        
        # Maksimum link sayısını sınırla
        links = links[:max_links]
        
        entities = []
        categories = {}
        
        # Her linki kontrol et
        for i, link in enumerate(links):
            try:
                # Entity bilgilerini al
                entity_info = await self.get_entity_info(link["page_key"])
                
                if entity_info:
                    # Kategori belirle
                    category = self.categorize_entity(
                        entity_info["title"],
                        entity_info["summary"],
                        keyword
                    )
                    
                    # İlgili olma skorunu hesapla (sayfa içeriğindeki önemli terimlerle birlikte)
                    relevance_score = self.calculate_relevance_score(
                        entity_info["title"],
                        entity_info["summary"],
                        keyword,
                        page_key_terms=page_key_terms
                    )
                    
                    # Entity adı ve summary'yi küçük harfe çevir
                    entity_name_lower = entity_info["title"].lower()
                    entity_summary_lower = (entity_info["summary"] or "").lower()
                    entity_text = entity_name_lower + " " + entity_summary_lower
                    
                    # Entity adı sayfa içeriğindeki linklerden biri mi? (EN ÖNEMLİSİ)
                    # Örnek: "Dental prosthesis" sayfa içeriğinde link olarak geçiyorsa, bu entity mutlaka eklenmeli
                    is_in_page_links = entity_name_lower in page_key_terms
                    
                    # Entity adının kelimeleri sayfa içeriğindeki link metinlerinde geçiyor mu?
                    # Örnek: "Dental prosthesis" entity'si için, sayfa içeriğinde "dental prosthesis" veya "prosthesis" linki varsa
                    entity_words = set(entity_name_lower.split())
                    matches_link_words = any(
                        len(entity_words.intersection(set(term.split()))) >= 1  # En az 1 kelime eşleşiyorsa
                        for term in page_key_terms
                    )
                    
                    # Entity adı veya summary'de sayfa içeriğindeki önemli terimlerden biri geçiyor mu?
                    # Örnek: "titanium", "zirconia", "CAD/CAM" gibi terimler entity summary'sinde geçiyorsa
                    matches_key_term = any(
                        term in entity_text 
                        for term in page_key_terms  # TÜM önemli terimlerle kontrol et
                    )
                    
                    # Entity adı sayfa içeriğindeki linklerden biriyse veya önemli terimlerle eşleşiyorsa mutlaka ekle
                    # Ayrıca relevance score > 10 olanları da ekle (eşik düşürüldü)
                    if is_in_page_links or matches_link_words or matches_key_term or relevance_score > 10:
                        entity_data = {
                            "entity_name": entity_info["title"],
                            "wikipedia_url": entity_info["url"],
                            "wikipedia_summary": entity_info["summary"],
                            "category": category,
                            "relevance_score": relevance_score,
                            "is_related": relevance_score > 30
                        }
                        entities.append(entity_data)
                        
                        # Kategori sayısını güncelle
                        if category not in categories:
                            categories[category] = {
                                "name": category,
                                "display_name": category.replace("_", " ").title(),
                                "count": 0
                            }
                        categories[category]["count"] += 1
            except Exception as e:
                print(f"⚠️ Link işlenirken hata ({link['url']}): {e}")
                continue
        
        return entities, categories
    
    def _clean_text(self, text: str) -> str:
        """Metinden referansları temizle [1] gibi"""
        return re.sub(r'\[\d+\]', '', text).strip()
    
    def _determine_category(self, header_text: str) -> Optional[str]:
        """Başlık ismine bakarak kategoriyi bulur"""
        h_text = header_text.lower()
        for category, keywords in SECTION_MAPPING.items():
            if any(k in h_text for k in keywords):
                return category
        return None
    
    def _is_valid_link(self, title: str) -> bool:
        """Gürültülü linkleri eler"""
        if not title:
            return False
        t_lower = title.lower()
        # Blacklist kontrolü
        if any(b in t_lower for b in BLACKLIST_KEYWORDS):
            return False
        # Yıl kontrolü (1990s vb.)
        if re.match(r'^\d{4}s?$', title):
            return False
        return True
    
    async def extract_contextual_entities(self, wiki_url: str) -> Dict[str, List[DentalEntity]]:
        """
        Bağlamsal entity çıkarma - Başlık bazlı kategorilendirme
        
        Verilen URL'yi tarar ve kategorize edilmiş entity listesi döner.
        Her entity hangi başlık altından geldiğini bilir.
        
        Args:
            wiki_url: Wikipedia sayfası URL'i
        
        Returns:
            Kategori bazında entity listesi
        """
        print(f"📖 Bağlamsal Entity Çıkarma: {wiki_url}...")
        try:
            async with httpx.AsyncClient(timeout=30.0, headers=self.HEADERS) as client:
                resp = await client.get(wiki_url)
                if resp.status_code != 200:
                    print(f"⚠️ Hata: Sayfaya ulaşılamadı ({resp.status_code})")
                    return {}
                
                print(f"✅ Sayfa yüklendi ({len(resp.content)} bytes)")
                soup = BeautifulSoup(resp.content, 'html.parser')
                content_div = soup.find('div', id='mw-content-text')
                
                if not content_div:
                    print("⚠️ İçerik bölümü bulunamadı, alternatif arama yapılıyor...")
                    # Alternatif: mw-parser-output class'ını dene
                    content_div = soup.find('div', class_='mw-parser-output')
                    if not content_div:
                        print("⚠️ Hiçbir içerik bölümü bulunamadı!")
                        return {}
                
                print(f"✅ İçerik bölümü bulundu")
                
                extracted_data = {
                    "Condition": [],
                    "Method": [],
                    "Material": [],
                    "Risk": [],
                    "Alternative": []
                }
                
                seen_entities = set()  # Tekrarı önlemek için
                
                # Tüm başlıkları bul (h2 ve h3)
                headers = content_div.find_all(['h2', 'h3'])
                print(f"   📋 Toplam {len(headers)} başlık bulundu")
                
                # İlk 10 başlığı göster
                if headers:
                    print(f"   📝 İlk başlıklar: {[self._clean_text(h.get_text()) for h in headers[:10]]}")
                
                found_categories = []
                skipped_headers = []
                
                for idx, header in enumerate(headers):
                    header_text = self._clean_text(header.get_text())
                    
                    # "Contents", "References", "See also" gibi bölümleri atla
                    skip_sections = ["contents", "references", "see also", "external links", 
                                    "notes", "further reading", "navigation menu"]
                    if header_text.lower() in skip_sections:
                        skipped_headers.append(header_text)
                        continue
                    
                    category = self._determine_category(header_text)
                    
                    # Eğer bu başlık bizim haritamızda yoksa, "Method" kategorisine ekle (genel kategori)
                    if not category:
                        # Bazı genel başlıklar için otomatik kategori atama
                        header_lower = header_text.lower()
                        if any(word in header_lower for word in ["specialty", "specialties", "branch", "branches", 
                                                                  "field", "fields", "type", "types", "category", "categories",
                                                                  "education", "training", "career", "profession"]):
                            category = "Method"
                        elif any(word in header_lower for word in ["treatment", "treatments", "therapy", "therapies",
                                                                     "disease", "disorders", "condition", "conditions"]):
                            category = "Condition"
                        elif any(word in header_lower for word in ["material", "materials", "equipment", "tool", "tools",
                                                                     "device", "devices", "technology"]):
                            category = "Material"
                        else:
                            skipped_headers.append(f"{header_text} (kategori eşleşmedi)")
                            continue
                    
                    found_categories.append((header_text, category))
                    print(f"   ✅ [{idx+1}/{len(headers)}] Bölüm Bulundu: '{header_text}' -> [{category}]")
                    
                    # Başlığın altındaki içeriği taramaya başla
                    # Wikipedia'da başlıklar genelde <h2><span class="mw-headline">...</span></h2> şeklinde
                    # İçerik başlıktan sonraki tüm elementler, bir sonraki h2/h3'e kadar
                    entity_count_in_section = 0
                    elements_checked = 0
                    
                    # Başlığın parent'ını bul (genelde div veya section)
                    header_parent = header.parent
                    if not header_parent:
                        header_parent = content_div
                    
                    # Bu başlıktan sonraki tüm kardeş elementleri al
                    # Bir sonraki başlığa kadar
                    next_header = None
                    if idx + 1 < len(headers):
                        next_header = headers[idx + 1]
                    
                    # Başlıktan sonraki tüm elementleri topla
                    # Wikipedia'da başlıklar genelde div içinde değil, direkt içerikte
                    # Daha agresif yaklaşım: Başlıktan sonraki TÜM elementleri al
                    all_elements = []
                    
                    # Yöntem 1: find_next_siblings ile tüm kardeşleri al
                    next_siblings = header.find_next_siblings()
                    for sibling in next_siblings:
                        # Bir sonraki başlığa geldiysek dur
                        if sibling.name in ['h2', 'h3']:
                            break
                        if next_header and sibling == next_header:
                            break
                        all_elements.append(sibling)
                    
                    # Yöntem 2: Eğer hiç element bulunamadıysa, başlığın parent'ının içindeki tüm elementleri kontrol et
                    if not all_elements:
                        # Başlığın parent'ını bul
                        parent = header.parent
                        if parent:
                            # Parent içindeki tüm elementleri al (başlıktan sonraki)
                            all_children = parent.find_all(recursive=False)
                            header_index = None
                            for i, child in enumerate(all_children):
                                if child == header or header in child:
                                    header_index = i
                                    break
                            
                            if header_index is not None:
                                # Başlıktan sonraki tüm çocukları al
                                for child in all_children[header_index + 1:]:
                                    if child.name in ['h2', 'h3']:
                                        break
                                    all_elements.append(child)
                    
                    print(f"      📦 {len(all_elements)} element bulundu (başlıktan sonraki)")
                    
                    # Tüm elementlerdeki linkleri topla
                    for element in all_elements:
                        elements_checked += 1
                        # Tüm element tiplerini kontrol et
                        if element.name in ['p', 'ul', 'dl', 'ol', 'li', 'dt', 'dd', 'div', 'table', 'tbody', 'tr', 'td', 'span']:
                            links = element.find_all('a', href=True)
                            if links and elements_checked <= 5:  # İlk 5 elementte link varsa göster
                                print(f"      🔗 {element.name} elementinde {len(links)} link bulundu")
                            for link in links:
                                # title attribute yoksa link text'ini kullan
                                title = link.get('title') or link.get_text(strip=True)
                                href = link.get('href')
                                
                                # title boşsa href'den çıkar
                                if not title and href:
                                    if href.startswith('/wiki/'):
                                        title = href.replace('/wiki/', '').replace('_', ' ').split('#')[0]
                                
                                # Validasyonlar
                                if (title and href and href.startswith('/wiki/') and 
                                    self._is_valid_link(title) and 
                                    title not in seen_entities):
                                    
                                    # Özel sayfaları atla
                                    if any(skip in href for skip in ['/wiki/File:', '/wiki/Image:', 
                                                                     '/wiki/Category:', '/wiki/Template:', 
                                                                     '/wiki/Help:', '/wiki/Wikipedia:',
                                                                     '/wiki/User:', '/wiki/Talk:', 
                                                                     '/wiki/Special:']):
                                        continue
                                    
                                    full_url = f"https://en.wikipedia.org{href.split('#')[0]}"
                                    
                                    entity = DentalEntity(
                                        name=title,
                                        url=full_url,
                                        category=category,
                                        source_section=header_text
                                    )
                                    extracted_data[category].append(entity)
                                    seen_entities.add(title)
                                    entity_count_in_section += 1
                                    if entity_count_in_section <= 5:  # İlk 5 entity'yi göster
                                        print(f"         ✓ Entity bulundu: {title}")
                    
                    if entity_count_in_section > 0:
                        print(f"      ✅ {entity_count_in_section} entity bulundu ({elements_checked} element kontrol edildi)")
                    else:
                        print(f"      ⚠️  Bu bölümde entity bulunamadı ({elements_checked} element kontrol edildi)")
                        # Debug: İlk birkaç elementin ne olduğunu göster
                        if all_elements and len(all_elements) > 0:
                            debug_info = []
                            for e in all_elements[:3]:
                                link_count = len(e.find_all('a', href=True))
                                text_preview = e.get_text(strip=True)[:50] if e.get_text(strip=True) else "boş"
                                debug_info.append(f"{e.name}({link_count} link, '{text_preview}...')")
                            print(f"         🔍 İlk 3 element: {', '.join(debug_info)}")
                        # Debug: İlk elementin ne olduğunu göster
                        if all_elements:
                            first_elem = all_elements[0]
                            print(f"         🔍 İlk element: {first_elem.name}, içerik: {str(first_elem.get_text()[:100])}...")
                
                # Debug: Atlanan başlıkları göster
                if skipped_headers:
                    print(f"   ⏭️  Atlanan başlıklar ({len(skipped_headers)}): {', '.join(skipped_headers[:5])}")
                
                # Debug: Bulunan kategorileri göster
                if found_categories:
                    print(f"   📊 Bulunan kategoriler ({len(found_categories)}): {', '.join([f'{h}->{c}' for h, c in found_categories])}")
                else:
                    print(f"   ⚠️  Hiç kategori bulunamadı! Başlıklar: {[self._clean_text(h.get_text()) for h in headers[:10]]}")
                
                total_entities = sum(len(entities) for entities in extracted_data.values())
                print(f"✅ Toplam {total_entities} bağlamsal entity bulundu")
                
                # Her kategoriden kaç entity bulunduğunu göster
                for cat_name, entities_list in extracted_data.items():
                    if entities_list:
                        print(f"   📦 {cat_name}: {len(entities_list)} entity")
                
                return extracted_data
                
        except Exception as e:
            print(f"⚠️ Bağlamsal entity çıkarma hatası: {e}")
            import traceback
            traceback.print_exc()
            return {}
    
    async def find_entities_contextual(self, keyword: str = None, wikipedia_url: str = None) -> Tuple[List[Dict], Dict]:
        """
        Bağlamsal entity bulma - Yeni yaklaşım (başlık bazlı)
        
        Args:
            keyword: Anahtar kelime (opsiyonel)
            wikipedia_url: Wikipedia sayfası URL'i (opsiyonel)
        
        Returns:
            (entity_listesi, kategori_dict) tuple
        """
        # Ana sayfayı al
        if wikipedia_url:
            target_url = wikipedia_url
        elif keyword:
            page_content = await self.get_page_content(keyword)
            if not page_content:
                return [], {}
            target_url = page_content.get("url", "")
        else:
            return [], {}
        
        if not target_url:
            return [], {}
        
        # Bağlamsal entity'leri çıkar
        contextual_data = await self.extract_contextual_entities(target_url)
        
        entities = []
        categories = {}
        
        # Her kategori için entity'leri işle
        for category_name, dental_entities in contextual_data.items():
            if not dental_entities:
                continue
            
            # Kategoriyi kaydet
            if category_name not in categories:
                categories[category_name] = {
                    "name": category_name,
                    "display_name": category_name.replace("_", " ").title(),
                    "count": 0
                }
            
            # Her entity için Wikipedia bilgilerini al
            for dental_entity in dental_entities:
                try:
                    # URL'den page_key çıkar
                    page_key = dental_entity.url.split('/wiki/')[-1].split('#')[0]
                    
                    # Entity bilgilerini al
                    entity_info = await self.get_entity_info(page_key)
                    
                    if entity_info:
                        entity_data = {
                            "entity_name": entity_info["title"],
                            "wikipedia_url": entity_info["url"],
                            "wikipedia_summary": entity_info["summary"],
                            "category": category_name.lower(),  # Küçük harfe çevir (database için)
                            "relevance_score": 100,  # Bağlamsal entity'ler otomatik olarak yüksek skorlu
                            "is_related": True,
                            "source_section": dental_entity.source_section  # Kaynak bölüm bilgisi
                        }
                        entities.append(entity_data)
                        categories[category_name]["count"] += 1
                except Exception as e:
                    print(f"⚠️ Entity bilgisi alınamadı ({dental_entity.name}): {e}")
                    continue
        
        return entities, categories


# Global instance
entity_finder = WikipediaEntityFinder()

