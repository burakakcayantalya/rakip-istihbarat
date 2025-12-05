# ============================================
# Entity Analyzer - Wikipedia API ve Entity Eşleştirme
# ============================================

import httpx
import re
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from urllib.parse import quote

from entity_analyzer.models import MatchType


@dataclass
class EntityMatch:
    """Entity eşleşme sonucu"""
    entity_name: str
    entity_url: str
    match_type: MatchType
    match_score: int
    matched_words: List[str]
    wikipedia_summary: Optional[str] = None


class WikipediaAPI:
    """Wikipedia API servisi"""
    
    BASE_URL = "https://en.wikipedia.org/api/rest_v1"
    
    # Wikipedia zorunlu User-Agent header'ı
    HEADERS = {
        "User-Agent": "RakipIstihbaratBot/2.0 (https://github.com/your-repo; contact@example.com) Python/httpx"
    }
    
    async def search_entity(self, term: str) -> List[Dict]:
        """
        Wikipedia'da entity ara
        
        Args:
            term: Aranacak terim
        
        Returns:
            Entity listesi
        """
        try:
            async with httpx.AsyncClient(timeout=30.0, headers=self.HEADERS) as client:
                # Wikipedia search API
                url = f"{self.BASE_URL}/page/summary/{quote(term)}"
                response = await client.get(url)
                
                if response.status_code == 200:
                    data = response.json()
                    return [{
                        "title": data.get("title", term),
                        "extract": data.get("extract", ""),
                        "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                        "description": data.get("description", "")
                    }]
                elif response.status_code == 404:
                    # Arama yap
                    search_url = f"{self.BASE_URL}/page/search/{quote(term)}"
                    search_response = await client.get(search_url, params={"limit": 5})
                    
                    if search_response.status_code == 200:
                        results = search_response.json()
                        entities = []
                        for item in results.get("pages", [])[:5]:
                            entities.append({
                                "title": item.get("title", ""),
                                "extract": item.get("extract", ""),
                                "url": f"https://en.wikipedia.org/wiki/{quote(item.get('key', ''))}",
                                "description": item.get("description", "")
                            })
                        return entities
                    return []
                else:
                    return []
        except Exception as e:
            print(f"⚠️ Wikipedia API Hatası: {e}")
            return []
    
    async def get_entity_info(self, entity_name: str) -> Optional[Dict]:
        """
        Belirli bir entity'nin detaylı bilgisini al
        
        Args:
            entity_name: Entity adı
        
        Returns:
            Entity bilgisi
        """
        try:
            async with httpx.AsyncClient(timeout=30.0, headers=self.HEADERS) as client:
                url = f"{self.BASE_URL}/page/summary/{quote(entity_name)}"
                response = await client.get(url)
                
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "title": data.get("title", entity_name),
                        "extract": data.get("extract", ""),
                        "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                        "description": data.get("description", "")
                    }
        except Exception as e:
            print(f"⚠️ Wikipedia API Hatası: {e}")
        return None


class EntityMatcher:
    """Entity eşleştirme motoru"""
    
    def __init__(self):
        self.wikipedia = WikipediaAPI()
    
    def extract_words(self, text: str) -> List[str]:
        """
        Metinden kelimeleri çıkar (Türkçe karakter desteği ile)
        
        Args:
            text: Metin
        
        Returns:
            Kelime listesi
        """
        if not text:
            return []
        
        # Küçük harfe çevir
        text = text.lower()
        
        # Türkçe karakterleri normalize et
        text = text.replace("ı", "i").replace("ğ", "g").replace("ü", "u").replace("ş", "s").replace("ö", "o").replace("ç", "c")
        
        # Kelimeleri ayır (alfanumerik karakterler)
        words = re.findall(r'\b[a-z0-9]+\b', text)
        
        # Kısa kelimeleri filtrele (2 karakterden kısa)
        words = [w for w in words if len(w) >= 2]
        
        return words
    
    def calculate_match_score(self, search_term: str, entity_name: str, matched_words: List[str]) -> Tuple[MatchType, int]:
        """
        Eşleşme skorunu hesapla
        
        Args:
            search_term: Aranan terim
            entity_name: Entity adı
            matched_words: Eşleşen kelimeler
        
        Returns:
            (MatchType, score) tuple
        """
        search_lower = search_term.lower()
        entity_lower = entity_name.lower()
        
        # Tam eşleşme kontrolü
        if search_lower == entity_lower:
            return MatchType.EXACT, 100
        
        # Entity adında arama terimi geçiyor mu?
        if search_lower in entity_lower:
            # Kaç kelime eşleşti?
            search_words = self.extract_words(search_term)
            matched_count = len([w for w in search_words if w in entity_lower])
            
            if matched_count == len(search_words):
                return MatchType.EXACT, 90
            elif matched_count >= len(search_words) * 0.5:
                return MatchType.PARTIAL, 60
            else:
                return MatchType.LOW, 30
        
        # Kelime bazında eşleşme
        search_words = self.extract_words(search_term)
        entity_words = self.extract_words(entity_name)
        
        matched_count = len([w for w in search_words if w in entity_words])
        
        if matched_count == len(search_words) and len(search_words) > 0:
            return MatchType.PARTIAL, 70
        elif matched_count >= len(search_words) * 0.5:
            return MatchType.PARTIAL, 50
        elif matched_count > 0:
            return MatchType.LOW, 30
        else:
            return MatchType.LOW, 10
    
    async def match_entity(self, search_term: str, text: str) -> Optional[EntityMatch]:
        """
        Metinde entity ara ve eşleştir (SADECE KULLANICI ARAMA TERİMİ İÇİN - eski mantık)
        
        Args:
            search_term: Aranan terim
            text: Analiz edilecek metin
        
        Returns:
            EntityMatch veya None
        """
        if not text or not search_term:
            return None
        
        # Metinden kelimeleri çıkar
        text_lower = text.lower()
        search_lower = search_term.lower()
        search_words = self.extract_words(search_term)
        
        # Önce Wikipedia'da entity ara (öncelikle)
        entities = await self.wikipedia.search_entity(search_term)
        
        if not entities:
            return None
        
        # İlk entity'yi al (en uygun eşleşme)
        entity = entities[0]
        entity_name = entity.get("title", search_term)
        entity_name_lower = entity_name.lower()
        
        # Metinde arama teriminin kelimelerinden en az biri geçiyor mu?
        search_term_in_text = search_lower in text_lower
        search_words_in_text = any(word in text_lower for word in search_words if len(word) >= 2)
        
        # Entity adının kelimelerini çıkar ve metinde geçip geçmediğini kontrol et
        entity_words = self.extract_words(entity_name)
        entity_words_in_text = any(word in text_lower for word in entity_words if len(word) >= 2)
        
        # Eğer hiçbir bağlantı yoksa None döndür
        if not (search_term_in_text or search_words_in_text or entity_words_in_text):
            return None
        
        # Eşleşen kelimeleri bul
        matched_words = []
        matched_words.extend([w for w in search_words if w in text_lower])
        matched_words.extend([w for w in entity_words if w in text_lower and w not in matched_words])
        matched_words = list(set(matched_words))
        
        # Eşleşme skorunu hesapla
        match_type, match_score = self.calculate_match_score(search_term, entity_name, matched_words)
        
        # Eğer entity adı metinde geçiyorsa skoru artır
        if entity_name_lower in text_lower:
            match_score = min(100, match_score + 20)
            if match_type == MatchType.LOW:
                match_type = MatchType.PARTIAL
        
        return EntityMatch(
            entity_name=entity_name,
            entity_url=entity.get("url", ""),
            match_type=match_type,
            match_score=match_score,
            matched_words=matched_words,
            wikipedia_summary=entity.get("extract", "")
        )
    
    async def match_entities_from_text(self, text: str, min_word_length: int = 3) -> List[EntityMatch]:
        """
        Metindeki her kelimeyi ayrı ayrı Wikipedia'da ara ve entity eşleştirmesi yap
        
        Args:
            text: Analiz edilecek metin (meta_title, meta_description, url birleşimi)
            min_word_length: Minimum kelime uzunluğu (kısa kelimeleri filtrele)
        
        Returns:
            EntityMatch listesi (her kelime için bulunan entity'ler)
        """
        if not text:
            return []
        
        # Metinden kelimeleri çıkar
        words = self.extract_words(text)
        
        # Kısa ve anlamsız kelimeleri filtrele
        stop_words = {'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'as', 'is', 'are', 'was', 'were', 'be', 'been', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must', 'can', 'this', 'that', 'these', 'those', 'a', 'an'}
        
        # Minimum uzunluk ve stop words filtresi
        meaningful_words = [
            w for w in words 
            if len(w) >= min_word_length and w not in stop_words
        ]
        
        # Tekrarları kaldır ama sırayı koru
        seen = set()
        unique_words = []
        for w in meaningful_words:
            if w not in seen:
                seen.add(w)
                unique_words.append(w)
        
        if not unique_words:
            return []
        
        # Her kelime için Wikipedia'da entity ara
        matches = []
        text_lower = text.lower()
        
        for word in unique_words:
            try:
                # Wikipedia'da entity ara
                entities = await self.wikipedia.search_entity(word)
                
                if not entities:
                    continue
                
                # İlk entity'yi al
                entity = entities[0]
                entity_name = entity.get("title", word)
                entity_name_lower = entity_name.lower()
                
                # Kelime metinde geçiyor mu?
                word_in_text = word in text_lower
                
                # Entity adının kelimelerini çıkar
                entity_words = self.extract_words(entity_name)
                entity_words_in_text = any(ew in text_lower for ew in entity_words if len(ew) >= 2)
                
                # Eğer kelime veya entity adı metinde geçiyorsa eşleştirme yap
                if word_in_text or entity_words_in_text:
                    # Eşleşen kelimeleri bul
                    matched_words = [word] if word_in_text else []
                    matched_words.extend([ew for ew in entity_words if ew in text_lower and ew not in matched_words])
                    matched_words = list(set(matched_words))
                    
                    # Eşleşme skorunu hesapla
                    match_type, match_score = self.calculate_match_score(word, entity_name, matched_words)
                    
                    # Entity adı metinde geçiyorsa skoru artır
                    if entity_name_lower in text_lower:
                        match_score = min(100, match_score + 20)
                        if match_type == MatchType.LOW:
                            match_type = MatchType.PARTIAL
                    
                    matches.append(EntityMatch(
                        entity_name=entity_name,
                        entity_url=entity.get("url", ""),
                        match_type=match_type,
                        match_score=match_score,
                        matched_words=matched_words,
                        wikipedia_summary=entity.get("extract", "")
                    ))
            except Exception as e:
                # Hata durumunda devam et
                continue
        
        return matches


# Global instance
entity_matcher = EntityMatcher()

